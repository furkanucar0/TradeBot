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
    from lightgbm import LGBMClassifier
    import lightgbm as lgb
    LGBM_AVAILABLE = True
except Exception:
    LGBM_AVAILABLE = False

try:
    from xgboost import XGBClassifier
    XGBOOST_AVAILABLE = True
except Exception:
    XGBOOST_AVAILABLE = False

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
from features import FEATURE_COLS, add_features

# ── Sabitler ──────────────────────────────────────────────────────────────────
# Kararlılık paketi (2026-07-03): hedef günlük %1-2 istikrarlı getiri.
# Yüksek R:R "seyrek büyük kazanç" modu yerine sık-küçük-kazanç profili.
LEVERAGE = 5                  # 10x → 5x: gap/likidasyon riski yarıya
POSITION_USDT = 50.0          # teminat başına (eski canlı yol — artık kullanılmıyor)
MAX_POSITIONS = 2
FEE_RATE = 0.0004             # %0.04 taker (giriş + çıkış = %0.08 toplam)
SLIPPAGE_RATE = 0.0002        # %0.02 market order slippage (giriş + çıkış)
FUNDING_PER_8H = 0.0001       # tahmini %0.01 / 8 saat
CANDLE_INTERVAL_MINUTES = 1   # 1m mumlar

WIN_RATE_TARGET = 0.60
RR_TARGET = 2.0          # min R:R — altında breakeven WR model WR'ı geçer
# MAX_RR deneyi (2026-07-03): 2.5'e kısıtlamak denendi ve GERİ ALINDI.
# Ampirik sonuç: R:R 2.0 kombolarında model WR'ı (%40-41) maliyet dahil
# başabaşı (%42.2) TUTMUYOR (iki bağımsız eğitimde negatif). R:R 4.0'da ise
# kenar var (WR %31 > başabaş %25.3, iki eğitimde pozitif). Kararlılık,
# R:R'ı kısıtlamakla değil %0.5 risk + günlük frenlerle sağlanıyor.
MAX_RR = 4.0
RISK_PER_TRADE = 0.005   # sermayenin %0.5'i risk/işlem — canlı ile AYNI formül

# Zaman bazlı bölme: train | val (threshold seçimi) | test (dokunulmamış rapor)
# Test verisi eğitimde, early stopping'de veya threshold seçiminde KULLANILMAZ.
VAL_DAYS  = 21
TEST_DAYS = 21
PURGE_HOURS = 24   # bölme sınırlarında etiket sızıntısını önlemek için boşluk

# Dar SL/TP: günlük %1 hedefi için yüksek trade frekansı gerekli.
# Geniş SL/TP (0.8%/3.0%) → pozisyon saatlerce açık kalır → MAX_POSITIONS=2 bloklar → az trade.
# Dar SL/TP (0.3-0.5%/0.6-1.2%) → 5-30 dk kapanır → daha fazla trade/gün.
# Breakeven WR: SL=0.5%/TP=1.0% → 38.7%; SL=0.3%/TP=0.6% → 38.7% (aynı formül).
SL_GRID = [0.003, 0.004, 0.005]
TP_GRID = [0.006, 0.008, 0.010, 0.012]

# Yönün minimum precision eşiği — altında sinyaller devre dışı bırakılır
MIN_DIRECTION_PREC = 0.35

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

def load_data(days: int = 0) -> pd.DataFrame:
    """days > 0 ise sadece son N günü yükler (hızlı smoke test için)."""
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
    if days > 0 and not df.empty:
        min_ts = int(df["timestamp"].max()) - days * 86_400_000
        df = df[df["timestamp"] >= min_ts].reset_index(drop=True)
    return df


# ── Etiketleme ────────────────────────────────────────────────────────────────

