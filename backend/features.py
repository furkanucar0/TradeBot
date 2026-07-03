"""
Ortak özellik mühendisliği modülü.
train_engine (toplu eğitim) ve live_trader (canlı sinyal) AYNI implementasyonu
kullanır — train/serve kayması (skew) olmaması için indikatör matematiği
sadece burada tanımlıdır.

Kullanım:
  Eğitim : add_features(df)                    # çok sembollü tarihsel veri
  Canlı  : add_features(df, d1_override=d1_df) # tek sembollük 1m buffer +
                                               # REST'ten çekilmiş günlük barlar
"""
from typing import Optional

import numpy as np
import pandas as pd

try:
    from ta.momentum import RSIIndicator, StochRSIIndicator
    from ta.trend import MACD, ADXIndicator
    from ta.volatility import BollingerBands, AverageTrueRange
    TA_AVAILABLE = True
except Exception:
    TA_AVAILABLE = False

FEATURE_COLS = [
    # ── 1m (17) ──────────────────────────────────────────────────────────────
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "bb_position", "bb_width",
    "atr_14", "volume_ratio",
    "ret_1_n", "ret_5_n", "ret_15_n",
    "obv_ratio",
    "ha_body", "ha_upper_shadow", "ha_lower_shadow",
    "volume_delta", "volume_accel",
    # ── Stochastic RSI (2) ───────────────────────────────────────────────────
    "stoch_rsi_k", "stoch_rsi_d",
    # ── Zaman / Seans (4) ────────────────────────────────────────────────────
    "hour_sin", "hour_cos", "is_london_open", "is_ny_open",
    # ── 1h MTF (6) ───────────────────────────────────────────────────────────
    "h1_rsi", "h1_macd_hist", "h1_ema_cross", "h1_bb_pos", "h1_adx", "h1_atr_ratio",
    # ── 1d MTF (3) ───────────────────────────────────────────────────────────
    "d1_rsi", "d1_ema_slope", "d1_bb_pos",
    # ── Trend Hizalama (1) ───────────────────────────────────────────────────
    "tf_alignment",
]


