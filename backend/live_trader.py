"""
Binance USDT-M Futures Live Trader
Paper mode (testnet=True): Gerçek Binance verisi, emir yok, demo kasa takibi
Live mode (testnet=False): Gerçek emir (backtest kriterleri zorunlu)
"""
import asyncio
import concurrent.futures
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

import ccxt
import joblib
import numpy as np
import pandas as pd
import requests as _req

from config import (
    CANDLE_BUFFER_SIZE, DAILY_LOSS_LIMIT_PCT, DAILY_PROFIT_LOCK_PCT,
    DECISIONS_KEEP_DAYS, DEMO_START_BALANCE, FEE_RATE, LEVERAGE, LOOP_INTERVAL,
    MAE_NEAR_SL_RATIO, MAX_POSITIONS, METRICS_BUFFER_SIZE, METRICS_POLL_S,
    MFE_LOW_RATIO, MFE_NEAR_TP_RATIO,
    RETRAIN_DAYS, RETRAIN_MAX_AGE_DAYS, RETRAIN_MIN_GAP_S, RETRAIN_MIN_TRADES,
    RETRAIN_STUCK_ALERT_S, RETRAIN_STUCK_FORCE_S,
    RISK_PER_TRADE, SIGNAL_MARGIN, SILENT_PERSIST_GAP_S, SLIPPAGE_RATE,
    SYMBOLS, TIMEFRAME, WATCHDOG_ALERT_GAP_S, WATCHDOG_STALL_S,
)
from database import Database
from features import FEATURE_COLS, latest_features
from health import compute_health
from risk_gate import RiskGate, panic_active
import telegram_notifier as tg

MODEL_PATH = Path(__file__).resolve().parent / "model.bin"

_stop_flag = False
_model_updating = False        # retrain sırasında yeni pozisyon açmayı engeller
_manual_close_requests: set   = set()   # manuel kapatılacak semboller
broadcast: Callable[[Dict[str, Any]], None] = lambda ev: None

# K-30: ana sinyal döngüsü kalp atışı. 19-21 Temmuz olayında döngü günlerce
# sessizce durdu ama API/health yeşil kaldı — bekçi bu ayrımı görünür kılar.
_heartbeat = {"loop_ts": 0.0, "note": "başlatılmadı"}


def heartbeat_age() -> Optional[float]:
    """Ana döngünün son kalp atışından bu yana geçen saniye (None = hiç atmadı)."""
    return (time.time() - _heartbeat["loop_ts"]) if _heartbeat["loop_ts"] else None

# Günlük fren yüzdeleri config.py'de: DAILY_LOSS_LIMIT_PCT / DAILY_PROFIT_LOCK_PCT


def request_close(symbol: str) -> None:
    """Frontend'den gelen manuel kapatma isteği."""
    _manual_close_requests.add(symbol)


def stop() -> None:
    global _stop_flag
    _stop_flag = True


_panic_close_requested = False   # /panik: tüm pozisyonları kapat + botu durdur


def panic_close_all() -> None:
    """FAZ 3 (K-19) kill switch: açık pozisyonlar market'ten kapatılır,
    ardından bot durur. Kilit dosyası (panic.lock) api tarafında yazılır."""
    global _panic_close_requested
    _panic_close_requested = True


_fng_cache: Dict[str, Any] = {"value": 50, "ts": 0.0}   # Fear & Greed cache (1 saat)


def _fetch_order_book_imbalance(symbol: str) -> float:
    """Bid/Ask imbalance: +1 = tamamen bids, -1 = tamamen asks."""
    try:
        raw = symbol.replace("/", "")
        resp = _req.get(
            "https://fapi.binance.com/fapi/v1/depth",
            params={"symbol": raw, "limit": 20},
            timeout=3,
        )
        data = resp.json()
        bid_vol = sum(float(b[1]) for b in data.get("bids", []))
        ask_vol = sum(float(a[1]) for a in data.get("asks", []))
        total   = bid_vol + ask_vol
        return (bid_vol - ask_vol) / total if total > 0 else 0.0
    except Exception:
        return 0.0


def _fetch_fear_greed() -> int:
    """Alternative.me Fear & Greed Index, 1 saatte bir güncellenir (0=korku, 100=açgözlülük)."""
    now = time.time()
    if now - _fng_cache["ts"] < 3600:
        return int(_fng_cache["value"])
    try:
        resp = _req.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        val = int(resp.json()["data"][0]["value"])
        _fng_cache["value"] = val
        _fng_cache["ts"]    = now
        return val
    except Exception:
        return 50


def _load_model() -> Dict[str, Any]:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model bulunamadı: {MODEL_PATH}")
    return joblib.load(str(MODEL_PATH))


def _build_exchange() -> ccxt.Exchange:
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret  = os.getenv("BINANCE_API_SECRET", "")

    exchange = ccxt.binanceusdm({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })

    # Yerel saat ile Binance sunucu saati arasındaki farkı düzelt
    try:
        server_ms = _req.get("https://fapi.binance.com/fapi/v1/time", timeout=5).json()["serverTime"]
        diff = int(time.time() * 1000) - server_ms
        exchange.options["timeDifference"] = diff
    except Exception:
        pass

    return exchange


