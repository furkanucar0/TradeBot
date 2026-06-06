"""
Futures Scalping Bot — Training & Backtest Engine
Run: python train_engine.py [--no-server]

Pipeline:
  1. SQLite'dan OHLCV yükle
  2. Teknik indikatörler ekle (ta kütüphanesi)
  3. SL/TP grid search → en iyi R:R bul
  4. LightGBM eğit (time-series split)
  5. Backtest (futures fee + funding)
  6. Sonuçları kaydet + broadcast
  7. FastAPI API server başlat
"""
import asyncio
import json
import os
import sqlite3
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score

try:
    from ta.momentum import RSIIndicator
    from ta.trend import MACD
    from ta.volatility import BollingerBands, AverageTrueRange
    TA_AVAILABLE = True
except Exception:
    TA_AVAILABLE = False

try:
    from lightgbm import LGBMClassifier
    LGBM_AVAILABLE = True
except Exception:
    LGBM_AVAILABLE = False

try:
    from fastapi import FastAPI, WebSocket, Request, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    FASTAPI_AVAILABLE = True
except Exception:
    FASTAPI_AVAILABLE = False

from database import get_database_path

# ── Sabitler ──────────────────────────────────────────────────────────────────
LEVERAGE = 5
POSITION_USDT = 50.0          # teminat başına (notional = 250 USDT)
MAX_POSITIONS = 2
FEE_RATE = 0.0004             # %0.04 taker (giriş + çıkış = %0.08 toplam)
FUNDING_PER_8H = 0.0001       # tahmini %0.01 / 8 saat
CANDLE_INTERVAL_MINUTES = 5

WIN_RATE_TARGET = 0.60
RR_TARGET = 2.0

SL_GRID = [0.003, 0.005, 0.008, 0.010]
TP_GRID = [0.006, 0.010, 0.015, 0.020]

FEATURE_COLS = [
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "bb_position", "bb_width",
    "atr_14", "volume_ratio",
    "ret_1", "ret_5", "ret_15",
]

REPORTS_DIR = Path(__file__).resolve().parent / "reports"

# ── Event Bus ─────────────────────────────────────────────────────────────────
_clients: List[asyncio.Queue] = []
_clients_lock = threading.Lock()
_events_log = Path(__file__).resolve().parent / "events.log"


def broadcast(ev: Dict[str, Any]) -> None:
    ev = {"ts": time.time(), **ev}
    try:
        with _events_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, default=str, ensure_ascii=False) + "\n")
    except Exception:
        pass
    with _clients_lock:
        for q in list(_clients):
            try:
                q.put_nowait(ev)
            except Exception:
                pass


# ── FastAPI App ───────────────────────────────────────────────────────────────
_app: Optional[Any] = None


def get_app() -> Optional[Any]:
    global _app
    if _app is not None or not FASTAPI_AVAILABLE:
        return _app

    _app = FastAPI(title="Futures Scalping Bot")
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

    @_app.get("/api/backtest-summary")
    async def backtest_summary():
        p = REPORTS_DIR / "backtest_summary.json"
        if not p.exists():
            raise HTTPException(404, "No backtest report")
        return json.loads(p.read_text(encoding="utf-8"))

    @_app.get("/sse")
    async def sse(request: Request):
        async def gen(q: asyncio.Queue):
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"data: {json.dumps(ev, default=str, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                with _clients_lock:
                    try:
                        _clients.remove(q)
                    except ValueError:
                        pass

        q: asyncio.Queue = asyncio.Queue()
        with _clients_lock:
            _clients.append(q)
        return StreamingResponse(gen(q), media_type="text/event-stream")

    @_app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue()
        with _clients_lock:
            _clients.append(q)
        try:
            while True:
                ev = await q.get()
                await ws.send_text(json.dumps(ev, default=str, ensure_ascii=False))
        except Exception:
            pass
        finally:
            with _clients_lock:
                try:
                    _clients.remove(q)
                except ValueError:
                    pass

    return _app


def _find_free_port(host: str, start: int) -> int:
    for port in range(start, start + 5):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return start


def start_event_server(host: str = "127.0.0.1", base_port: int = 8000) -> int:
    if not FASTAPI_AVAILABLE:
        print("FastAPI yok; olaylar events.log'a yazılacak")
        return base_port
    app = get_app()
    port = _find_free_port(host, base_port)

    def run():
        uvicorn.run(app, host=host, port=port, log_level="warning")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    broadcast({"phase": "server", "msg": f"API server {host}:{port} adresinde başlatıldı"})
    return port