def add_features(df: pd.DataFrame, d1_override: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    OHLCV DataFrame'ine FEATURE_COLS sütunlarını ekler.

    df          : timestamp(ms), symbol, open, high, low, close, volume
    d1_override : günlük OHLCV (timestamp ms). Verilirse 1d özellikler
                  resample yerine bu seriden hesaplanır (canlı mod — 1m buffer
                  21 günden kısa olduğu için). Sadece tek sembollü df ile
                  kullanılmalıdır. Son barı henüz kapanmamış olabilir; shift(1)
                  sayesinde her zaman bir önceki TAMAMLANMIŞ gün kullanılır.
    """
    if not TA_AVAILABLE:
        raise RuntimeError("'ta' kütüphanesi gerekli: pip install ta")
    if d1_override is not None and df["symbol"].nunique() > 1:
        raise ValueError("d1_override sadece tek sembollü df ile kullanılabilir")

    results = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("timestamp").copy()
        close = g["close"]

        # ── 1m indikatörler ──────────────────────────────────────────────────
        g["rsi_14"] = RSIIndicator(close=close, window=14).rsi()

        macd_obj = MACD(close=close)
        g["macd"]        = macd_obj.macd()
        g["macd_signal"] = macd_obj.macd_signal()
        g["macd_hist"]   = macd_obj.macd_diff()

        bb     = BollingerBands(close=close, window=20, window_dev=2)
        bb_h   = bb.bollinger_hband()
        bb_l   = bb.bollinger_lband()
        bb_m   = bb.bollinger_mavg()
        bb_w   = (bb_h - bb_l) / bb_m.replace(0, np.nan)
        g["bb_position"] = (close - bb_l) / (bb_h - bb_l).replace(0, np.nan)
        g["bb_width"]    = bb_w

        g["atr_14"] = AverageTrueRange(
            high=g["high"], low=g["low"], close=close, window=14
        ).average_true_range()

        vol_ma = g["volume"].rolling(20).mean()
        g["volume_ratio"] = g["volume"] / vol_ma.replace(0, np.nan)

        g["ret_1"]  = close.pct_change(1)
        g["ret_5"]  = close.pct_change(5)
        g["ret_15"] = close.pct_change(15)

        # ATR-normalize edilmiş return'lar — rejim değişikliğine dayanıklı
        atr_pct       = g["atr_14"] / close.replace(0, np.nan)
        g["ret_1_n"]  = (g["ret_1"]  / atr_pct.replace(0, np.nan)).clip(-10, 10)
        g["ret_5_n"]  = (g["ret_5"]  / atr_pct.replace(0, np.nan)).clip(-10, 10)
        g["ret_15_n"] = (g["ret_15"] / atr_pct.replace(0, np.nan)).clip(-10, 10)

        # Pencereli işaretli hacim akışı [-1, 1] — kümülatif OBV yerine
        # pencereli form: buffer uzunluğundan bağımsız, train/live tutarlı.
        signed_vol = (np.sign(close.diff()) * g["volume"]).fillna(0.0)
        vol_sum20  = g["volume"].rolling(20).sum()
        g["obv_ratio"] = signed_vol.rolling(20).sum() / vol_sum20.replace(0, np.nan)

        ha_close = (g["open"] + g["high"] + g["low"] + close) / 4
        ha_open  = ((g["open"] + close) / 2).shift(1)
        ha_max   = ha_close.clip(lower=ha_open)
        ha_min   = ha_close.clip(upper=ha_open)
        g["ha_body"]         = ha_close - ha_open
        g["ha_upper_shadow"] = g["high"] - ha_max
        g["ha_lower_shadow"] = ha_min - g["low"]

        vol_ma5 = g["volume"].rolling(5).mean().replace(0, np.nan)
        g["volume_delta"] = (g["volume"] - vol_ma5) / vol_ma5
        g["volume_accel"] = g["volume"].pct_change(1)

        # ── Stochastic RSI ────────────────────────────────────────────────────
        stoch = StochRSIIndicator(close=close, window=14, smooth1=3, smooth2=3)
        g["stoch_rsi_k"] = stoch.stochrsi_k()
        g["stoch_rsi_d"] = stoch.stochrsi_d()

        # ── Zaman / Seans özellikleri ─────────────────────────────────────────
        ts_dt = pd.to_datetime(g["timestamp"], unit="ms", utc=True)
        g["hour_sin"]       = np.sin(2 * np.pi * ts_dt.dt.hour / 24).values
        g["hour_cos"]       = np.cos(2 * np.pi * ts_dt.dt.hour / 24).values
        g["is_london_open"] = ((ts_dt.dt.hour >= 7) & (ts_dt.dt.hour < 10)).astype(float).values
        g["is_ny_open"]     = ((ts_dt.dt.hour >= 13) & (ts_dt.dt.hour < 16)).astype(float).values

        # ── MTF: DatetimeIndex ile resample ──────────────────────────────────
        orig_idx  = g.index.copy()
        g.index   = ts_dt

        # 1h OHLCV
        g_1h = g[["open", "high", "low", "close", "volume"]].resample("1h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()

        if len(g_1h) >= 27:
            h1_c = g_1h["close"]
            h1_rsi  = RSIIndicator(close=h1_c, window=14).rsi()
            h1_macd = MACD(close=h1_c).macd_diff()
            h1_ef   = h1_c.ewm(span=9, adjust=False).mean()
            h1_es   = h1_c.ewm(span=21, adjust=False).mean()
            h1_ema_cross = np.sign(h1_ef - h1_es)
            h1_bb   = BollingerBands(close=h1_c, window=20, window_dev=2)
            h1_bb_pos = (h1_c - h1_bb.bollinger_lband()) / (
                h1_bb.bollinger_hband() - h1_bb.bollinger_lband()
            ).replace(0, np.nan)
            h1_adx  = ADXIndicator(
                high=g_1h["high"], low=g_1h["low"], close=h1_c, window=14
            ).adx()
            h1_atr  = AverageTrueRange(
                high=g_1h["high"], low=g_1h["low"], close=h1_c, window=14
            ).average_true_range()

            h1_df = pd.DataFrame({
                "h1_rsi":       h1_rsi,
                "h1_macd_hist": h1_macd,
                "h1_ema_cross": h1_ema_cross,
                "h1_bb_pos":    h1_bb_pos,
                "h1_adx":       h1_adx,
            }, index=g_1h.index).shift(1)   # lookahead önle

            h1_atr_s = h1_atr.shift(1)

            for col in h1_df.columns:
                g[col] = h1_df[col].reindex(g.index, method="ffill")
            g["h1_atr_ratio"] = (
                h1_atr_s.reindex(g.index, method="ffill") / g["atr_14"].replace(0, np.nan)
            )
        else:
            for col in ["h1_rsi", "h1_macd_hist", "h1_ema_cross",
                        "h1_bb_pos", "h1_adx", "h1_atr_ratio"]:
                g[col] = np.nan

        # 1d OHLCV — canlıda REST'ten gelen günlük barlar, eğitimde resample
        if d1_override is not None:
            d1_src = d1_override.copy()
            d1_src.index = pd.to_datetime(d1_src["timestamp"], unit="ms", utc=True)
            g_1d = d1_src[["open", "high", "low", "close", "volume"]].sort_index()
        else:
            g_1d = g[["open", "high", "low", "close", "volume"]].resample("1D").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            ).dropna()

        if len(g_1d) >= 21:
            d1_c  = g_1d["close"]
            d1_rsi = RSIIndicator(close=d1_c, window=14).rsi()
            d1_ema = d1_c.ewm(span=20, adjust=False).mean()
            d1_ema_slope = np.sign(d1_ema.diff(3))
            d1_bb  = BollingerBands(close=d1_c, window=20, window_dev=2)
            d1_bb_pos = (d1_c - d1_bb.bollinger_lband()) / (
                d1_bb.bollinger_hband() - d1_bb.bollinger_lband()
            ).replace(0, np.nan)

            d1_df = pd.DataFrame({
                "d1_rsi":       d1_rsi,
                "d1_ema_slope": d1_ema_slope,
                "d1_bb_pos":    d1_bb_pos,
            }, index=g_1d.index).shift(1)

            for col in d1_df.columns:
                g[col] = d1_df[col].reindex(g.index, method="ffill")
        else:
            for col in ["d1_rsi", "d1_ema_slope", "d1_bb_pos"]:
                g[col] = np.nan

        # ── TF Alignment (0–3) ────────────────────────────────────────────────
        m1_bull = (g["rsi_14"].fillna(50) > 50).astype(float)
        h1_bull = pd.Series(g["h1_ema_cross"].values, index=g.index).fillna(0).gt(0).astype(float)
        d1_bull = pd.Series(g["d1_ema_slope"].values, index=g.index).fillna(0).gt(0).astype(float)
        g["tf_alignment"] = (m1_bull + h1_bull + d1_bull).values

        # DatetimeIndex'i geri al
        g.index = orig_idx
        results.append(g)

    return pd.concat(results).reset_index(drop=True)


def latest_features(df: pd.DataFrame, d1_df: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """
    Canlı mod: 1m buffer'ın son mumu için özellik sözlüğü döner.
    Herhangi bir özellik NaN ise None döner (eksik veriyle sinyal üretme).
    """
    if len(df) < 60:
        return None
    work = df.copy()
    if "symbol" not in work.columns:
        work["symbol"] = "LIVE"
    feat = add_features(work, d1_override=d1_df)
    row = feat.iloc[-1]
    out = {}
    for c in FEATURE_COLS:
        v = row.get(c)
        if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
            return None
        out[c] = float(v)
    return out