def _fetch_ohlcv(exchange: ccxt.Exchange, symbol: str, limit: int = 100) -> pd.DataFrame:
    # Public REST — ccxt'in exchangeInfo yükleme hatasını atlatır, auth gerekmez.
    # Binance tek istekte en fazla 1500 mum verir; limit > 1500 için geriye doğru sayfalar.
    raw_sym = symbol.replace("/", "")  # BTC/USDT → BTCUSDT
    all_rows: List[list] = []
    end_time: Optional[int] = None
    remaining = limit
    while remaining > 0:
        batch = min(remaining, 1500)
        params: Dict[str, Any] = {"symbol": raw_sym, "interval": TIMEFRAME, "limit": batch}
        if end_time is not None:
            params["endTime"] = end_time
        resp = _req.get("https://fapi.binance.com/fapi/v1/klines", params=params, timeout=10)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        all_rows = rows + all_rows
        end_time = int(rows[0][0]) - 1   # bir önceki sayfanın bitişi
        remaining -= len(rows)
        if len(rows) < batch:
            break
    df = pd.DataFrame(all_rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "qav", "num_trades", "taker_base", "taker_quote", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = df["timestamp"].astype(int)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def _fetch_recent_klines(symbol: str, limit: int = 3) -> list:
    """Son N 1m mumu ham liste olarak döner (REST fiyat fallback'i için)."""
    raw_sym = symbol.replace("/", "")
    resp = _req.get(
        "https://fapi.binance.com/fapi/v1/klines",
        params={"symbol": raw_sym, "interval": TIMEFRAME, "limit": limit},
        timeout=8,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_ohlcv_1d(symbol: str, limit: int = 60) -> pd.DataFrame:
    """Başlangıçta 1d OHLCV çek — _d1_buffer için, sadece bir kez kullanılır."""
    raw_sym = symbol.replace("/", "")
    resp = _req.get(
        "https://fapi.binance.com/fapi/v1/klines",
        params={"symbol": raw_sym, "interval": "1d", "limit": limit},
        timeout=10,
    )
    resp.raise_for_status()
    rows = resp.json()
    df = pd.DataFrame(rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "qav", "num_trades", "taker_base", "taker_quote", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = df["timestamp"].astype(int)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def _compute_features(df: pd.DataFrame, d1_df: Optional[pd.DataFrame] = None,
                      metrics_df: Optional[pd.DataFrame] = None) -> Optional[Dict[str, float]]:
    """
    Eğitimle BİREBİR AYNI özellik hesaplaması — features.latest_features kullanır.
    Eksik/NaN özellik varsa None döner (varsayılan değerlerle sinyal ÜRETMEZ;
    eski davranış nötr varsayılanlarla trade açabiliyordu).
    metrics_df: canlı funding+OI buffer'ı (ts, funding_rate, open_interest).
    """
    try:
        return latest_features(df, d1_df, metrics_df)
    except Exception as e:
        broadcast({"phase": "error", "msg": f"Özellik hesaplama hatası: {e}"})
        return None


def _predict_bidir(model_payload: Dict, features: Dict[str, float],
                   thr_adj: float = 0.0) -> tuple:
    """
    Çift yönlü tahmin: (pred_long, proba_long, pred_short, proba_short)
    thr_adj: F&G gibi filtrelerden gelen eşik artışı
    """
    cols = model_payload.get("feature_cols", FEATURE_COLS)
    X    = pd.DataFrame([[features.get(c, 0.0) for c in cols]], columns=cols)

    # Yeni çift yönlü model
    m_long  = model_payload.get("model_long")
    m_short = model_payload.get("model_short")
    thr_l   = float(model_payload.get("threshold_long",  0.5)) + thr_adj
    thr_s   = float(model_payload.get("threshold_short", 0.5)) + thr_adj

    if m_long and m_short:
        p_long  = float(m_long.predict_proba(X)[0][1])
        p_short = float(m_short.predict_proba(X)[0][1])
        return (1 if p_long  >= thr_l else 0), p_long, \
               (1 if p_short >= thr_s else 0), p_short

    # Eski tek yönlü model — geriye dönük uyumluluk
    m_old   = model_payload.get("model")
    old_dir = model_payload.get("direction", "LONG")
    thr_old = float(model_payload.get("threshold", 0.5)) + thr_adj
    if m_old:
        p = float(m_old.predict_proba(X)[0][1])
        pred = 1 if p >= thr_old else 0
        if old_dir == "LONG":
            return pred, p, 0, 0.0
        else:
            return 0, 0.0, pred, p
    return 0, 0.0, 0, 0.0


def _set_leverage(exchange: ccxt.Exchange, symbol: str) -> None:
    try:
        exchange.set_leverage(LEVERAGE, symbol)
    except Exception as e:
        broadcast({"phase": "server", "msg": f"Kaldıraç ayarlanamadı ({symbol}): {e}"})


def _open_live_position(exchange: ccxt.Exchange, symbol: str, side: str,
                        entry_price: float, sl_pct: float, tp_pct: float,
                        notional: float) -> Optional[str]:
    try:
        qty = notional / entry_price
        try:
            qty = float(exchange.amount_to_precision(symbol, qty))
        except Exception:
            qty = round(qty, 3)   # markets yüklenemezse BTC/ETH step'ine uygun fallback
        order_side = "buy" if side == "LONG" else "sell"

        order = exchange.create_order(symbol, "market", order_side, qty)
        order_id = order.get("id", "")

        if side == "LONG":
            sl_price = round(entry_price * (1 - sl_pct), 4)
            tp_price = round(entry_price * (1 + tp_pct), 4)
            close_side = "sell"
        else:
            sl_price = round(entry_price * (1 + sl_pct), 4)
            tp_price = round(entry_price * (1 - tp_pct), 4)
            close_side = "buy"

        exchange.create_order(symbol, "stop_market", close_side, qty,
                              params={"stopPrice": sl_price, "reduceOnly": True})
        exchange.create_order(symbol, "take_profit_market", close_side, qty,
                              params={"stopPrice": tp_price, "reduceOnly": True})

        broadcast({"phase": "trade_open", "symbol": symbol, "side": side,
                   "entry": entry_price, "sl": sl_price, "tp": tp_price,
                   "qty": qty, "leverage": LEVERAGE})
        return order_id
    except Exception as e:
        err_msg = f"Pozisyon açılamadı ({symbol}): {e}"
        broadcast({"phase": "error", "msg": err_msg})
        tg.send_async(f"❌ <b>Emir Hatası | {symbol}</b>\n{err_msg}")
        return None


# Sembol başına h1_atr_ratio geçmişi — volatilite cezası göreli artışa bakar.
# NOT: h1_atr_ratio doğal olarak ~7-17 bandındadır (1h ATR >> 1m ATR); mutlak
# değere ceza kesmek eşiği kalıcı olarak tavana yapıştırıp TÜM sinyalleri
# öldürüyordu. Bu yüzden kendi yakın geçmişinin medyanına oranlanır.
_atr_ratio_hist: Dict[str, Deque[float]] = {}


def _calc_dynamic_threshold(base_adj: float, features: Dict[str, float], sym: str = "") -> float:
    """F&G baz ayarı üzerine volatilite + trend hizalama düzeltmesi ekler."""
    # Volatilite cezası: 1h ATR oranı KENDİ son 24 saat medyanının üzerindeyse
    vol_ratio = features.get("h1_atr_ratio", 1.0)
    hist = _atr_ratio_hist.setdefault(sym, deque(maxlen=2880))  # ~24 saat (30 sn döngü)
    hist.append(vol_ratio)
    baseline = sorted(hist)[len(hist) // 2]   # medyan
    rel = vol_ratio / baseline if baseline > 0 else 1.0
    vol_penalty = max(0.0, (rel - 1.0) * 0.12)   # medyanın %10 üstü → +0.012 eşik

    # Trend hizalama bonusu: 3/3 hizalı → eşiği biraz düşür
    tf_score  = features.get("tf_alignment", 1.5)
    tf_bonus  = (tf_score - 1.5) * (-0.025)             # 3/3 → -0.038; 0/3 → +0.038

    # ADX trend gücü bonusu
    adx       = features.get("h1_adx", 25.0)
    adx_bonus = -0.03 if adx > 30 else (0.03 if adx < 18 else 0.0)

    adj = base_adj + vol_penalty + tf_bonus + adx_bonus
    # K-13 (B-1): Filtreler sadece ELER, asla kolaylaştırmaz — ayar 0'ın altına
    # inemez. Kalibrasyona göre 0.50-0.55 dilimi sınırda zararına; bonusların
    # tabanı oraya çekmesine izin verilmez.
    return float(np.clip(adj, 0.0, 0.25))


def _self_evaluate(result: str, mfe: float, mae: float,
                   sl_pct: float, tp_pct: float) -> tuple:
    """
    K-21 (FAZ 5): kapanışta öz-değerlendirme. MFE (lehte en uç hareket) ve
    MAE (aleyhte en uç hareket) hedef mesafelere oranlanır — "stop dar mı,
    TP uzak mı" sorusuna işlem başına sayısal etiket üretir.
    Döner: (kod, açıklama)
    """
    mfe_r = mfe / tp_pct if tp_pct > 0 else 0.0
    mae_r = mae / sl_pct if sl_pct > 0 else 0.0
    if result == "SL":
        if mfe_r >= MFE_NEAR_TP_RATIO:
            return "STOP_DAR", f"SL yedi ama fiyat TP'nin %{mfe_r*100:.0f}'ine ulaşmıştı — stop dar / TP uzak sinyali"
        if mfe_r < MFE_LOW_RATIO:
            return "YANLIS_YON", f"Lehte hareket TP'nin yalnız %{mfe_r*100:.0f}'i — giriş yönü baştan tersti"
        return "NORMAL_SL", f"Lehte hareket TP'nin %{mfe_r*100:.0f}'i — olağan kayıp"
    if result == "TP":
        if mae_r >= MAE_NEAR_SL_RATIO:
            return "SANSLI_TP", f"TP vurdu ama fiyat SL'in %{mae_r*100:.0f}'ine dayanmıştı — şanslı kazanç"
        if mae_r <= MFE_LOW_RATIO:
            return "TEMIZ_TP", f"Aleyhte hareket SL'in yalnız %{mae_r*100:.0f}'i — temiz kazanç"
        return "NORMAL_TP", f"Aleyhte hareket SL'in %{mae_r*100:.0f}'i — olağan kazanç"
    return "MANUEL", f"MFE TP'nin %{mfe_r*100:.0f}'i · MAE SL'in %{mae_r*100:.0f}'i"


def _proba_scale(proba: float, rr: float) -> float:
    """
    K-14 (H-1): İşlem bazlı Kelly — işlemin KENDİ olasılığıyla boyut ölçeği.
    Kalibrasyon kanıtı (2026-07-03): proba dilimleri monoton; %85'lik sinyal
    ile %55'lik sinyal aynı parayla oynanmamalı. Bant 0.4-1.0: zayıf-geçer
    sinyal ~yarım boy, güçlü sinyal tam boy. Riski sadece AŞAĞI çeker.
    """
    kelly = max(0.0, (proba * rr - (1.0 - proba)) / rr) if rr > 0 else 0.0
    return float(min(1.0, max(0.4, kelly * 2.5)))


def _calc_position_margin(
    balance: float,
    peak_balance: float,
    demo_trades: List[Dict],
    sl_pct: float,
    tp_pct: float,
    proba: float = 0.60,
) -> tuple:
    """
    Birleşik pozisyon boyutlandırma — backtest ile AYNI hedef:
    SL vurursa kasanın en fazla RISK_PER_TRADE'i (%0.5) gider.
    Drawdown, Kelly ve proba katmanları riski sadece AŞAĞI çeker, asla yukarı değil.
    Döndürür: (margin_usdt, effective_leverage)
    """
    # Katman 1: Drawdown Scale — DD %10'a gelince pozisyon %70 küçülür
    dd       = (peak_balance - balance) / peak_balance if peak_balance > 0 else 0.0
    dd_scale = max(0.30, 1.0 - dd * 7.0)

    # Katman 2: Quarter-Kelly (son 20 işlem performansı)
    recent = demo_trades[-20:]
    if len(recent) >= 10:
        wins    = sum(1 for t in recent if t["result"] == "TP")
        wr      = wins / len(recent)
        rr      = (tp_pct / sl_pct) if sl_pct > 0 else 1.0
        kelly   = max(0.0, (wr * rr - (1 - wr)) / rr)
        k_scale = max(0.30, min(1.0, kelly * 3.0))   # quarter-Kelly, 0.30–1.0
    else:
        k_scale = 0.50   # yeterli veri yokken muhafazakâr (efektif risk %0.25)

    # Drawdown'a göre kaldıraç kademesi (taban 5x)
    if dd < 0.05:
        eff_leverage = 5
    elif dd < 0.08:
        eff_leverage = 4
    else:
        eff_leverage = 3

    # Hedef risk: notional × sl_pct = balance × risk_pct olacak şekilde marjin
    p_scale  = _proba_scale(proba, (tp_pct / sl_pct) if sl_pct > 0 else 1.0)
    risk_pct = RISK_PER_TRADE * dd_scale * k_scale * p_scale   # maks %0.5
    margin   = (balance * risk_pct) / sl_pct / eff_leverage if sl_pct > 0 else balance * 0.05
    margin   = max(5.0, min(balance * 0.25, margin))      # min $5, marjin ≤ kasa %25

    return margin, eff_leverage


async def _run_async(testnet: bool) -> None:
    global _stop_flag
    _stop_flag = False
    # K-30: önceki oturumdan kalan bayat kalp atışı yeni başlatmada yanlış
    # alarm vermesin — sayaç "şimdi"den başlar
    _heartbeat["loop_ts"] = time.time()
    _heartbeat["note"] = "başlatılıyor"

    model_payload = _load_model()
    sl_pct: float = model_payload.get("sl_pct", 0.005)
    tp_pct: float = model_payload.get("tp_pct", 0.015)
    bidir  = model_payload.get("direction", "LONG") == "BIDIR"
    broadcast({"phase": "server",
               "msg": f"Model yüklendi | {'LONG+SHORT' if bidir else model_payload.get('direction','LONG')} | SL={sl_pct*100:.1f}% TP={tp_pct*100:.1f}%"})

    paper_mode = testnet  # True → demo kasa, emir yok
    exchange   = _build_exchange()
    db         = Database()
    await db.connect()

    # FAZ 3 (K-19): tek veto noktası + FAZ 4 (K-20): eski karar kayıtlarını buda
    gate = RiskGate()
    try:
        await db.prune_decisions(DECISIONS_KEEP_DAYS)
    except Exception:
        pass

    if not paper_mode:
        for sym in SYMBOLS:
            _set_leverage(exchange, sym)

    # ── Demo kasa ────────────────────────────────────────────────────────────
    demo_balance   = DEMO_START_BALANCE
    peak_balance   = DEMO_START_BALANCE   # dinamik position sizing için en yüksek bakiye
    demo_positions: Dict[str, Dict] = {}   # sym → {entry, tp, sl, side, ts, proba}
    demo_trades:    List[Dict] = []
    analysis_window: Deque[Dict] = deque(maxlen=50)  # son 50 işlemin analizi
    _retrain_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    # count/ts: son retrain'deki işlem sayısı + zamanı; busy_since: aktif
    # retrain'in başlangıcı (K-30 bekçisi askıda kalan kilidi bununla ölçer)
    _retrain_state = {"count": 0, "ts": time.time(), "busy_since": 0.0}

    def _maybe_auto_retrain() -> None:
        """
        Otomatik yeniden eğitim tetiği (K-13 + K-29). İKİ yerden çağrılır:
        işlem kapanışında (işlem-sayısı tetiği için doğal an) ve ana sinyal
        döngüsünde her turda — YAŞ tetiği sadece kapanışta kontrol edilseydi,
        işlemsiz haftalarda hiç ateşlenemez ve tam da çözmesi gereken
        bayatlama sorununa kendisi yakalanırdı.

        Tetikler (ikisinde de RETRAIN_MIN_GAP_S guard'ı ŞART — C-v-C (K-22)
        challenger'ı reddederse model.bin mtime'ı DEĞİŞMEZ; guard olmasa bot
        her döngüde yeniden eğitime girip retrain fırtınası yaratırdı):
        - işlem: ≥RETRAIN_MIN_TRADES yeni kapanan işlem
        - yaş  : model.bin RETRAIN_MAX_AGE_DAYS'ten eski (bayatlama önlemi;
                 piyasa haftalarca yönsüz kalıp işlem üretmeyebiliyor)
        """
        if _model_updating:
            return
        total_closed = len(demo_trades)
        new_trades = total_closed - _retrain_state["count"]
        gap_ok = time.time() - _retrain_state["ts"] >= RETRAIN_MIN_GAP_S
        trade_trigger = new_trades >= RETRAIN_MIN_TRADES and gap_ok
        model_age_days = ((time.time() - MODEL_PATH.stat().st_mtime) / 86400
                          if MODEL_PATH.exists() else 0.0)
        age_trigger = model_age_days >= RETRAIN_MAX_AGE_DAYS and gap_ok
        if not (trade_trigger or age_trigger):
            return
        trigger_desc = (f"{new_trades} işlem" if trade_trigger
                        else f"model {model_age_days:.1f} günden eski")
        _retrain_state["count"] = total_closed
        _retrain_state["ts"] = time.time()
        _retrain_state["busy_since"] = time.time()
        broadcast({"phase": "server",
                   "msg": f"otomatik eğitim (tetik: {trigger_desc}) — model güncelleniyor..."})

        def _retrain():
            global _model_updating
            nonlocal model_payload, sl_pct, tp_pct
            _model_updating = True
            try:
                import train_engine
                train_engine.broadcast = broadcast
                # K-22 (FAZ 6): challenger şampiyonu ortak doğrulamada
                # yenemezse model.bin DEĞİŞMEZ
                outcome = train_engine.main(run_server=False, days=RETRAIN_DAYS) or {}
                if not outcome.get("deployed", True):
                    _c = outcome.get("champion_val_ev")
                    _n = outcome.get("challenger_val_ev")
                    broadcast({"phase": "server",
                               "msg": (f"🛡 Şampiyon savundu — model DEĞİŞMEDİ "
                                       f"(challenger val-EV {_n:+.2f} ≤ şampiyon {_c:+.2f})")})
                    tg.send_async(
                        f"🛡 <b>Şampiyon Savundu</b>\n"
                        f"Yeni model doğrulamada mevcut modeli yenemedi.\n"
                        f"Challenger EV: {_n:+.2f} | Şampiyon EV: {_c:+.2f}\n"
                        f"Canlı model DEĞİŞMEDİ."
                    )
                elif MODEL_PATH.exists():
                    model_payload = _load_model()
                    # yeni modelin SL/TP'sini de devral
                    sl_pct = model_payload.get("sl_pct", sl_pct)
                    tp_pct = model_payload.get("tp_pct", tp_pct)
                    broadcast({"phase": "server",
                               "msg": f"Model yeniden yüklendi | SL={sl_pct*100:.1f}% TP={tp_pct*100:.1f}%"})
            except Exception as ex:
                err_msg = f"Yeniden eğitim hatası: {ex}"
                broadcast({"phase": "error", "msg": err_msg})
                tg.send_async(f"❌ <b>Eğitim Hatası</b>\n{err_msg}")
            finally:
                _model_updating = False
                _retrain_state["busy_since"] = 0.0

        asyncio.get_event_loop().run_in_executor(_retrain_executor, _retrain)
    realized_pnl = 0.0     # gün içi gerçekleşen PnL (günlük fren kontrolü için)
    day_start_balance = DEMO_START_BALANCE   # gün başı bakiye — yüzde frenlerin paydası
    daily_paused = False   # kayıp freni / kâr kilidi devredeyse o gün yeni işlem yok
    day_trades_idx = 0     # günlük rapor için: gün başında demo_trades uzunluğu

    _last_prices: Dict[str, float] = {}

    def _broadcast_wallet():
        # Açık pozisyonlar için gerçek zamanlı unrealized PnL
        unrealized = 0.0
        for sym, pos in demo_positions.items():
            price = _last_prices.get(sym, pos["entry"])
            raw_ret = (price - pos["entry"]) / pos["entry"]
            is_long = pos["side"] == "LONG"
            unrealized += pos["notional"] * raw_ret * (1 if is_long else -1)

        total_pnl = (demo_balance - DEMO_START_BALANCE) + unrealized
        broadcast({
            "phase":        "wallet",
            "balance":      round(demo_balance, 4),
            "start":        DEMO_START_BALANCE,
            "pnl":          round(total_pnl, 4),
            "pnl_pct":      round(total_pnl / DEMO_START_BALANCE * 100, 2),
            "open_count":   len(demo_positions),
            "trade_count":  len(demo_trades),
            "unrealized":   round(unrealized, 4),
        })

    def _broadcast_positions():
        """Açık pozisyonları unrealized PnL ile birlikte yayınla."""
        positions = []
        for sym, pos in demo_positions.items():
            price   = _last_prices.get(sym, pos["entry"])
            raw_ret = (price - pos["entry"]) / pos["entry"]
            is_long = pos["side"] == "LONG"
            upnl    = pos["notional"] * raw_ret * (1 if is_long else -1)
            upnl_pct = (upnl / pos["margin"]) * 100  # teminat üzerinden %
            positions.append({
                "symbol":        sym,
                "side":          pos["side"],
                "entry":         round(pos["entry"], 4),
                "current_price": round(price, 4),
                "tp":            round(pos["tp"], 4),
                "sl":            round(pos["sl"], 4),
                "upnl":          round(upnl, 4),
                "upnl_pct":      round(upnl_pct, 2),
                "open_ts":       pos.get("ts", 0),
                "proba":         round(pos.get("proba", 0), 3),
                "db_id":         pos.get("db_id"),
                "margin":        pos["margin"],
                "notional":      pos["notional"],
                "leverage":      pos.get("leverage", LEVERAGE),
            })
        broadcast({"phase": "positions", "positions": positions})

    # Anlık mum verisi — WS'den güncellenir, SL/TP kontrolünde kullanılır
    _last_candles: Dict[str, Dict] = {}              # sym → {price, high, low}
    _candle_buffer: Dict[str, Deque] = {}            # sym → kapanmış mumlar (maxlen=200)
    # Funding rate + open interest rolling buffer (ts, funding_rate, open_interest)
    # → latest_features'a geçirilir; oi_change_1h için ~1h'lik geçmiş taşır.
    _metrics_buffer: Dict[str, Deque] = {s: deque(maxlen=METRICS_BUFFER_SIZE) for s in SYMBOLS}
    _last_error_ts: Dict[str, float] = {}            # Telegram hata spam önleme
    _feed_ts = {"t": 0.0}                            # son başarılı fiyat güncellemesi (sağlık için)
    _health_last = {"t": 0.0}                        # son sağlık yayını
    # K-30 bekçi durumu: son kontrol + uyarı zaman damgaları (Telegram spam önleme)
    _watchdog = {"check_ts": 0.0, "stall_alert_ts": 0.0, "stuck_alert_ts": 0.0}

    async def _ticker():
        """
        Binance Futures WebSocket kline_1m stream.
        Anlık fiyat + cari mum high/low → SL/TP kontrolü için REST yok.
        Bağlantı koparsa 3 saniyede otomatik yeniden bağlanır.
        """
        nonlocal demo_balance, realized_pnl, peak_balance
        global _model_updating   # K-30 bekçisi askıda kalan retrain kilidini açabilir
        from websockets.asyncio.client import connect as _ws_connect

        # kline_1m: her tick'te cari mum o/h/l/c gelir
        streams = "/".join(s.replace("/", "").lower() + "@kline_1m" for s in SYMBOLS)
        ws_url  = f"wss://fstream.binance.com/stream?streams={streams}"

        # Sembol eşleme: BTCUSDT → BTC/USDT
        _raw_to_sym = {s.replace("/", ""): s for s in SYMBOLS}

        async def _price_loop():
            # Bu ağda WS bağlanıp veri GÖNDERMEZ (ISS filtresi) → her ~10 dk
            # ping-timeout/yeniden-bağlanma döngüsü logu çöple dolduruyordu.
            # Kural: "kuruldu" mesajı ancak GERÇEKTEN veri akarsa basılır;
            # hatalar 1. ve her 20.'de bir loglanır; bekleme üstel (3sn→5dk).
            backoff = 3
            fail_count = 0
            data_flowing = False
            while not _stop_flag:
                try:
                    async with _ws_connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                        async for raw in ws:
                            if _stop_flag:
                                return
                            try:
                                k = json.loads(raw).get("data", {}).get("k", {})
                                if not k:
                                    continue
                                if not data_flowing:
                                    data_flowing = True
                                    backoff, fail_count = 3, 0
                                    broadcast({"phase": "server",
                                               "msg": "Fiyat WebSocket AKTİF — gerçek zamanlı tick akıyor"})
                                raw_sym = k["s"]   # BTCUSDT
                                sym = _raw_to_sym.get(raw_sym)
                                if sym:
                                    _feed_ts["t"] = time.time()
                                    _last_prices[sym]   = float(k["c"])
                                    _last_candles[sym]  = {
                                        "price": float(k["c"]),
                                        "high":  float(k["h"]),
                                        "low":   float(k["l"]),
                                    }
                                    if k.get("x"):  # mum kapandı — buffer'a ekle
                                        buf = _candle_buffer.setdefault(
                                            sym, deque(maxlen=CANDLE_BUFFER_SIZE))
                                        last_ts = buf[-1]["timestamp"] if buf else 0
                                        if int(k["t"]) > last_ts:  # REST fallback ile çakışma önle
                                            buf.append({
                                                "timestamp": int(k["t"]),
                                                "open":   float(k["o"]),
                                                "high":   float(k["h"]),
                                                "low":    float(k["l"]),
                                                "close":  float(k["c"]),
                                                "volume": float(k["v"]),
                                            })
                            except Exception:
                                pass
                except Exception as e:
                    if not _stop_flag:
                        fail_count += 1
                        data_flowing = False
                        if fail_count == 1 or fail_count % 20 == 0:
                            broadcast({"phase": "server",
                                       "msg": (f"WS veri akmıyor ({fail_count}. deneme: {e}) — "
                                               f"REST beslemesi asıl kaynak, {backoff} sn sonra tekrar")})
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 300)   # üstel geri çekilme, tavan 5 dk

        async def _rest_price_loop():
            """
            REST fiyat güvenlik ağı — 2 sn'de bir son mumları çeker.
            Bazı ağlarda Binance WS bağlanıyor ama market datası HİÇ akmıyor
            (ISS/bölge filtresi); bot bu durumda fiyatsız kalıp sonsuza dek
            sinyal atlıyordu. WS tick gelirse bu döngü sadece yedek görevi görür.
            """
            announced = False
            while not _stop_flag:
                for sym in SYMBOLS:
                    try:
                        rows = await asyncio.to_thread(_fetch_recent_klines, sym, 3)
                        if not rows:
                            continue
                        open_k = rows[-1]   # son satır = henüz kapanmamış cari mum
                        _feed_ts["t"] = time.time()
                        _last_prices[sym]  = float(open_k[4])
                        _last_candles[sym] = {
                            "price": float(open_k[4]),
                            "high":  float(open_k[2]),
                            "low":   float(open_k[3]),
                        }
                        buf = _candle_buffer.setdefault(sym, deque(maxlen=CANDLE_BUFFER_SIZE))
                        last_ts = buf[-1]["timestamp"] if buf else 0
                        for r in rows[:-1]:   # kapanmış mumlar
                            if int(r[0]) > last_ts:
                                buf.append({
                                    "timestamp": int(r[0]),
                                    "open":   float(r[1]),
                                    "high":   float(r[2]),
                                    "low":    float(r[3]),
                                    "close":  float(r[4]),
                                    "volume": float(r[5]),
                                })
                        if not announced:
                            announced = True
                            broadcast({"phase": "server",
                                       "msg": "REST fiyat beslemesi aktif (2 sn) — WS yedekli çalışıyor"})
                    except Exception:
                        pass   # geçici ağ hatası — sonraki turda tekrar dene
                await asyncio.sleep(2)   # K-13 (B-3): SL/TP tespiti için gecikme payı azaltıldı

        async def _metrics_loop():
            """
            Funding rate + open interest çekici (her METRICS_POLL_S).
            ccxt üzerinden public veri; hata durumunda SESSİZ geçer (döngüyü
            öldürmez). Buffer latest_features'a beslenir → funding_rate +
            oi_change_1h özellikleri canlıda eğitimdeki as-of semantiğiyle üretilir.
            """
            announced = False
            while not _stop_flag:
                for sym in SYMBOLS:
                    funding = None
                    open_interest = None
                    try:
                        fr = await asyncio.to_thread(exchange.fetch_funding_rate, sym)
                        if fr.get("fundingRate") is not None:
                            funding = float(fr["fundingRate"])
                    except Exception:
                        pass
                    try:
                        oi = await asyncio.to_thread(exchange.fetch_open_interest, sym)
                        oi_val = oi.get("openInterestAmount")
                        if oi_val is None:
                            oi_val = oi.get("openInterestValue")
                        if oi_val is not None:
                            open_interest = float(oi_val)
                    except Exception:
                        pass
                    if funding is not None or open_interest is not None:
                        _metrics_buffer.setdefault(sym, deque(maxlen=METRICS_BUFFER_SIZE)).append({
                            "ts": int(time.time() * 1000),
                            "funding_rate": funding,
                            "open_interest": open_interest,
                        })
                        if not announced:
                            announced = True
                            broadcast({"phase": "server",
                                       "msg": f"Piyasa metrikleri aktif (funding+OI, {METRICS_POLL_S} sn)"})
                await asyncio.sleep(METRICS_POLL_S)

        price_task   = asyncio.create_task(_price_loop())
        rest_task    = asyncio.create_task(_rest_price_loop())
        metrics_task = asyncio.create_task(_metrics_loop())

        try:
            # ── 1 saniyelik döngü: manuel kapat + wallet/position broadcast ──
            while not _stop_flag:
                # ── Panik (K-19): önce tüm pozisyonları kapat, sonra dur ─────
                global _panic_close_requested
                if _panic_close_requested:
                    if demo_positions:
                        for _ps in list(demo_positions.keys()):
                            _manual_close_requests.add(_ps)
                    elif not _manual_close_requests:
                        _panic_close_requested = False
                        broadcast({"phase": "server",
                                   "msg": "🚨 Panik: tüm pozisyonlar kapatıldı — bot durduruluyor"})
                        stop()

                # ── MFE/MAE takibi (K-21 / FAZ 5): saniyelik uç hareket kaydı ─
                # Fiyat beslemesi zaten akıyor — maliyetsiz hafıza. Not: giriş
                # dakikasının mumu girişten önceki tikleri de içerir; ilk dakika
                # için küçük bir üst tahmin payı vardır (bilinçli kabul).
                for _ms, _mp in demo_positions.items():
                    _mc = _last_candles.get(_ms)
                    if not _mc:
                        continue
                    if _mp["side"] == "LONG":
                        _fav = (_mc["high"] - _mp["entry"]) / _mp["entry"]
                        _adv = (_mp["entry"] - _mc["low"]) / _mp["entry"]
                    else:
                        _fav = (_mp["entry"] - _mc["low"]) / _mp["entry"]
                        _adv = (_mc["high"] - _mp["entry"]) / _mp["entry"]
                    _mp["mfe"] = max(_mp.get("mfe", 0.0), _fav)
                    _mp["mae"] = max(_mp.get("mae", 0.0), _adv)

                for sym in list(_manual_close_requests):
                    _manual_close_requests.discard(sym)
                    if sym not in demo_positions:
                        continue
                    pos        = demo_positions.pop(sym)
                    exit_price = _last_prices.get(sym, pos["entry"])
                    is_long    = pos["side"] == "LONG"
                    raw_ret    = (exit_price - pos["entry"]) / pos["entry"]
                    pnl_raw    = pos["notional"] * raw_ret * (1 if is_long else -1)
                    fee        = pos["notional"] * (FEE_RATE + SLIPPAGE_RATE)
                    pnl_net    = pnl_raw - fee   # kasa akışı (giriş ücreti açılışta düşüldü)
                    pnl_rep    = pnl_net - pos.get("entry_fee", 0.0)   # rapor: giriş dahil
                    pnl_pct    = (pnl_rep / pos["margin"]) * 100
                    demo_balance += pnl_net
                    peak_balance  = max(peak_balance, demo_balance)
                    realized_pnl += pnl_net
                    _mfe, _mae = pos.get("mfe", 0.0), pos.get("mae", 0.0)
                    _evc, _evt = _self_evaluate("MANUAL", _mfe, _mae, sl_pct, tp_pct)
                    demo_trades.append({"result": "MANUAL", "pnl": pnl_rep, "sym": sym,
                                        "mfe_r": _mfe / tp_pct if tp_pct > 0 else 0.0,
                                        "mae_r": _mae / sl_pct if sl_pct > 0 else 0.0,
                                        "eval": _evc})
                    if pos.get("db_id"):
                        await db.close_trade(pos["db_id"], round(exit_price, 4),
                                             int(time.time() * 1000), "MANUAL", round(pnl_rep, 4),
                                             mfe_pct=round(_mfe * 100, 4),
                                             mae_pct=round(_mae * 100, 4),
                                             self_eval=_evc)
                    broadcast({
                        "phase": "trade_close", "symbol": sym, "result": "MANUAL",
                        "entry": round(pos["entry"], 4), "exit": round(exit_price, 4),
                        "pnl": round(pnl_rep, 4), "pnl_pct": round(pnl_pct, 2), "paper": True,
                    })
                    broadcast({"phase": "server", "msg": f"{sym} manuel kapatıldı @ {exit_price:.2f}"})
                    pnl_sign = "+" if pnl_rep >= 0 else ""
                    tg.send_async(
                        f"🖐 <b>Manuel Kapatma | {sym}</b>\n"
                        f"Çıkış: {exit_price:.2f}\n"
                        f"PnL: <b>{pnl_sign}{pnl_rep:.3f} USDT ({pnl_sign}{pnl_pct:.2f}%)</b>\n"
                        f"Kasa: <b>{demo_balance:.2f} USDT</b>"
                    )

                _broadcast_wallet()
                _broadcast_positions()

                # ── Sağlık skoru yayını (15 sn'de bir — K-18 / FAZ 2) ────────
                if time.time() - _health_last["t"] >= 15:
                    _health_last["t"] = time.time()
                    try:
                        _cost = FEE_RATE * 2 + SLIPPAGE_RATE
                        _be = (sl_pct + _cost) / ((tp_pct - _cost) + (sl_pct + _cost))
                        _h = compute_health(
                            balance=demo_balance,
                            peak_balance=peak_balance,
                            day_start_balance=day_start_balance,
                            realized_pnl_today=realized_pnl,
                            trades=demo_trades,
                            breakeven_wr=_be,
                            last_feed_ts=_feed_ts["t"],
                            daily_paused=daily_paused,
                            open_positions=len(demo_positions),
                        )
                        # K-19: sağlık skoru RiskGate'i besler (histerezisli duraklatma)
                        _hchange = gate.update_health(_h["score"])
                        broadcast({"phase": "health", **_h,
                                   "health_paused": gate.health_paused,
                                   "panic": panic_active()})
                        if _hchange == "paused":
                            broadcast({"phase": "server",
                                       "msg": f"⚠️ Sağlık skoru {_h['score']} — yeni işlem DURAKLATILDI (eşik altı)"})
                            tg.send_async(
                                f"⚠️ <b>Sağlık Duraklatması</b>\n"
                                f"Skor: {_h['score']}/100 ({_h['status']})\n"
                                f"Skor toparlanana kadar yeni işlem açılmayacak."
                            )
                        elif _hchange == "resumed":
                            broadcast({"phase": "server",
                                       "msg": f"✅ Sağlık skoru {_h['score']} — işlem açma yeniden aktif"})
                            tg.send_async(
                                f"✅ <b>Sağlık Toparlandı</b>\n"
                                f"Skor: {_h['score']}/100 — işlemler devam ediyor."
                            )
                    except Exception:
                        pass

                # ── K-30 Bekçi: ana sinyal döngüsü ölürse/askıda kalırsa haber ver.
                # Bu housekeeping döngüsü 19-21 Temmuz olayında bile ayakta kaldı
                # (health yayını hiç kesilmedi) — bekçi bu yüzden BURADA yaşar,
                # izlediği döngünün içinde değil.
                if time.time() - _watchdog["check_ts"] >= 60:
                    _watchdog["check_ts"] = time.time()
                    _age = heartbeat_age()
                    if (_age is not None and _age > WATCHDOG_STALL_S
                            and time.time() - _watchdog["stall_alert_ts"] >= WATCHDOG_ALERT_GAP_S):
                        _watchdog["stall_alert_ts"] = time.time()
                        _stall_msg = (f"Sinyal döngüsü {_age/60:.0f} dakikadır atmıyor "
                                      f"(son aşama: {_heartbeat['note']})")
                        broadcast({"phase": "error", "msg": f"🐕 Bekçi: {_stall_msg}"})
                        tg.send_async(f"🐕 <b>Bekçi Uyarısı</b>\n{_stall_msg}\n"
                                      f"Bot işlem TARAMIYOR — kontrol gerekli.")
                        try:
                            # zaman aşımı ŞART: ana döngü DB üzerinde asılıysa
                            # bekçinin DB yazımı da aynı kuyrukta asılı kalır
                            # ve bekçiyi de öldürür
                            await asyncio.wait_for(
                                _emit_decision("*", blocked_by="LOOP_STALL",
                                               detail={"age_s": round(_age),
                                                       "note": _heartbeat["note"]}),
                                timeout=5)
                        except Exception:
                            pass
                    # Askıda kalan retrain kilidi: uyar, çok uzarsa zorla aç
                    # (eğitim normalde dakikalar sürer; saatler = askıda thread)
                    if _model_updating and _retrain_state.get("busy_since"):
                        _busy = time.time() - _retrain_state["busy_since"]
                        if _busy > RETRAIN_STUCK_FORCE_S:
                            _retrain_state["busy_since"] = 0.0
                            _model_updating = False
                            broadcast({"phase": "error",
                                       "msg": f"🐕 Bekçi: retrain kilidi {_busy/3600:.1f} saattir açık — ZORLA açıldı, eski modelle devam"})
                            tg.send_async(f"🐕 <b>Bekçi: Retrain Kilidi Zorla Açıldı</b>\n"
                                          f"Eğitim {_busy/3600:.1f} saattir bitmedi (askıda). "
                                          f"Bot mevcut modelle işleme devam ediyor.")
                        elif (_busy > RETRAIN_STUCK_ALERT_S
                                and time.time() - _watchdog["stuck_alert_ts"] >= WATCHDOG_ALERT_GAP_S):
                            _watchdog["stuck_alert_ts"] = time.time()
                            tg.send_async(f"🐕 <b>Bekçi Uyarısı</b>\n"
                                          f"Retrain kilidi {_busy/3600:.1f} saattir açık — "
                                          f"eğitim askıda kalmış olabilir.")

                await asyncio.sleep(1)
        finally:
            price_task.cancel()
            rest_task.cancel()
            metrics_task.cancel()

    mode_label = f"PAPER (demo kasa: {DEMO_START_BALANCE} USDT)" if paper_mode else "CANLI"
    dir_label  = "LONG+SHORT" if bidir else model_payload.get("direction", "LONG")
    bot_start_ts = int(time.time())
    broadcast({"phase": "bot_start", "ts": bot_start_ts})
    broadcast({"phase": "server",
               "msg": f"Trader başladı | {mode_label} | Yön={dir_label} | {SYMBOLS}"})
    tg.send_async(
        f"🤖 <b>Bot Başladı</b>\n"
        f"Mod: {mode_label}\n"
        f"Yön: {dir_label} | Kaldıraç: {LEVERAGE}x\n"
        f"Demo Kasa: <b>{DEMO_START_BALANCE:.2f} USDT</b>"
    )
    _broadcast_wallet()

    # ── Yeniden başlatmada önceki açık paper trade'leri temizle ──────────────
    try:
        await db.conn.execute(
            "UPDATE trades SET status='cancelled', exit_reason='BOT_RESTART', exit_ts=? WHERE status='open'",
            (int(time.time() * 1000),),
        )
        await db.conn.commit()
    except Exception:
        pass

    # ── Başlangıç mum buffer'ı — REST, sadece bir kez ────────────────────────
    for sym in SYMBOLS:
        _candle_buffer[sym] = deque(maxlen=CANDLE_BUFFER_SIZE)
    for sym in SYMBOLS:
        for attempt in range(3):
            try:
                df_init = _fetch_ohlcv(exchange, sym, limit=CANDLE_BUFFER_SIZE)
                for _, row in df_init.iterrows():
                    _candle_buffer[sym].append(row.to_dict())
                broadcast({"phase": "server",
                           "msg": f"{sym} başlangıç verisi yüklendi ({len(_candle_buffer[sym])} mum)"})
                break
            except Exception as e_init:
                if attempt < 2:
                    broadcast({"phase": "server",
                               "msg": f"{sym} veri yüklenemedi (deneme {attempt+1}/3): {e_init}"})
                    await asyncio.sleep(5)
                else:
                    broadcast({"phase": "server",
                               "msg": f"{sym} başlangıç verisi alınamadı — WS buffer dolana kadar sinyal bekle"})

    # ── 1d buffer — sadece başlangıçta yükle ─────────────────────────────────
    _d1_buffer: Dict[str, Optional[pd.DataFrame]] = {}
    for sym in SYMBOLS:
        for attempt in range(3):
            try:
                _d1_buffer[sym] = _fetch_ohlcv_1d(sym, limit=60)
                broadcast({"phase": "server",
                           "msg": f"{sym} günlük veri yüklendi ({len(_d1_buffer[sym])} bar)"})
                break
            except Exception as e_d1:
                if attempt < 2:
                    await asyncio.sleep(5)
                else:
                    _d1_buffer[sym] = None
                    broadcast({"phase": "server",
                               "msg": f"{sym} günlük veri alınamadı — 1d özellikler devre dışı"})

    # K-30: sessiz bloklar (NO_PRICE/NO_FEATURES/BUFFER_SHORT/GLOBAL_BLOCK)
    # eskiden DB'ye HİÇ yazılmıyordu → döngü günlerce boş dönse geriye tek iz
    # kalmıyor, kök neden analizi imkânsızlaşıyordu (19-21 Temmuz olayı).
    # Sembol+neden başına en fazla SILENT_PERSIST_GAP_S'de bir kalıcı kayıt.
    _silent_last: Dict[str, float] = {}

    def _persist_throttled(sym: str, reason: str) -> bool:
        key = f"{sym}:{reason}"
        now = time.time()
        if now - _silent_last.get(key, 0.0) >= SILENT_PERSIST_GAP_S:
            _silent_last[key] = now
            return True
        return False

    async def _emit_decision(sym: str, *, blocked_by: Optional[str] = None,
                             direction: Optional[str] = None,
                             proba: Optional[float] = None,
                             threshold: Optional[float] = None,
                             opened: bool = False,
                             detail: Optional[Dict[str, Any]] = None,
                             persist: bool = True) -> None:
        """FAZ 4 (K-20): karar eventi — dashboard paneli + decisions tablosu.
        NO_SIGNAL kalabalığı DB'ye yazılmaz (panel canlı event'ten görür);
        gerçek bloklar ve açılışlar kalıcıdır."""
        broadcast({"phase": "decision", "symbol": sym, "blocked_by": blocked_by,
                   "direction": direction, "proba": proba, "threshold": threshold,
                   "opened": opened, "detail": detail or {}})
        if persist and blocked_by != "NO_SIGNAL":
            try:
                await db.insert_decision({
                    "ts": int(time.time() * 1000), "symbol": sym,
                    "direction": direction, "proba": proba,
                    "threshold": threshold, "blocked_by": blocked_by,
                    "opened": opened,
                    "detail": json.dumps(detail or {}, ensure_ascii=False),
                })
            except Exception:
                pass

    ticker_task = asyncio.create_task(_ticker())
    loss_day = time.strftime("%Y-%m-%d", time.gmtime())   # günlük kayıp limiti UTC gün bazlı
    try:
        while not _stop_flag:
            # K-30: kalp atışı — bekçi (housekeeping döngüsü) bunun yaşına bakar
            _heartbeat["loop_ts"] = time.time()
            _heartbeat["note"] = "döngü başı"

            # ── Günlük frenler: yeni UTC gününde sıfırla + günlük rapor ──────
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if today != loss_day:
                # K-16 (H-4): dünün özet raporu — Telegram'a her gün otomatik
                day_trades = demo_trades[day_trades_idx:]
                if day_trades:
                    wins   = sum(1 for t in day_trades if t["result"] == "TP")
                    day_wr = wins / len(day_trades)
                    ret    = realized_pnl / day_start_balance * 100 if day_start_balance > 0 else 0.0
                    emoji  = "📈" if realized_pnl >= 0 else "📉"
                    # K-21: MFE/MAE günlük içgörü — SL'ler TP'ye ne kadar yaklaştı?
                    _sl_mfe = [t["mfe_r"] for t in day_trades
                               if t["result"] == "SL" and t.get("mfe_r") is not None]
                    _stop_dar = sum(1 for t in day_trades if t.get("eval") == "STOP_DAR")
                    _sansli   = sum(1 for t in day_trades if t.get("eval") == "SANSLI_TP")
                    mfe_line = ""
                    if _sl_mfe:
                        mfe_line = (f"\n🧠 SL'lerde ort. TP-yaklaşımı: %{sum(_sl_mfe)/len(_sl_mfe)*100:.0f}"
                                    f" | stop-dar: {_stop_dar} | şanslı TP: {_sansli}")
                    tg.send_async(
                        f"{emoji} <b>Günlük Rapor | {loss_day}</b>\n"
                        f"İşlem: {len(day_trades)} ({wins} TP / {len(day_trades)-wins} diğer)\n"
                        f"Gün WR: {day_wr:.0%}\n"
                        f"Gün PnL: <b>{realized_pnl:+.2f} USDT ({ret:+.2f}%)</b>\n"
                        f"Kasa: <b>{demo_balance:.2f} USDT</b>"
                        + mfe_line
                        + ("\n⏸ Gün frenle kapandı" if daily_paused else "")
                    )
                else:
                    tg.send_async(
                        f"😴 <b>Günlük Rapor | {loss_day}</b>\n"
                        f"Bugün hiç işlem açılmadı.\n"
                        f"Kasa: <b>{demo_balance:.2f} USDT</b>"
                    )
                loss_day = today
                if realized_pnl != 0.0 or daily_paused:
                    broadcast({"phase": "server",
                               "msg": f"Yeni gün — günlük PnL sayacı sıfırlandı (önceki: {realized_pnl:+.2f} USDT)"})
                realized_pnl = 0.0
                day_start_balance = demo_balance
                daily_paused = False
                day_trades_idx = len(demo_trades)

            # ── Paper: Açık pozisyon SL/TP kontrolü ─────────────────────────
            if paper_mode:
                balance_delta = 0.0
                for sym in list(demo_positions.keys()):
                    try:
                        candle = _last_candles.get(sym)
                        if not candle:
                            continue   # WS henüz veri almadı, atla
                        pos  = demo_positions[sym]
                        h, l = candle["high"], candle["low"]
                        is_long = pos["side"] == "LONG"
                        tp_hit  = h >= pos["tp"] if is_long else l <= pos["tp"]
                        sl_hit  = l <= pos["sl"] if is_long else h >= pos["sl"]

                        if tp_hit or sl_hit:
                            result = "TP" if (tp_hit and not sl_hit) else "SL"
                            exit_price = pos["tp"] if result == "TP" else pos["sl"]
                            raw_ret = (exit_price - pos["entry"]) / pos["entry"]
                            pnl_raw = pos["notional"] * raw_ret * (1 if is_long else -1)
                            # backtest ile aynı maliyet modeli: çıkış komisyonu + slippage
                            fee     = pos["notional"] * (FEE_RATE + SLIPPAGE_RATE)
                            pnl_net = pnl_raw - fee   # kasa akışı (giriş ücreti açılışta düşüldü)
                            # Rapor PnL'i giriş ücretini de içerir — kasayla tutarlı
                            pnl_rep = pnl_net - pos.get("entry_fee", 0.0)
                            pnl_pct = (pnl_rep / pos["margin"]) * 100
                            balance_delta += pnl_net
                            realized_pnl  += pnl_net
                            # ── MFE/MAE öz-değerlendirmesi (K-21 / FAZ 5) ────
                            mfe, mae = pos.get("mfe", 0.0), pos.get("mae", 0.0)
                            ev_code, ev_text = _self_evaluate(result, mfe, mae, sl_pct, tp_pct)
                            # DB'de trade'i kapat
                            if pos.get("db_id"):
                                await db.close_trade(
                                    pos["db_id"],
                                    round(exit_price, 4),
                                    int(time.time() * 1000),
                                    result,
                                    round(pnl_rep, 4),
                                    mfe_pct=round(mfe * 100, 4),
                                    mae_pct=round(mae * 100, 4),
                                    self_eval=ev_code,
                                )
                            demo_positions.pop(sym, None)
                            demo_trades.append({"result": result, "pnl": pnl_rep, "sym": sym,
                                                "mfe_r": mfe / tp_pct if tp_pct > 0 else 0.0,
                                                "mae_r": mae / sl_pct if sl_pct > 0 else 0.0,
                                                "eval": ev_code})

                            # ── Öz-analiz ────────────────────────────────────
                            rec = {
                                "sym":    sym,
                                "result": result,
                                "pnl":    round(pnl_rep, 4),
                                "proba":  pos.get("proba", 0),
                                "correct": result == "TP",
                            }
                            analysis_window.append(rec)
                            recent = list(analysis_window)
                            n = len(recent)
                            rolling_wr = sum(1 for r in recent if r["correct"]) / n if n else 0
                            avg_proba  = sum(r["proba"] for r in recent) / n if n else 0
                            broadcast({
                                "phase":      "trade_analysis",
                                "symbol":     sym,
                                "result":     result,
                                "pnl":        round(pnl_rep, 4),
                                "pnl_pct":    round(pnl_pct, 2),
                                "proba":      pos.get("proba", 0),
                                "correct":    result == "TP",
                                "rolling_wr": round(rolling_wr, 3),
                                "rolling_n":  n,
                                "avg_proba":  round(avg_proba, 3),
                                "mfe_pct":    round(mfe * 100, 3),
                                "mae_pct":    round(mae * 100, 3),
                                "self_eval":  ev_code,
                                "self_eval_text": ev_text,
                            })

                            # ── Otomatik yeniden eğitim (K-13 + K-29) — ortak
                            # tetik mantığı _maybe_auto_retrain'de
                            _maybe_auto_retrain()

                            broadcast({
                                "phase": "trade_close",
                                "symbol": sym, "result": result,
                                "entry": round(pos["entry"], 4),
                                "exit":  round(exit_price, 4),
                                "pnl":   round(pnl_rep, 4),
                                "pnl_pct": round(pnl_pct, 2),
                                "paper": True,
                                "mfe_pct": round(mfe * 100, 3),
                                "mae_pct": round(mae * 100, 3),
                                "self_eval": ev_code,
                            })
                            close_emoji = "✅" if result == "TP" else "❌"
                            pnl_sign    = "+" if pnl_rep >= 0 else ""
                            tg.send_async(
                                f"{close_emoji} <b>{result} | {sym}</b>\n"
                                f"Giriş: {pos['entry']:.2f}  →  Çıkış: {exit_price:.2f}\n"
                                f"PnL: <b>{pnl_sign}{pnl_rep:.3f} USDT ({pnl_sign}{pnl_pct:.2f}%)</b>\n"
                                f"MFE: %{mfe*100:.2f} · MAE: %{mae*100:.2f}\n"
                                f"🧠 {ev_text}\n"
                                f"Kasa: <b>{demo_balance + balance_delta:.2f} USDT</b>"
                            )
                    except Exception as e:
                        broadcast({"phase": "error", "msg": f"{sym} SL/TP kontrol hatası: {e}"})
                        tg.send_async(f"⚠️ <b>SL/TP Hatası | {sym}</b>\n{e}")

                if balance_delta != 0.0:
                    demo_balance += balance_delta
                    peak_balance  = max(peak_balance, demo_balance)
                    _broadcast_wallet()

                # ── Günlük frenler: kayıp freni + kâr kilidi ──────────────
                # Bot durmaz; sadece O GÜN yeni pozisyon açmaz. Açık
                # pozisyonların SL/TP takibi devam eder; ertesi gün sıfırlanır.
                if not daily_paused and day_start_balance > 0:
                    day_ret = realized_pnl / day_start_balance
                    if day_ret <= DAILY_LOSS_LIMIT_PCT:
                        daily_paused = True
                        broadcast({"phase": "server",
                                   "msg": f"Günlük kayıp freni: {day_ret*100:+.2f}% — bugün yeni işlem yok"})
                        tg.send_async(
                            f"🛑 <b>Günlük Kayıp Freni</b>\n"
                            f"Gün içi: {day_ret*100:+.2f}% ({realized_pnl:+.2f} USDT)\n"
                            f"Bugün yeni işlem açılmayacak; yarın devam.\n"
                            f"Kasa: <b>{demo_balance:.2f} USDT</b>"
                        )
                    elif day_ret >= DAILY_PROFIT_LOCK_PCT:
                        daily_paused = True
                        broadcast({"phase": "server",
                                   "msg": f"Günlük kâr kilidi: {day_ret*100:+.2f}% — hedefe ulaşıldı, bugün yeni işlem yok"})
                        tg.send_async(
                            f"🔒 <b>Günlük Kâr Kilidi!</b>\n"
                            f"Gün içi: <b>{day_ret*100:+.2f}%</b> ({realized_pnl:+.2f} USDT)\n"
                            f"Hedefe ulaşıldı — kâr korunuyor, yarın devam.\n"
                            f"Kasa: <b>{demo_balance:.2f} USDT</b>"
                        )

            if _stop_flag:
                break

            open_syms = list(demo_positions.keys()) if paper_mode else []

            # K-29: yaş tetiği işlemsiz dönemlerde de kontrol edilsin — sadece
            # işlem kapanışında kontrol edilseydi, piyasa işlem üretmezken
            # (tam da yaş tetiğinin var olma nedeni) hiç ateşlenemezdi
            _maybe_auto_retrain()

            # ── Döngü seviyesi bloklar (K-19): panik / retrain / günlük fren /
            #    sağlık duraklatması — tek noktadan
            if gate.global_block(_model_updating, daily_paused):
                # K-30: bloklu turlar da iz bıraksın — hangi kilit, ne zamandır
                _heartbeat["note"] = "global_block"
                if _persist_throttled("*", "GLOBAL_BLOCK"):
                    await _emit_decision("*", blocked_by="GLOBAL_BLOCK", detail={
                        "retrain": _model_updating,
                        "daily_paused": daily_paused,
                        "health_paused": gate.health_paused,
                        "panic": panic_active(),
                    })
                await asyncio.sleep(LOOP_INTERVAL)
                continue

            _heartbeat["note"] = "sinyal taraması"

            # ── Sinyal üret ──────────────────────────────────────────────────
            for sym in SYMBOLS:
                if _stop_flag:
                    break
                if sym in open_syms:
                    continue

                try:
                    buf = list(_candle_buffer.get(sym, deque()))
                    if len(buf) < 30:
                        broadcast({"phase": "server",
                                   "msg": f"{sym} buffer dolmadı ({len(buf)}/30), bekleniyor"})
                        await _emit_decision(sym, blocked_by="BUFFER_SHORT",
                                             persist=_persist_throttled(sym, "BUFFER_SHORT"))
                        continue
                    df = pd.DataFrame(buf)
                    mbuf = list(_metrics_buffer.get(sym, deque()))
                    metrics_df = pd.DataFrame(mbuf) if mbuf else None
                    features = _compute_features(df, _d1_buffer.get(sym), metrics_df)
                    entry_price = _last_prices.get(sym)
                    if entry_price is None:
                        broadcast({"phase": "server",
                                   "msg": f"{sym} anlık fiyat henüz yok (WS tick bekleniyor) — atlandı"})
                        await _emit_decision(sym, blocked_by="NO_PRICE",
                                             persist=_persist_throttled(sym, "NO_PRICE"))
                        continue

                    if features is None:
                        broadcast({"phase": "server",
                                   "msg": f"{sym} özellikler hesaplanamadı (NaN/eksik veri) — atlandı"})
                        await _emit_decision(sym, blocked_by="NO_FEATURES",
                                             persist=_persist_throttled(sym, "NO_FEATURES"))
                        continue

                    # ── Volatility-Adjusted Threshold ────────────────────────
                    # senkron HTTP'yi thread'e al — event loop'u bloklamasın
                    fng      = await asyncio.to_thread(_fetch_fear_greed)
                    fng_adj  = 0.05 if (fng < 20 or fng > 80) else 0.0
                    # SIGNAL_MARGIN: eşiği kıl payı geçen sinyaller elenir —
                    # daha az ama daha isabetli işlem (kararlılık paketi)
                    thr_adj  = _calc_dynamic_threshold(fng_adj, features, sym) + SIGNAL_MARGIN

                    # ── Çift yönlü tahmin ─────────────────────────────────────
                    pred_long, proba_long, pred_short, proba_short = \
                        _predict_bidir(model_payload, features, thr_adj)

                    # ── Risk Duvarı (FAZ 3 — K-19): ADX + trend vetosu + emir
                    #    defteri + çift-yön çözümü + kapasite TEK noktada
                    ob_imbalance = await asyncio.to_thread(_fetch_order_book_imbalance, sym)
                    thr_l_eff = float(model_payload.get("threshold_long", 0.5)) + thr_adj
                    thr_s_eff = float(model_payload.get("threshold_short", 0.5)) + thr_adj
                    dec = gate.evaluate(
                        sym=sym, features=features,
                        pred_long=pred_long, proba_long=proba_long,
                        pred_short=pred_short, proba_short=proba_short,
                        thr_long_eff=thr_l_eff, thr_short_eff=thr_s_eff,
                        ob_imbalance=ob_imbalance,
                        open_count=len(open_syms), max_positions=MAX_POSITIONS,
                    )
                    for _m in dec["logs"]:
                        broadcast({"phase": "server", "msg": _m})

                    if dec["emit_signal"]:
                        any_signal = dec["pred_long"] or dec["pred_short"]
                        sig_proba  = dec["proba"] if dec["direction"] else max(proba_long, proba_short)
                        broadcast({
                            "phase": "signal",
                            "symbol": sym,
                            "pred":   1 if any_signal else 0,
                            "proba":  round(sig_proba, 4),
                            "price":  round(entry_price, 2),
                            "direction": dec["direction"] or "—",
                            "ob_imbalance": round(ob_imbalance, 3),
                            "fng":    fng,
                            "thr_adj": round(thr_adj, 4),
                            "proba_long":  round(proba_long, 4),
                            "proba_short": round(proba_short, 4),
                        })

                    if dec["ob_blocked"]:
                        broadcast({"phase": "server",
                                   "msg": f"{sym} sinyal emir defteri tarafından bloklandı (OB={ob_imbalance:.2f})"})

                    # ── Karar kaydı (FAZ 4 — K-20) ───────────────────────────
                    await _emit_decision(
                        sym,
                        blocked_by=dec["blocked_by"],
                        direction=dec["direction"],
                        proba=round(dec["proba"], 4) if dec["proba"] is not None else None,
                        threshold=round(dec["threshold"], 4) if dec["threshold"] is not None else None,
                        opened=dec["allowed"],
                        detail=dec["detail"],
                    )

                    if not dec["allowed"]:
                        continue

                    chosen_dir = dec["direction"]
                    is_long    = chosen_dir == "LONG"
                    proba      = dec["proba"]
                    if is_long:
                        tp_price = entry_price * (1 + tp_pct)
                        sl_price = entry_price * (1 - sl_pct)
                    else:
                        tp_price = entry_price * (1 - tp_pct)
                        sl_price = entry_price * (1 + sl_pct)

                    if True:   # pozisyon açma bloğu (indentasyonu koru)

                        if paper_mode:
                            # Dinamik pozisyon boyutu + kaldıraç (proba-ölçekli, K-14)
                            margin, eff_leverage = _calc_position_margin(
                                demo_balance, peak_balance, demo_trades, sl_pct, tp_pct,
                                proba=proba,
                            )
                            # Korelasyon koruması: BTC-ETH ~0.9 korele — aynı yönde
                            # ikinci pozisyon fiilen çift risk → yarım boyut
                            if any(p["side"] == chosen_dir for p in demo_positions.values()):
                                margin *= 0.5
                            notional  = margin * eff_leverage
                            entry_fee = notional * FEE_RATE
                            demo_balance -= entry_fee
                            ts_now = int(time.time() * 1000)
                            db_id = await db.insert_trade({
                                "symbol":        sym,
                                "side":          chosen_dir,
                                "leverage":      eff_leverage,
                                "entry_price":   entry_price,
                                "quantity_usdt": margin,
                                "notional":      notional,
                                "entry_ts":      ts_now,
                                "paper":         True,
                            })
                            demo_positions[sym] = {
                                "entry":     entry_price,
                                "tp":        tp_price,
                                "sl":        sl_price,
                                "side":      chosen_dir,
                                "ts":        ts_now,
                                "db_id":     db_id,
                                "proba":     proba,
                                "margin":    margin,
                                "notional":  notional,
                                "leverage":  eff_leverage,
                                "entry_fee": entry_fee,
                            }
                            dd_pct = (peak_balance - demo_balance) / peak_balance * 100 if peak_balance > 0 else 0
                            open_syms.append(sym)
                            broadcast({
                                "phase": "trade_open",
                                "symbol": sym, "side": chosen_dir,
                                "entry": round(entry_price, 4),
                                "tp":    round(tp_price, 4),
                                "sl":    round(sl_price, 4),
                                "paper": True,
                            })
                            side_emoji = "📈" if chosen_dir == "LONG" else "📉"
                            tg.send_async(
                                f"{side_emoji} <b>{sym} {chosen_dir} Açıldı</b>\n"
                                f"Giriş: <b>{entry_price:.2f}</b>\n"
                                f"TP: {tp_price:.2f}  |  SL: {sl_price:.2f}\n"
                                f"Marjin: {margin:.2f} USDT × {eff_leverage}x = {notional:.2f} USDT\n"
                                f"Sinyal gücü: {proba*100:.1f}%\n"
                                f"Kasa: <b>{demo_balance:.2f} USDT</b>"
                            )
                            _broadcast_wallet()
                        else:
                            # Canlı mod: borsadaki gerçek USDT bakiyesi ile boyutlandır
                            try:
                                bal = await asyncio.to_thread(exchange.fetch_balance)
                                usdt_free = float(bal.get("USDT", {}).get("free") or 0.0)
                            except Exception as e_bal:
                                broadcast({"phase": "error",
                                           "msg": f"Bakiye okunamadı, işlem atlandı: {e_bal}"})
                                continue
                            if usdt_free < 5.0:
                                broadcast({"phase": "server",
                                           "msg": f"Yetersiz bakiye ({usdt_free:.2f} USDT) — işlem atlandı"})
                                continue
                            margin, eff_leverage = _calc_position_margin(
                                usdt_free, usdt_free, [], sl_pct, tp_pct,
                                proba=proba,
                            )
                            notional = margin * eff_leverage
                            order_id = await asyncio.to_thread(
                                _open_live_position, exchange, sym, chosen_dir,
                                entry_price, sl_pct, tp_pct, notional,
                            )
                            if order_id:
                                ts = int(time.time() * 1000)
                                await db.insert_trade({
                                    "symbol":         sym,
                                    "side":           chosen_dir,
                                    "leverage":       eff_leverage,
                                    "entry_price":    entry_price,
                                    "quantity_usdt":  margin,
                                    "notional":       notional,
                                    "entry_ts":       ts,
                                    "paper":          False,
                                })
                                open_syms.append(sym)

                except Exception as e:
                    msg = f"{sym} döngü hatası: {e}"
                    broadcast({"phase": "error", "msg": msg})
                    now = time.time()
                    if now - _last_error_ts.get(sym, 0) > 300:  # 5 dakikada bir Telegram
                        tg.send_async(f"⚠️ <b>Bot Hatası</b>\n{msg}")
                        _last_error_ts[sym] = now

            await asyncio.sleep(LOOP_INTERVAL)

    finally:
        ticker_task.cancel()
        await db.close()
        try:
            exchange.close()
        except Exception:
            pass
        broadcast({"phase": "server", "msg": "Trader durduruldu"})


def run(testnet: bool = True) -> None:
    asyncio.run(_run_async(testnet))