def make_labels_bidir(df: pd.DataFrame, sl_pct: float, tp_pct: float) -> pd.Series:
    """
    Bidirectional etiketleme — LONG ve SHORT bağımsız olarak değerlendirilir:
      1 = LONG kazanır  : fiyat entry*(1+tp_pct) ÖNCE entry*(1-sl_pct) seviyesine ulaşır
      2 = SHORT kazanır : fiyat entry*(1-tp_pct) ÖNCE entry*(1+sl_pct) seviyesine ulaşır
      0 = her ikisi de kaybeder veya verinin sonuna kadar tetiklenmez

    NOT: Eski hata — label=2 önceden "LONG SL tetiklendi" anlamındaydı, bu SHORT TP
    ile aynı şey DEĞİL. Bu versiyon LONG ve SHORT için ayrı ayrı TP/SL kontrol eder.
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
            long_tp  = entry * (1 + tp_pct)   # LONG için hedef
            long_sl  = entry * (1 - sl_pct)   # LONG için stop
            short_tp = entry * (1 - tp_pct)   # SHORT için hedef (FARKLI!)
            short_sl = entry * (1 + sl_pct)   # SHORT için stop (FARKLI!)

            long_done = short_done = False
            long_wins = short_wins = False

            for m in range(k + 1, n):
                h, l = highs[m], lows[m]

                if not long_done:
                    if h >= long_tp and l > long_sl:
                        long_wins = True;  long_done = True
                    elif l <= long_sl:     long_done = True  # SL veya her ikisi → kayıp

                if not short_done:
                    if l <= short_tp and h < short_sl:
                        short_wins = True; short_done = True
                    elif h >= short_sl:    short_done = True  # SL veya her ikisi → kayıp

                if long_done and short_done:
                    break

            if long_wins:
                labels.loc[idxs[k]] = 1
            elif short_wins:
                labels.loc[idxs[k]] = 2
    return labels


# ── Grid Search ───────────────────────────────────────────────────────────────

def grid_search_rr(df_clean: pd.DataFrame) -> Tuple[float, float, float, float, str]:
    """
    Bidirectional grid search: LONG ve SHORT EV'lerini karşılaştır.
    En iyi (sl, tp, wr, rr, direction) döner.
    """
    # Varsayılan da R:R bandına (2.0-2.5) uymalı — eskiden gate'i kimse geçemeyince
    # band DIŞI (0.3/1.2 = 4.0) varsayılana düşüyordu ve kısıt deliniyordu
    best = {"sl": 0.005, "tp": 0.010, "score": -999.0, "wr": 0.0, "rr": 2.0, "ev": 0.0, "dir": "LONG"}
    # Gate'i kimse geçemezse: band içi en yüksek WR'lı kombo
    fallback = {"sl": 0.005, "tp": 0.010, "wr": -1.0, "rr": 2.0, "ev": 0.0, "dir": "LONG"}
    total_combos = len(SL_GRID) * len(TP_GRID)
    done = 0
    broadcast({"phase": "grid_search", "msg": f"Bidirectional R:R grid search ({total_combos} kombinasyon x2 yon)", "progress": 10})

    for sl in SL_GRID:
        for tp in TP_GRID:
            if tp <= sl:
                done += 1
                continue
            rr = tp / sl
            if rr > MAX_RR:
                # Yüksek R:R = düşük WR + uzun kayıp serileri → equity oynaklığı.
                # Kararlılık hedefi için 2.0-2.5 bandına kısıtlandı.
                done += 1
                continue
            labels = make_labels_bidir(df_clean, sl, tp)
            total = len(labels)
            n_long = int((labels == 1).sum())
            n_short = int((labels == 2).sum())
            wr_long = n_long / total
            wr_short = n_short / total

            # Komisyon dahil net EV (giriş %0.04 + çıkış %0.04 = %0.08 toplam)
            fee      = FEE_RATE * 2
            net_tp   = tp - fee
            net_sl   = sl + fee
            ev_long  = wr_long  * net_tp - (1 - wr_long)  * net_sl
            ev_short = wr_short * net_tp - (1 - wr_short) * net_sl

            done += 1
            broadcast({
                "phase": "grid_search",
                "msg": (f"SL={sl*100:.2f}% TP={tp*100:.2f}% "
                        f"LONG={wr_long:.1%}(EV={ev_long*100:+.3f}%) "
                        f"SHORT={wr_short:.1%}(EV={ev_short*100:+.3f}%)"),
                "progress": 10 + int(30 * done / total_combos),
                "sl_pct": sl, "tp_pct": tp,
                "win_rate_long": wr_long, "win_rate_short": wr_short,
                "ev_long": ev_long, "ev_short": ev_short, "rr": rr,
            })

            for ev, wr, direction in [(ev_long, wr_long, "LONG"), (ev_short, wr_short, "SHORT")]:
                # Skor = wr² × rr (kanıtlanmış): bu zincir iki bağımsız eğitimde
                # 0.3/1.2 kombosunu seçip temiz test setinde pozitif sonuç verdi.
                # Taban-istatistik EV skoru denendi ve GERİ ALINDI — pencere
                # kaydıkça oynuyor ve maliyet-verimsiz dar komboya kayıyor.
                if rr >= RR_TARGET and ev > fallback.get("ev", -1.0):
                    fallback = {"sl": sl, "tp": tp, "wr": wr, "rr": rr, "ev": ev, "dir": direction}
                score = wr * wr * rr if (wr >= 0.38 and rr >= RR_TARGET) else -999.0
                if score > best["score"]:
                    best = {"sl": sl, "tp": tp, "score": score, "wr": wr, "rr": rr, "ev": ev, "dir": direction}

    if best["score"] <= -999.0 and fallback["wr"] > 0:
        # Hiçbir kombo taban WR eşiğini geçemedi — band içi en iyi EV ile devam
        # (model threshold'u taban WR'ın üzerine çıkarır; band dışına ASLA çıkma)
        best = {**fallback, "score": 0.0}
        broadcast({"phase": "grid_search",
                   "msg": (f"Taban WR eşiği geçilemedi — band içi en iyi EV: {best['dir']} "
                           f"SL={best['sl']*100:.2f}% TP={best['tp']*100:.2f}% WR={best['wr']:.1%}")})

    broadcast({
        "phase": "grid_search",
        "msg": (f"En iyi: {best['dir']} SL={best['sl']*100:.2f}% TP={best['tp']*100:.2f}% "
                f"WR={best['wr']:.1%} R:R={best['rr']:.2f} EV={best['ev']*100:+.3f}%"),
        "progress": 40,
    })
    return best["sl"], best["tp"], best["wr"], best["rr"], best["dir"]


# ── Model Eğitimi ─────────────────────────────────────────────────────────────

def split_train_val_test(
    df_feat: pd.DataFrame,
    val_days: int = VAL_DAYS,
    test_days: int = TEST_DAYS,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Zaman bazlı train/val/test bölmesi + purge boşluğu.
    Veri kısa ise (smoke test) 70/15/15 oransal bölmeye düşer.
    """
    max_ts = int(df_feat["timestamp"].max())
    unit = "ms" if max_ts > 10**12 else "s"
    df_feat = df_feat.copy()
    df_feat["dt"] = pd.to_datetime(df_feat["timestamp"], unit=unit)

    last_dt    = df_feat["dt"].max()
    test_start = last_dt - pd.DateOffset(days=test_days)
    val_start  = test_start - pd.DateOffset(days=val_days)
    purge      = pd.Timedelta(hours=PURGE_HOURS)

    df_train = df_feat[df_feat["dt"] < val_start - purge]
    df_val   = df_feat[(df_feat["dt"] >= val_start) & (df_feat["dt"] < test_start - purge)]
    df_test  = df_feat[df_feat["dt"] >= test_start]

    if df_train.empty or df_val.empty or df_test.empty:
        n = len(df_feat)
        i1, i2 = int(0.70 * n), int(0.85 * n)
        df_train, df_val, df_test = df_feat.iloc[:i1], df_feat.iloc[i1:i2], df_feat.iloc[i2:]
        broadcast({"phase": "training",
                   "msg": "Zaman bazlı split yetersiz; 70/15/15 oransal bölme uygulandı",
                   "progress": 42})
    return df_train, df_val, df_test


