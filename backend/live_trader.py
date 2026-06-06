"""
Binance USDT-M Futures Live Trader
Testnet: BINANCE_TESTNET=true (varsayılan)
Mainnet: BINANCE_TESTNET=false (backtest kriterleri karşılanmalı)
"""
import asyncio
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import ccxt
import joblib
import numpy as np
import pandas as pd

try:
    from ta.momentum import RSIIndicator
    from ta.trend import MACD
    from ta.volatility import BollingerBands, AverageTrueRange
except Exception:
    RSIIndicator = MACD = BollingerBands = AverageTrueRange = None

from database import Database

MODEL_PATH = Path(__file__).resolve().parent / "model.bin"

SYMBOLS = ["BTC/USDT", "ETH/USDT"]
TIMEFRAME = "5m"
LEVERAGE = 5
POSITION_USDT = 50.0      # teminat başına
MAX_POSITIONS = 2
FEE_RATE = 0.0004
LOOP_INTERVAL = 30        # saniye

FEATURE_COLS = [
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "bb_position", "bb_width",
    "atr_14", "volume_ratio",
    "ret_1", "ret_5", "ret_15",
]

_stop_flag = False
broadcast: Callable[[Dict[str, Any]], None] = lambda ev: None


def stop() -> None:
    global _stop_flag
    _stop_flag = True


def _load_model() -> Dict[str, Any]:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model bulunamadı: {MODEL_PATH}")
    return joblib.load(str(MODEL_PATH))


def _build_exchange(testnet: bool) -> ccxt.Exchange:
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_API_SECRET", "")

    exchange = ccxt.binanceusdm({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })

    if testnet:
        exchange.set_sandbox_mode(True)
        broadcast({"phase": "server", "msg": "TESTNET modu aktif"})
    else:
        broadcast({"phase": "server", "msg": "⚠️  MAINNET modu aktif — gerçek para kullanılıyor"})

    return exchange


def _fetch_ohlcv(exchange: ccxt.Exchange, symbol: str, limit: int = 100) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def _compute_features(df: pd.DataFrame) -> Optional[Dict[str, float]]:
    if len(df) < 30 or RSIIndicator is None:
        return None
    close = df["close"]

    rsi = RSIIndicator(close=close, window=14).rsi()
    macd_obj = MACD(close=close)
    macd_line = macd_obj.macd()
    macd_sig = macd_obj.macd_signal()
    macd_hist = macd_obj.macd_diff()

    bb = BollingerBands(close=close, window=20, window_dev=2)
    bb_h = bb.bollinger_hband()
    bb_l = bb.bollinger_lband()
    bb_m = bb.bollinger_mavg()
    bb_w = (bb_h - bb_l) / bb_m.replace(0, np.nan)
    bb_pos = (close - bb_l) / (bb_h - bb_l).replace(0, np.nan)

    atr = AverageTrueRange(high=df["high"], low=df["low"], close=close, window=14).average_true_range()
    vol_ratio = df["volume"] / df["volume"].rolling(20).mean().replace(0, np.nan)

    ret1 = close.pct_change(1)
    ret5 = close.pct_change(5)
    ret15 = close.pct_change(15)

    row = {
        "rsi_14": rsi.iloc[-1],
        "macd": macd_line.iloc[-1],
        "macd_signal": macd_sig.iloc[-1],
        "macd_hist": macd_hist.iloc[-1],
        "bb_position": bb_pos.iloc[-1],
        "bb_width": bb_w.iloc[-1],
        "atr_14": atr.iloc[-1],
        "volume_ratio": vol_ratio.iloc[-1],
        "ret_1": ret1.iloc[-1],
        "ret_5": ret5.iloc[-1],
        "ret_15": ret15.iloc[-1],
    }
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in row.values()):
        return None
    return row


def _predict(model_payload: Dict, features: Dict[str, float]) -> tuple[int, float]:
    model = model_payload["model"]
    cols = model_payload.get("feature_cols", FEATURE_COLS)
    X = np.array([[features.get(c, 0.0) for c in cols]], dtype=np.float32)
    pred = int(model.predict(X)[0])
    proba = float(model.predict_proba(X)[0][1])
    return pred, proba