# ── Veri Yükleme ──────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    db_path = get_database_path()
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query(
        "SELECT timestamp, symbol, open, high, low, close, volume FROM historical_market_data ORDER BY symbol, timestamp",
        conn,
    )
    conn.close()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = df["timestamp"].astype("int64")
    return df


# ── Teknik İndikatörler ───────────────────────────────────────────────────────

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    if not TA_AVAILABLE:
        raise RuntimeError("'ta' kütüphanesi gerekli: pip install ta")

    results = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("timestamp").copy()
        close = g["close"]

        g["rsi_14"] = RSIIndicator(close=close, window=14).rsi()

        macd_obj = MACD(close=close)
        g["macd"] = macd_obj.macd()
        g["macd_signal"] = macd_obj.macd_signal()
        g["macd_hist"] = macd_obj.macd_diff()

        bb = BollingerBands(close=close, window=20, window_dev=2)
        bb_high = bb.bollinger_hband()
        bb_low = bb.bollinger_lband()
        bb_mid = bb.bollinger_mavg()
        bb_w = (bb_high - bb_low) / bb_mid.replace(0, np.nan)
        g["bb_position"] = (close - bb_low) / (bb_high - bb_low).replace(0, np.nan)
        g["bb_width"] = bb_w

        g["atr_14"] = AverageTrueRange(high=g["high"], low=g["low"], close=close, window=14).average_true_range()

        vol_ma = g["volume"].rolling(20).mean()
        g["volume_ratio"] = g["volume"] / vol_ma.replace(0, np.nan)

        g["ret_1"] = close.pct_change(1)
        g["ret_5"] = close.pct_change(5)
        g["ret_15"] = close.pct_change(15)

        results.append(g)

    return pd.concat(results).reset_index(drop=True)


# ── Etiketleme ────────────────────────────────────────────────────────────────

def make_labels(df: pd.DataFrame, sl_pct: float, tp_pct: float) -> pd.Series:
    """
    Her satır için: entry = close, TP = entry*(1+tp_pct), SL = entry*(1-sl_pct)
    Sonraki mumlarda hangisi önce? TP → 1, SL → 0
    Aynı mumda ikisi de varsa (high>=TP ve low<=SL) → 0 (muhafazakâr)
    """
    labels = pd.Series(0, index=df.index, dtype=np.int8)
    for sym, grp in df.groupby("symbol"):
        idxs = grp.index.tolist()
        closes = grp["close"].values
        highs = grp["high"].values
        lows = grp["low"].values
        n = len(idxs)
        for k in range(n - 1):
            entry = closes[k]
            tp = entry * (1 + tp_pct)
            sl = entry * (1 - sl_pct)
            for m in range(k + 1, n):
                h, l = highs[m], lows[m]
                if h >= tp and l > sl:
                    labels.iloc[idxs[k]] = 1
                    break
                if l <= sl:
                    break
    return labels


# ── Grid Search ───────────────────────────────────────────────────────────────

def grid_search_rr(df_clean: pd.DataFrame) -> Tuple[float, float, float, float]:
    """
    SL/TP kombinasyonları üzerinde naive win-rate ve R:R hesapla.
    Gerçek label verisi (bağımsız model olmadan) kullanılır.
    En yüksek R:R * win_rate skoru olan kombinasyonu döner.
    """
    best = {"sl": SL_GRID[0], "tp": TP_GRID[-1], "score": -1.0, "wr": 0.0, "rr": 0.0}
    total_combos = len(SL_GRID) * len(TP_GRID)
    done = 0
    broadcast({"phase": "grid_search", "msg": f"R:R grid search başladı ({total_combos} kombinasyon)", "progress": 10})

    for sl in SL_GRID:
        for tp in TP_GRID:
            rr = tp / sl
            labels = make_labels(df_clean, sl, tp)
            wr = float(labels.mean())
            score = wr * rr
            done += 1
            broadcast({
                "phase": "grid_search",
                "msg": f"SL={sl*100:.1f}% TP={tp*100:.1f}% → WR={wr:.3f} R:R={rr:.2f}",
                "progress": 10 + int(30 * done / total_combos),
                "sl_pct": sl, "tp_pct": tp, "win_rate": wr, "rr": rr,
            })
            if score > best["score"]:
                best = {"sl": sl, "tp": tp, "score": score, "wr": wr, "rr": rr}

    broadcast({
        "phase": "grid_search",
        "msg": f"En iyi: SL={best['sl']*100:.1f}% TP={best['tp']*100:.1f}% WR={best['wr']:.3f} R:R={best['rr']:.2f}",
        "progress": 40,
    })
    return best["sl"], best["tp"], best["wr"], best["rr"]