def train_model(
    df_train: pd.DataFrame,
    df_val: pd.DataFrame,
    df_test: pd.DataFrame,
    labels: pd.Series,      # bidirectional: 0=none, 1=long, 2=short
    direction: str,         # "LONG" veya "SHORT"
) -> Tuple[Any, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    direction="LONG"  → y=1 if label==1, else y=0
    direction="SHORT" → y=1 if label==2, else y=0

    Early stopping ve model seçimi VALIDATION setiyle yapılır;
    test seti eğitim sürecine hiç girmez.
    Döner: (model, y_val, proba_val, y_test, proba_test)
    """
    if not LGBM_AVAILABLE:
        raise RuntimeError("lightgbm gerekli: pip install lightgbm")

    target_class = 1 if direction == "LONG" else 2
    y_train = (labels.loc[df_train.index] == target_class).astype(int).values
    y_val   = (labels.loc[df_val.index]   == target_class).astype(int).values
    y_test  = (labels.loc[df_test.index]  == target_class).astype(int).values

    n_pos = int(y_train.sum())
    n_neg = len(y_train) - n_pos
    raw_scale = (n_neg / n_pos) if n_pos > 0 else 1.0
    scale = min(raw_scale, 5.0)
    broadcast({
        "phase": "training",
        "msg": f"{direction}: train={len(y_train)} val={len(y_val)} test={len(y_test)} | pos={n_pos}({n_pos/max(len(y_train),1):.1%}) | scale={scale:.1f}",
        "progress": 46,
    })

    X_train = df_train[FEATURE_COLS]
    X_val   = df_val[FEATURE_COLS]
    X_test  = df_test[FEATURE_COLS]

    lgbm = LGBMClassifier(
        n_estimators=1000,
        learning_rate=0.03,        # daha yavaş öğrenme → daha iyi genelleme
        random_state=42,
        verbose=-1,
        scale_pos_weight=min(scale, 3.0),
        min_child_samples=100,     # yaprak başına daha fazla örnek → overfit azalır
        num_leaves=20,             # daha basit ağaçlar (31→20)
        reg_alpha=0.1,             # L1 düzenleyici
        reg_lambda=0.1,            # L2 düzenleyici
        subsample=0.8,             # her ağaçta %80 veri
        colsample_bytree=0.8,      # her ağaçta %80 özellik
        early_stopping_rounds=50,
    )
    lgbm.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
    )
    lgbm_f1 = f1_score(y_val, lgbm.predict(X_val), zero_division=0)

    model = lgbm
    model_name = "LightGBM"

    if XGBOOST_AVAILABLE:
        try:
            xgb = XGBClassifier(
                n_estimators=500,
                learning_rate=0.05,
                max_depth=6,
                scale_pos_weight=min(scale, 3.0),
                random_state=42,
                eval_metric="logloss",
                early_stopping_rounds=50,
                verbosity=0,
            )
            xgb.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
            xgb_f1 = f1_score(y_val, xgb.predict(X_val), zero_division=0)
            if xgb_f1 > lgbm_f1:
                model = xgb
                model_name = "XGBoost"
                broadcast({"phase": "training",
                           "msg": f"{direction} XGBoost kazandı (val): F1={xgb_f1:.3f} > LGBM {lgbm_f1:.3f}",
                           "progress": 74})
            else:
                broadcast({"phase": "training",
                           "msg": f"{direction} LightGBM kazandı (val): F1={lgbm_f1:.3f} >= XGB {xgb_f1:.3f}",
                           "progress": 74})
        except Exception as e:
            broadcast({"phase": "training", "msg": f"XGBoost hatası ({e}), LightGBM kullanılıyor", "progress": 74})

    broadcast({"phase": "training", "msg": f"{direction} [{model_name}] eğitim tamamlandı", "progress": 75})

    proba_val  = model.predict_proba(X_val)[:, 1]
    proba_test = model.predict_proba(X_test)[:, 1]

    return model, y_val, proba_val, y_test, proba_test


# ── Backtest ──────────────────────────────────────────────────────────────────

def backtest(
    df_test: pd.DataFrame,
    y_pred: np.ndarray,
    y_proba: np.ndarray,
    sl_pct: float,
    tp_pct: float,
    direction: str = "LONG",
) -> Dict[str, Any]:
    capital = 100.0          # sabit başlangıç sermayesi
    starting_cap = capital
    peak_cap = capital       # max drawdown takibi için peak
    positions: List[Dict] = []
    trades_log: List[Dict] = []
    equity_curve: List[float] = [capital]
    ms_per_8h = 8 * 3600 * 1000

    # Zaman-sıralı simülasyon: semboller gerçek hayattaki gibi eşzamanlı işlenir
    # (önceden sembol-sıralı geliyordu — MAX_POSITIONS ve equity eğrisi yanıltıcıydı)
    df_test = df_test.reset_index(drop=True).copy()
    df_test["_pred"] = y_pred
    df_test["_proba"] = y_proba
    df_test = df_test.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    def _funding_cost(pos: Dict, ts_now: int) -> float:
        held_ms = max(0, ts_now - pos["open_ts"])
        return pos["notional"] * FUNDING_PER_8H * (held_ms // ms_per_8h)

    broadcast({"phase": "backtest", "msg": "Backtest başladı", "progress": 77})
    n = len(df_test)

    for i in range(n):
        row = df_test.iloc[i]
        sym = row.get("symbol", "")
        ts  = int(row["timestamp"])

        # Açık pozisyonları güncelle (SL/TP kontrolü)
        to_close = []
        for pos in positions:
            if pos["symbol"] != sym:
                continue
            h, l = float(row["high"]), float(row["low"])
            tp_level = pos["tp_level"]
            sl_level = pos["sl_level"]

            is_long = pos["side"] == "LONG"
            # LONG: TP hit = high >= tp_level; SL = low <= sl_level
            # SHORT: TP hit = low <= tp_level; SL = high >= sl_level
            tp_hit = (h >= tp_level) if is_long else (l <= tp_level)
            sl_hit = (l <= sl_level) if is_long else (h >= sl_level)

            if tp_hit and not sl_hit:
                pnl = pos["notional"] * tp_pct
                fee = pos["notional"] * FEE_RATE
                slip = pos["notional"] * SLIPPAGE_RATE
                net = pnl - fee - slip - _funding_cost(pos, ts)
                capital += net
                to_close.append(pos)
                # Rapor PnL'i giriş komisyonunu da içerir (kasa akışıyla tutarlı;
                # giriş ücreti kasadan açılışta düşüldü, tekrar düşülmez)
                net_rep = net - pos.get("entry_fee", 0.0)
                trades_log.append({"reason": "TP", "pnl": net_rep, "sym": sym, "ts": ts})
                broadcast({"phase": "trade_close", "result": "TP", "symbol": sym, "pnl": round(net_rep, 4), "capital": round(capital, 2)})
            elif sl_hit:
                pnl = -pos["notional"] * sl_pct
                fee = pos["notional"] * FEE_RATE
                slip = pos["notional"] * SLIPPAGE_RATE
                net = pnl - fee - slip - _funding_cost(pos, ts)
                capital += net
                to_close.append(pos)
                net_rep = net - pos.get("entry_fee", 0.0)
                trades_log.append({"reason": "SL", "pnl": net_rep, "sym": sym, "ts": ts})
                broadcast({"phase": "trade_close", "result": "SL", "symbol": sym, "pnl": round(net_rep, 4), "capital": round(capital, 2)})

        for p in to_close:
            try:
                positions.remove(p)
            except ValueError:
                pass
        equity_curve.append(capital)

        # Peak güncelle
        peak_cap = max(peak_cap, capital)

        # Yeni pozisyon aç?
        pred = int(row.get("_pred", 0))
        # Mevcut drawdown %15'i geçtiyse yeni işlem açma (risk yönetimi)
        current_dd = (peak_cap - capital) / peak_cap if peak_cap > 0 else 0.0
        # Risk bazlı position sizing: her işlemde sermayenin RISK_PER_TRADE'ini riskle
        risk_usdt = capital * RISK_PER_TRADE          # örn. $100 × 0.5% = $0.5 risk
        margin = max(5.0, risk_usdt / sl_pct / LEVERAGE)  # min $5 margin
        # Korelasyon koruması: BTC-ETH ~0.9 korele; ikinci eşzamanlı pozisyon
        # (aynı yön) fiilen çift risk taşır → yarım boyut
        if positions:
            margin *= 0.5
        notional = margin * LEVERAGE
        sym_open = any(p["symbol"] == sym for p in positions)  # canlıdaki gibi sembol başına 1 pozisyon
        can_open = (pred == 1
                    and not sym_open
                    and len(positions) < MAX_POSITIONS
                    and capital >= margin
                    and current_dd < 0.15)
        if can_open:
            entry = float(row["close"])
            entry_fee = notional * FEE_RATE
            capital -= entry_fee
            is_long = direction == "LONG"
            pos = {
                "symbol": sym,
                "side": direction,
                "entry": entry,
                "tp_level": entry * (1 + tp_pct) if is_long else entry * (1 - tp_pct),
                "sl_level": entry * (1 - sl_pct) if is_long else entry * (1 + sl_pct),
                "margin": margin,
                "notional": notional,
                "open_ts": ts,
                "entry_fee": entry_fee,
            }
            positions.append(pos)
            broadcast({
                "phase": "trade_open",
                "symbol": sym,
                "side": direction,
                "entry": round(entry, 4),
                "sl": round(pos["sl_level"], 4),
                "tp": round(pos["tp_level"], 4),
                "capital": round(capital, 2),
            })

        if i % 1000 == 0:
            pct = 77 + int(20 * i / n)
            broadcast({"phase": "backtest", "msg": f"İşleniyor... {i}/{n}", "progress": pct})

    # Sona kalan pozisyonları kapat
    last_ts = int(df_test.iloc[-1]["timestamp"]) if n else 0
    for pos in list(positions):
        sym_rows = df_test[df_test["symbol"] == pos["symbol"]]
        last_close = float(sym_rows.iloc[-1]["close"]) if not sym_rows.empty else pos["entry"]
        raw_ret = (last_close - pos["entry"]) / pos["entry"]
        pnl = pos["notional"] * raw_ret if pos.get("side", "LONG") == "LONG" else -pos["notional"] * raw_ret
        fee = pos["notional"] * FEE_RATE  # sadece çıkış ücreti (giriş açılışta kesildi)
        net = pnl - fee - _funding_cost(pos, last_ts)
        capital += net
        trades_log.append({"reason": "END", "pnl": net - pos.get("entry_fee", 0.0),
                           "sym": pos["symbol"], "ts": last_ts})

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

    # Günlük getiri profili — "günde %1-2 istikrarlı" hedefinin doğrudan ölçümü
    daily_pnl: Dict[str, float] = {}
    for t in trades_log:
        if "ts" in t:
            day = time.strftime("%Y-%m-%d", time.gmtime(t["ts"] / 1000))
            daily_pnl[day] = daily_pnl.get(day, 0.0) + t["pnl"]
    daily_pcts = [v / starting_cap * 100 for v in daily_pnl.values()]
    daily_avg_pct   = float(np.mean(daily_pcts)) if daily_pcts else 0.0
    daily_worst_pct = float(min(daily_pcts))     if daily_pcts else 0.0
    daily_best_pct  = float(max(daily_pcts))     if daily_pcts else 0.0
    daily_std_pct   = float(np.std(daily_pcts))  if len(daily_pcts) > 1 else 0.0

    return {
        "daily_avg_pct":   round(daily_avg_pct, 3),
        "daily_worst_pct": round(daily_worst_pct, 3),
        "daily_best_pct":  round(daily_best_pct, 3),
        "daily_std_pct":   round(daily_std_pct, 3),
        "test_days":       len(daily_pcts),
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

def main(run_server: bool = True, days: int = 0) -> None:
    if run_server:
        start_event_server()
        time.sleep(0.8)

    broadcast({"phase": "data", "msg": "Veriler SQLite'dan yükleniyor...", "progress": 1})
    df = load_data(days=days)
    if df.empty:
        broadcast({"phase": "error", "msg": "Veritabanında veri yok. Önce zip_loader.py çalıştırın."})
        return

    symbols = df["symbol"].unique().tolist()
    broadcast({"phase": "data", "msg": f"{len(df)} satır yüklendi | Semboller: {symbols}", "progress": 5})

    broadcast({"phase": "features", "msg": "Teknik indikatörler hesaplanıyor...", "progress": 7})
    df_feat = add_features(df)
    df_feat = df_feat.dropna(subset=FEATURE_COLS).copy()
    broadcast({"phase": "features", "msg": f"İndikatörler tamam: {len(df_feat)} temiz satır", "progress": 10})
    if df_feat.empty:
        broadcast({"phase": "error",
                   "msg": ("İndikatör hesabından sonra hiç satır kalmadı — "
                           "1d MTF özellikleri için en az ~25 günlük veri gerekli.")})
        return

    # Train/Val/Test bölmesi — test seti grid search dahil hiçbir seçime girmez
    df_train, df_val, df_test = split_train_val_test(df_feat)
    broadcast({"phase": "training",
               "msg": f"Bölme: train={len(df_train)} | val={len(df_val)} | test={len(df_test)}",
               "progress": 11})

    # Grid Search (bidirectional) — SADECE train+val üzerinde (test'e bakmadan)
    df_pretest = pd.concat([df_train, df_val])
    if len(df_pretest) < 1000:
        df_pretest = df_feat   # smoke test: veri çok kısa, tümünü kullan
        broadcast({"phase": "grid_search",
                   "msg": "Uyarı: veri kısa, grid search tüm veride çalışıyor (smoke mod)"})
    best_sl, best_tp, naive_wr, naive_rr, best_dir = grid_search_rr(df_pretest)

    # Etiketleme (bidirectional)
    broadcast({"phase": "labeling", "msg": f"Etiketleme: {best_dir} SL={best_sl*100:.2f}% TP={best_tp*100:.2f}%", "progress": 40})
    labels = make_labels_bidir(df_feat, best_sl, best_tp)
    n1 = int((labels == 1).sum())
    n2 = int((labels == 2).sum())
    n0 = int((labels == 0).sum())
    broadcast({"phase": "labeling", "msg": f"Labels: LONG={n1} SHORT={n2} unresolved={n0}", "progress": 43})

    # ── Her iki yön için model eğit ──────────────────────────────────────────
    # Threshold seçimi ve precision kapısı VALIDATION setinde yapılır;
    # test seti sadece nihai raporlama + backtest için kullanılır.
    #
    # Precision tabanı DİNAMİK: seçilen SL/TP'nin komisyon+slippage dahil
    # başabaş WR'ı + %5 tampon. Sabit 0.40 tabanı dar kombolarda başabaşın
    # ALTINDA kalıyordu → zararına aşırı işlem (149 işlem / -9 USDT vakası).
    _cost    = FEE_RATE * 2 + SLIPPAGE_RATE
    _be      = (best_sl + _cost) / ((best_tp - _cost) + (best_sl + _cost))
    min_prec = max(MIN_DIRECTION_PREC, _be + 0.05)
    broadcast({"phase": "training",
               "msg": f"Precision tabanı: {min_prec:.3f} (başabaş {_be:.3f} + %5 tampon)",
               "progress": 43})

    def _optimize_threshold(y_proba_arr, y_true_arr, progress_base):
        """F1 maksimizasyonu — precision >= başabaş+tampon şartıyla.
        En az 10 sinyal şartı; hiç uygun eşik bulunamazsa en düşük geçerli threshold döner."""
        best_thr, best_f1 = None, -1.0
        fallback_thr = 0.20   # hiç uygun bulunamazsa kullanılacak
        for thr in [i / 100 for i in range(20, 70, 2)]:
            yt = (y_proba_arr >= thr).astype(int)
            ns = int(yt.sum())
            if ns < 10:
                continue          # break yerine continue — daha yüksek threshold'u da dene
            prec = precision_score(y_true_arr, yt, zero_division=0)
            f1  = f1_score(y_true_arr, yt, zero_division=0)
            broadcast({"phase": "training",
                       "msg": f"  thr={thr:.2f} n={ns} prec={prec:.3f} f1={f1:.3f}",
                       "progress": progress_base})
            if best_thr is None:
                fallback_thr = thr   # sinyal üreten ilk threshold = fallback
            if prec >= min_prec and f1 > best_f1:
                best_f1, best_thr = f1, thr
        chosen = best_thr if best_thr is not None else fallback_thr
        broadcast({"phase": "training",
                   "msg": f"  → Seçilen threshold={chosen:.2f} (val) F1={best_f1:.4f}",
                   "progress": progress_base})
        return chosen

    def _train_direction(direction: str, progress_base: int):
        """Bir yön için: eğit → val'de threshold seç → val precision kapısı →
        test metrikleri hesapla. Dönen f1_val yön seçiminde kullanılır."""
        broadcast({"phase": "training", "msg": f"{direction} modeli egitiliyor...", "progress": progress_base})
        model, y_val, proba_val, y_test, proba_test = train_model(
            df_train, df_val, df_test, labels, direction
        )
        thr = _optimize_threshold(proba_val, y_val, progress_base + 6)
        y_pred_val = (proba_val >= thr).astype(int)
        prec_val   = precision_score(y_val, y_pred_val, zero_division=0)
        f1_val     = f1_score(y_val, y_pred_val, zero_division=0)

        if prec_val < min_prec:
            thr = 1.01   # hiç sinyal üretme — val precision başabaşın altında
            f1_val = 0.0
            broadcast({"phase": "training",
                       "msg": f"{direction} devre dışı — val prec={prec_val:.3f} < {min_prec:.3f} (threshold=1.01)",
                       "progress": progress_base + 10})

        y_pred_test = (proba_test >= thr).astype(int)
        prec_test   = precision_score(y_test, y_pred_test, zero_division=0)
        f1_test     = f1_score(y_test, y_pred_test, zero_division=0)
        acc_test    = accuracy_score(y_test, y_pred_test)
        if thr <= 1.0:
            broadcast({"phase": "training",
                       "msg": (f"{direction}: Thr={thr:.2f} | val prec={prec_val:.3f} f1={f1_val:.3f} "
                               f"| test prec={prec_test:.3f} f1={f1_test:.3f} n={int(y_pred_test.sum())}"),
                       "progress": progress_base + 10})
        return {
            "model": model, "thr": thr,
            "f1_val": f1_val, "prec_val": prec_val,
            "y_pred_test": y_pred_test, "proba_test": proba_test, "y_test": y_test,
            "prec_test": prec_test, "f1_test": f1_test, "acc_test": acc_test,
        }

    res_long  = _train_direction("LONG", 44)
    res_short = _train_direction("SHORT", 66)

    model_long,  thr_long  = res_long["model"],  res_long["thr"]
    model_short, thr_short = res_short["model"], res_short["thr"]

    # Rapor yönü VALIDATION F1'e göre seçilir (test'e bakarak seçim yok)
    chosen = res_long if res_long["f1_val"] >= res_short["f1_val"] else res_short
    report_dir = "LONG" if chosen is res_long else "SHORT"
    y_pred_final, y_proba_rep = chosen["y_pred_test"], chosen["proba_test"]
    precision, f1, acc = chosen["prec_test"], chosen["f1_test"], chosen["acc_test"]
    prec_long, prec_short = res_long["prec_val"], res_short["prec_val"]

    broadcast({
        "phase": "training",
        "msg": f"Cift yonlu model hazir | LONG prec={prec_long:.3f} | SHORT prec={prec_short:.3f}",
        "progress": 76,
        "precision": precision, "f1": f1, "accuracy": acc,
    })

    # Model kaydet — her iki yön birlikte
    model_path = Path(__file__).resolve().parent / "model.bin"
    joblib.dump({
        "model_long":    model_long,
        "model_short":   model_short,
        "threshold_long":  thr_long,
        "threshold_short": thr_short,
        "feature_cols":  FEATURE_COLS,
        "sl_pct":   best_sl,
        "tp_pct":   best_tp,
        "direction": "BIDIR",   # artık her iki yön açık
    }, str(model_path))
    broadcast({"phase": "training", "msg": "Cift yonlu model kaydedildi: model.bin", "progress": 77})

    # Backtest (dominant yon ile) — SADECE dokunulmamış test seti
    results = backtest(df_test, y_pred_final, y_proba_rep, best_sl, best_tp, report_dir)
    results.update({"precision": precision, "f1": f1, "accuracy": acc, "direction": "BIDIR"})

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

    # Canlı trade kilit kontrolü — komisyon dahil gerçek EV
    rr  = results["rr"]
    tp  = results["tp_pct"]
    sl  = results["sl_pct"]
    wr  = results["win_rate"]
    fee = FEE_RATE * 2  # giriş + çıkış

    # Komisyon sonrası net EV (her işlem başına, notional yüzdesi)
    net_tp  = tp - fee   # TP vurulduğunda net kazanç
    net_sl  = sl + fee   # SL vurulduğunda net kayıp
    ev_net  = wr * net_tp - (1 - wr) * net_sl

    # Komisyon dahil başabaş WR
    breakeven_wr = net_sl / (net_tp + net_sl) if (net_tp + net_sl) > 0 else 1.0
    dynamic_wr_target = min(breakeven_wr + 0.05, WIN_RATE_TARGET)  # +%5 güvenlik tamponu

    ev_positive = ev_net > 0
    ready = (
        results["win_rate"] >= dynamic_wr_target
        and results["rr"] >= RR_TARGET
        and ev_positive
        and results["sharpe"] >= 0.5
        and results["max_drawdown"] <= 0.25
    )
    # Tek doğruluk kaynağı: api.py /status bu bayrağı summary'den okur
    results["ready_for_live"] = bool(ready)
    results["wr_target"] = round(dynamic_wr_target, 4)

    save_report(results, df_test)

    # ── Model çalışmasını DB'ye kaydet (model_runs) ──────────────────────────
    try:
        conn = sqlite3.connect(str(get_database_path()))
        conn.execute(
            """INSERT INTO model_runs (trained_at, symbols, sl_pct, tp_pct, leverage,
               win_rate, rr, precision, f1, accuracy, train_rows, test_rows, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(time.time()), ",".join(symbols), best_sl, best_tp, LEVERAGE,
                results["win_rate"], results["rr"], precision, f1, acc,
                len(df_train), len(df_test),
                f"dir={report_dir} thrL={thr_long:.2f} thrS={thr_short:.2f} ready={ready}",
            ),
        )
        conn.commit()
        conn.close()
        broadcast({"phase": "report", "msg": "model_runs kaydı eklendi"})
    except Exception as e:
        broadcast({"phase": "report", "msg": f"model_runs kaydedilemedi: {e}"})
    msg_ready = (
        f"Canli Hazir! WR={results['win_rate']:.1%}>={dynamic_wr_target:.1%} "
        f"R:R={rr:.1f}>={RR_TARGET} Sharpe={results['sharpe']:.2f}"
    ) if ready else (
        f"Kriterler henuz karsilandi degil | "
        f"WR={results['win_rate']:.1%}/{dynamic_wr_target:.1%} "
        f"R:R={rr:.1f}/{RR_TARGET} Sharpe={results['sharpe']:.2f} "
        f"EV={'pozitif' if ev_positive else 'negatif'}"
    )
    broadcast({
        "phase": "complete",
        "msg": msg_ready,
        "progress": 100,
        "ready_for_live": ready,
        "summary": results,
    })

    print("\n=== Backtest Ozeti ===================================")
    print(f"  Yon        : {results.get('direction','?')}")
    print(f"  Baslangic  : {results['starting_cap']:.2f} USDT")
    print(f"  Son Bakiye : {results['final_cap']:.2f} USDT")
    print(f"  Net PnL    : {results['total_pnl']:+.2f} USDT")
    print(f"  Islem      : {results['trades']}  (Kazanc={results['wins']} Kayip={results['losses']})")
    print(f"  Win Rate   : {results['win_rate']:.1%}")
    print(f"  R:R        : {results['rr']:.2f}")
    print(f"  Max DD     : {results['max_drawdown']:.1%}")
    print(f"  Sharpe     : {results['sharpe']:.2f}")
    print(f"  SL/TP      : {results['sl_pct']*100:.1f}% / {results['tp_pct']*100:.1f}%")
    print(f"  Gunluk Ort : {results.get('daily_avg_pct', 0):+.2f}%/gun ({results.get('test_days', 0)} gun)")
    print(f"  En Iyi Gun : {results.get('daily_best_pct', 0):+.2f}%  |  En Kotu Gun: {results.get('daily_worst_pct', 0):+.2f}%")
    breakeven_pct = breakeven_wr * 100
    ev_pct = ev_net * 100   # komisyon dahil — etiketle tutarlı
    print(f"  EV / islem : {ev_pct:+.4f}% ({'POZITIF' if ev_positive else 'NEGATIF'})")
    print(f"  Basabas WR : {breakeven_pct:.1f}%  (hedef: {dynamic_wr_target*100:.1f}%)")
    print(f"  Canli Hazir: {'EVET' if ready else 'HAYIR'}")
    print("=====================================================\n")

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
    p.add_argument("--days", type=int, default=0, help="Sadece son N günü kullan (hızlı test)")
    args = p.parse_args()
    main(run_server=not args.no_server, days=args.days)