def _set_leverage(exchange: ccxt.Exchange, symbol: str) -> None:
    try:
        exchange.set_leverage(LEVERAGE, symbol)
    except Exception as e:
        broadcast({"phase": "server", "msg": f"Kaldıraç ayarlanamadı ({symbol}): {e}"})


def _open_position(exchange: ccxt.Exchange, symbol: str, entry_price: float, sl_pct: float, tp_pct: float) -> Optional[str]:
    try:
        notional = POSITION_USDT * LEVERAGE
        qty = round(notional / entry_price, 4)

        order = exchange.create_order(symbol, "market", "buy", qty)
        order_id = order.get("id", "")

        sl_price = round(entry_price * (1 - sl_pct), 4)
        tp_price = round(entry_price * (1 + tp_pct), 4)

        exchange.create_order(symbol, "stop_market", "sell", qty, params={"stopPrice": sl_price, "reduceOnly": True})
        exchange.create_order(symbol, "take_profit_market", "sell", qty, params={"stopPrice": tp_price, "reduceOnly": True})

        broadcast({
            "phase": "trade_open",
            "symbol": symbol,
            "entry": entry_price,
            "sl": sl_price,
            "tp": tp_price,
            "qty": qty,
            "leverage": LEVERAGE,
        })
        return order_id
    except Exception as e:
        broadcast({"phase": "error", "msg": f"Pozisyon açılamadı ({symbol}): {e}"})
        return None


def _sync_positions(exchange: ccxt.Exchange, db: Database) -> List[str]:
    """Exchange'deki açık pozisyon sembollerini döner."""
    try:
        positions = exchange.fetch_positions(SYMBOLS)
        open_syms = [p["symbol"] for p in positions if abs(float(p.get("contracts", 0) or 0)) > 0]
        return open_syms
    except Exception as e:
        broadcast({"phase": "error", "msg": f"Pozisyon sorgulanamadı: {e}"})
        return []


async def _run_async(testnet: bool) -> None:
    global _stop_flag
    _stop_flag = False

    model_payload = _load_model()
    sl_pct: float = model_payload.get("sl_pct", 0.005)
    tp_pct: float = model_payload.get("tp_pct", 0.015)
    broadcast({"phase": "server", "msg": f"Model yüklendi | SL={sl_pct*100:.1f}% TP={tp_pct*100:.1f}%"})

    exchange = _build_exchange(testnet)
    db = Database()
    await db.connect()

    for sym in SYMBOLS:
        _set_leverage(exchange, sym)

    broadcast({"phase": "server", "msg": f"Trader döngüsü başladı | Semboller: {SYMBOLS}"})

    try:
        while not _stop_flag:
            open_syms = _sync_positions(exchange, db)

            for sym in SYMBOLS:
                if _stop_flag:
                    break
                if sym in open_syms:
                    continue  # Zaten açık pozisyon var

                try:
                    df = _fetch_ohlcv(exchange, sym, limit=100)
                    features = _compute_features(df)
                    if features is None:
                        continue

                    pred, proba = _predict(model_payload, features)
                    broadcast({
                        "phase": "signal",
                        "symbol": sym,
                        "pred": pred,
                        "proba": round(proba, 4),
                    })

                    if pred == 1 and len(open_syms) < MAX_POSITIONS:
                        entry_price = float(df["close"].iloc[-1])
                        order_id = _open_position(exchange, sym, entry_price, sl_pct, tp_pct)
                        if order_id:
                            ts = int(time.time() * 1000)
                            trade_id = await db.insert_trade({
                                "symbol": sym,
                                "side": "LONG",
                                "leverage": LEVERAGE,
                                "entry_price": entry_price,
                                "quantity_usdt": POSITION_USDT,
                                "notional": POSITION_USDT * LEVERAGE,
                                "entry_ts": ts,
                            })
                            broadcast({"phase": "trade_open", "symbol": sym, "db_id": trade_id})
                            open_syms.append(sym)

                except Exception as e:
                    broadcast({"phase": "error", "msg": f"{sym} döngü hatası: {e}"})

            await asyncio.sleep(LOOP_INTERVAL)

    finally:
        await db.close()
        try:
            exchange.close()
        except Exception:
            pass
        broadcast({"phase": "server", "msg": "Trader durduruldu"})


def run(testnet: bool = True) -> None:
    asyncio.run(_run_async(testnet))