# ── Model Eğitimi ─────────────────────────────────────────────────────────────

def train_model(
    df_feat: pd.DataFrame,
    labels: pd.Series,
    test_months: int = 6,
) -> Tuple[Any, pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    if not LGBM_AVAILABLE:
        raise RuntimeError("lightgbm gerekli: pip install lightgbm")

    max_ts = int(df_feat["timestamp"].max())
    unit = "ms" if max_ts > 10**12 else "s"
    df_feat = df_feat.copy()
    df_feat["dt"] = pd.to_datetime(df_feat["timestamp"], unit=unit)

    last_dt = df_feat["dt"].max()
    test_start = last_dt - pd.DateOffset(months=test_months)

    df_train = df_feat[df_feat["dt"] < test_start]
    df_test = df_feat[df_feat["dt"] >= test_start]

    if df_train.empty or df_test.empty:
        split = int(0.8 * len(df_feat))
        df_train = df_feat.iloc[:split]
        df_test = df_feat.iloc[split:]
        broadcast({"phase": "training", "msg": "Zaman bazlı split yetersiz; 80/20 bölme uygulandı", "progress": 42})

    X_train = df_train[FEATURE_COLS]
    y_train = labels.loc[df_train.index].values
    X_test = df_test[FEATURE_COLS]
    y_test = labels.loc[df_test.index].values

    broadcast({"phase": "training", "msg": f"Eğitim: {len(X_train)} satır | Test: {len(X_test)} satır", "progress": 45})

    model = LGBMClassifier(n_estimators=500, learning_rate=0.05, random_state=42, verbose=-1)
    model.fit(X_train, y_train)

    broadcast({"phase": "training", "msg": "Model eğitimi tamamlandı", "progress": 75})

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    return model, df_train, df_test, y_test, y_pred, y_proba


# ── Backtest ──────────────────────────────────────────────────────────────────

def backtest(
    df_test: pd.DataFrame,
    y_pred: np.ndarray,
    y_proba: np.ndarray,
    sl_pct: float,
    tp_pct: float,
) -> Dict[str, Any]:
    capital = POSITION_USDT * MAX_POSITIONS  # başlangıç sermayesi
    starting_cap = capital
    cash = capital
    positions: List[Dict] = []
    trades_log: List[Dict] = []
    equity_curve: List[float] = [capital]
    candles_per_8h = int(8 * 60 / CANDLE_INTERVAL_MINUTES)

    df_test = df_test.reset_index(drop=True).copy()
    df_test["_pred"] = y_pred
    df_test["_proba"] = y_proba

    broadcast({"phase": "backtest", "msg": "Backtest başladı", "progress": 77})
    n = len(df_test)

    for i in range(n):
        row = df_test.iloc[i]
        sym = row.get("symbol", "")

        # Açık pozisyonları güncelle (SL/TP kontrolü)
        to_close = []
        for pos in positions:
            if pos["symbol"] != sym:
                continue
            h, l = float(row["high"]), float(row["low"])
            tp_level = pos["tp_level"]
            sl_level = pos["sl_level"]
            candles_held = i - pos["open_i"]

            # Funding maliyeti (her 8 saatlik mum grubunda)
            if candles_held > 0 and candles_held % candles_per_8h == 0:
                funding_cost = pos["notional"] * FUNDING_PER_8H
                capital -= funding_cost
                cash -= funding_cost

            # TP hit
            if h >= tp_level and l > sl_level:
                pnl_pct = tp_pct * LEVERAGE
                pnl = pos["notional"] * tp_pct
                fee = pos["notional"] * FEE_RATE * 2
                net = pnl - fee
                capital += net
                cash += pos["margin"]
                to_close.append(pos)
                trades_log.append({"reason": "TP", "pnl": net, "sym": sym})
                broadcast({"phase": "trade_close", "result": "TP", "symbol": sym, "pnl": round(net, 4), "capital": round(capital, 2)})
            # SL hit (veya her ikisi aynı mumda → SL)
            elif l <= sl_level:
                pnl = -pos["notional"] * sl_pct
                fee = pos["notional"] * FEE_RATE * 2
                net = pnl - fee
                capital += net
                cash += pos["margin"]
                to_close.append(pos)
                trades_log.append({"reason": "SL", "pnl": net, "sym": sym})
                broadcast({"phase": "trade_close", "result": "SL", "symbol": sym, "pnl": round(net, 4), "capital": round(capital, 2)})

        for p in to_close:
            try:
                positions.remove(p)
            except ValueError:
                pass
        equity_curve.append(capital)

        # Yeni pozisyon aç?
        pred = int(row.get("_pred", 0))
        if pred == 1 and len(positions) < MAX_POSITIONS and cash >= POSITION_USDT:
            entry = float(row["close"])
            margin = POSITION_USDT
            notional = margin * LEVERAGE
            entry_fee = notional * FEE_RATE
            capital -= entry_fee
            cash -= margin
            pos = {
                "symbol": sym,
                "entry": entry,
                "tp_level": entry * (1 + tp_pct),
                "sl_level": entry * (1 - sl_pct),
                "margin": margin,
                "notional": notional,
                "open_i": i,
            }
            positions.append(pos)
            broadcast({"phase": "trade_open", "symbol": sym, "entry": round(entry, 4), "capital": round(capital, 2)})

        if i % 1000 == 0:
            pct = 77 + int(20 * i / n)
            broadcast({"phase": "backtest", "msg": f"İşleniyor... {i}/{n}", "progress": pct})

    # Sona kalan pozisyonları kapat
    for pos in list(positions):
        sym_rows = df_test[df_test["symbol"] == pos["symbol"]]
        last_close = float(sym_rows.iloc[-1]["close"]) if not sym_rows.empty else pos["entry"]
        pnl = pos["notional"] * ((last_close - pos["entry"]) / pos["entry"])
        fee = pos["notional"] * FEE_RATE * 2
        net = pnl - fee
        capital += net
        cash += pos["margin"]
        trades_log.append({"reason": "END", "pnl": net, "sym": pos["symbol"]})

    trades = len(trades_log)
    wins = sum(1 for t in trades_log if t["pnl"] > 0)
    total_pnl = capital - starting_cap
    win_rate = wins / trades if trades else 0.0

    # Max drawdown
    peak = starting_cap
    max_dd = 0.0
    running = starting_cap
    for t in trades_log:
        running += t["pnl"]
        peak = max(peak, running)
        dd = (peak - running) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    # Sharpe (basit)
    pnls = [t["pnl"] for t in trades_log]
    sharpe = (np.mean(pnls) / np.std(pnls) * np.sqrt(252)) if len(pnls) > 1 and np.std(pnls) > 0 else 0.0

    return {
        "starting_cap": starting_cap,
        "final_cap": round(capital, 4),
        "total_pnl": round(total_pnl, 4),
        "trades": trades,
        "wins": wins,
        "losses": trades - wins,
        "win_rate": round(win_rate, 4),
        "rr": round(tp_pct / sl_pct, 2),
        "max_drawdown": round(max_dd, 4),
        "sharpe": round(float(sharpe), 4),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "leverage": LEVERAGE,
        "equity_curve": equity_curve,
        "details": trades_log,
    }


# ── Rapor Kaydet ──────────────────────────────────────────────────────────────

def save_report(results: Dict[str, Any], df_test: pd.DataFrame) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    summary = {k: v for k, v in results.items() if k not in ("equity_curve", "details")}
    (REPORTS_DIR / "backtest_summary.json").write_text(
        json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        eq = results["equity_curve"]
        plt.figure(figsize=(10, 4))
        plt.plot(eq)
        plt.axhline(results["starting_cap"], color="gray", linestyle="--", alpha=0.5)
        plt.title(f"Equity Curve  |  WR={results['win_rate']:.1%}  R:R={results['rr']:.2f}  Sharpe={results['sharpe']:.2f}")
        plt.xlabel("Mum")
        plt.ylabel("Sermaye (USDT)")
        plt.grid(True, linestyle="--", alpha=0.3)
        plt.tight_layout()
        plt.savefig(str(REPORTS_DIR / "equity_curve.png"), dpi=120)
        plt.close()
        broadcast({"phase": "report", "msg": "equity_curve.png kaydedildi"})
    except Exception as e:
        broadcast({"phase": "report", "msg": f"Grafik kaydedilemedi: {e}"})

    broadcast({"phase": "report", "msg": "backtest_summary.json kaydedildi"})


# ── Ana Fonksiyon ─────────────────────────────────────────────────────────────

def main(run_server: bool = True) -> None:
    if run_server:
        start_event_server()
        time.sleep(0.8)

    broadcast({"phase": "data", "msg": "Veriler SQLite'dan yükleniyor...", "progress": 1})
    df = load_data()
    if df.empty:
        broadcast({"phase": "error", "msg": "Veritabanında veri yok. Önce zip_loader.py çalıştırın."})
        return

    symbols = df["symbol"].unique().tolist()
    broadcast({"phase": "data", "msg": f"{len(df)} satır yüklendi | Semboller: {symbols}", "progress": 5})

    broadcast({"phase": "features", "msg": "Teknik indikatörler hesaplanıyor...", "progress": 7})
    df_feat = add_features(df)
    df_feat = df_feat.dropna(subset=FEATURE_COLS).copy()
    broadcast({"phase": "features", "msg": f"İndikatörler tamam: {len(df_feat)} temiz satır", "progress": 10})

    # Grid Search
    best_sl, best_tp, naive_wr, naive_rr = grid_search_rr(df_feat)

    # Etiketleme (en iyi SL/TP ile)
    broadcast({"phase": "labeling", "msg": f"Etiketleme: SL={best_sl*100:.1f}% TP={best_tp*100:.1f}%", "progress": 40})
    labels = make_labels(df_feat, best_sl, best_tp)
    broadcast({"phase": "labeling", "msg": f"Label dağılımı: 1={labels.sum()} 0={(labels==0).sum()}", "progress": 43})

    # Model
    broadcast({"phase": "training", "msg": "LightGBM eğitimi başlıyor...", "progress": 44})
    model, df_train, df_test, y_test, y_pred, y_proba = train_model(df_feat, labels)

    precision = precision_score(y_test, y_pred, zero_division=0)
    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    broadcast({
        "phase": "training",
        "msg": f"Precision={precision:.4f}  F1={f1:.4f}  Accuracy={acc:.4f}",
        "progress": 76,
        "precision": precision, "f1": f1, "accuracy": acc,
    })

    # Model kaydet
    model_path = Path(__file__).resolve().parent / "model.bin"
    joblib.dump({"model": model, "feature_cols": FEATURE_COLS, "sl_pct": best_sl, "tp_pct": best_tp}, str(model_path))
    broadcast({"phase": "training", "msg": f"Model kaydedildi: {model_path.name}", "progress": 77})

    # Backtest
    results = backtest(df_test, y_pred, y_proba, best_sl, best_tp)
    results.update({"precision": precision, "f1": f1, "accuracy": acc})

    broadcast({
        "phase": "backtest",
        "msg": (
            f"Backtest tamamlandı | WR={results['win_rate']:.1%} "
            f"R:R={results['rr']:.2f} PnL={results['total_pnl']:+.2f} USDT "
            f"MaxDD={results['max_drawdown']:.1%}"
        ),
        "progress": 98,
        "summary": results,
    })

    save_report(results, df_test)

    # Canlı trade kilit kontrolü
    ready = results["win_rate"] >= WIN_RATE_TARGET and results["rr"] >= RR_TARGET
    broadcast({
        "phase": "complete",
        "msg": f"{'✓ Canlı trade kriterleri karşılandı!' if ready else '✗ Kriterler henüz karşılanmadı (WR>60% + R:R>2.0 gerekli)'}",
        "progress": 100,
        "ready_for_live": ready,
        "summary": results,
    })

    print("\n─── Backtest Özeti ───────────────────────────────")
    print(f"  Başlangıç  : {results['starting_cap']:.2f} USDT")
    print(f"  Son Bakiye : {results['final_cap']:.2f} USDT")
    print(f"  Net PnL    : {results['total_pnl']:+.2f} USDT")
    print(f"  İşlem      : {results['trades']}  (Kazanç={results['wins']} Kayıp={results['losses']})")
    print(f"  Win Rate   : {results['win_rate']:.1%}")
    print(f"  R:R        : {results['rr']:.2f}")
    print(f"  Max DD     : {results['max_drawdown']:.1%}")
    print(f"  Sharpe     : {results['sharpe']:.2f}")
    print(f"  Canlı Hazır: {'EVET' if ready else 'HAYIR'}")
    print("──────────────────────────────────────────────────\n")

    if run_server:
        broadcast({"phase": "server", "msg": "Sunucu çalışıyor, Ctrl+C ile durdurun"})
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--no-server", action="store_true", help="API sunucusunu başlatma")
    args = p.parse_args()
    main(run_server=not args.no_server)
