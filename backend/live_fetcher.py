"""
Binance'dan canlı 1m mumları çekip DB'ye yazar (auth gerektirmez — public endpoint).
Çalıştır: python live_fetcher.py [--once]
  --once : Tek seferlik çek ve çık (cron/scheduler için)
  Varsayılan: 60 saniyede bir yeni mumları çek (sonsuz döngü)
"""
import argparse
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

import ccxt
import requests

from config import METRICS_POLL_S, RETRAIN_DAYS
from database import Database

SYMBOLS = ["BTCUSDT", "ETHUSDT"]  # Binance public API formatı
TIMEFRAME = "1m"
LIMIT = 5       # Son 5 mumu çek — kısa ağ kesintilerinde kaçan mumlar kendiliğinden telafi olur
BASE_URL = "https://fapi.binance.com/fapi/v1/klines"
FAPI_BASE = "https://fapi.binance.com"


def fetch_klines(symbol: str, limit: int = 2):
    resp = requests.get(BASE_URL, params={
        "symbol": symbol,
        "interval": TIMEFRAME,
        "limit": limit,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def normalize_symbol(raw: str) -> str:
    raw = raw.upper()
    if raw.endswith("USDT"):
        return f"{raw[:-4]}/USDT"
    return raw


def build_exchange() -> ccxt.Exchange:
    """Public ccxt USDT-M Futures nesnesi (funding rate + open interest için;
    auth gerekmez)."""
    return ccxt.binanceusdm({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })


async def fetch_and_store_metrics(db: Database, exchange: ccxt.Exchange) -> int:
    """
    Her sembol için güncel funding rate + open interest çekip market_metrics'e
    yazar. Veri kaynağı ccxt (fetch_funding_rate → fundingRate;
    fetch_open_interest → openInterestAmount|openInterestValue). Hata SESSİZ
    geçilir (log at, döngüyü öldürme). Yazılan satır sayısını döner.
    """
    now_ms = int(time.time() * 1000)
    records = []
    for sym_raw in SYMBOLS:
        sym = normalize_symbol(sym_raw)
        funding = None
        open_interest = None
        try:
            fr = exchange.fetch_funding_rate(sym)
            if fr.get("fundingRate") is not None:
                funding = float(fr["fundingRate"])
        except Exception as e:
            print(f"[WARN] {sym} funding: {e}")
        try:
            oi = exchange.fetch_open_interest(sym)
            oi_val = oi.get("openInterestAmount")
            if oi_val is None:
                oi_val = oi.get("openInterestValue")
            if oi_val is not None:
                open_interest = float(oi_val)
        except Exception as e:
            print(f"[WARN] {sym} open interest: {e}")
        if funding is not None or open_interest is not None:
            records.append({
                "ts": now_ms, "symbol": sym,
                "funding_rate": funding, "open_interest": open_interest,
            })
    if not records:
        return 0
    return await db.insert_market_metrics(records)


def _fapi_get(path: str, params: dict) -> list:
    resp = requests.get(FAPI_BASE + path, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


async def backfill_market_metrics(days: Optional[int] = None) -> int:
    """
    Eğitim için geçmiş funding + open interest verisini market_metrics'e yazar.
    Kendi DB bağlantısını açar (train_engine best-effort çağırır).
      • Funding geçmişi : GET /fapi/v1/fundingRate (limit 1000 ≈ 45 günün tamamı)
      • OI geçmişi      : GET /futures/data/openInterestHist (period=5m, sayfalı;
                          Binance SADECE son ~30 günü verir — daha eskisi yoksa
                          alabildiğini yaz).
    Her ikisi de upsert edilir. Ağ hatası eğitimi durdurmasın diye çağıran
    taraf try/except ile sarmalı; burada da tek sembol hatası diğerini kesmez.
    """
    if not days or days <= 0:
        days = RETRAIN_DAYS
    since_ms = int((time.time() - days * 86400) * 1000)
    db = Database()
    await db.connect()
    total = 0
    try:
        for sym_raw in SYMBOLS:
            sym = normalize_symbol(sym_raw)
            records = []
            # ── Funding geçmişi ──────────────────────────────────────────────
            try:
                data = _fapi_get("/fapi/v1/fundingRate",
                                 {"symbol": sym_raw, "limit": 1000})
                for d in data:
                    ts = int(d["fundingTime"])
                    if ts >= since_ms:
                        records.append({
                            "ts": ts, "symbol": sym,
                            "funding_rate": float(d["fundingRate"]),
                            "open_interest": None,
                        })
            except Exception as e:
                print(f"[WARN] {sym} funding backfill: {e}")
            # ── OI geçmişi (5m, sayfalayarak geriye) ─────────────────────────
            try:
                end_time = None
                for _ in range(20):   # 20 × 500 × 5m ≈ 34 gün üst sınır
                    params = {"symbol": sym_raw, "period": "5m", "limit": 500}
                    if end_time is not None:
                        params["endTime"] = end_time
                    data = _fapi_get("/futures/data/openInterestHist", params)
                    if not data:
                        break
                    for d in data:
                        val = d.get("sumOpenInterest") or d.get("sumOpenInterestValue")
                        if val is not None:
                            records.append({
                                "ts": int(d["timestamp"]), "symbol": sym,
                                "funding_rate": None,
                                "open_interest": float(val),
                            })
                    oldest = int(data[0]["timestamp"])
                    if oldest <= since_ms or len(data) < 500:
                        break
                    end_time = oldest - 1
            except Exception as e:
                print(f"[WARN] {sym} OI backfill: {e}")
            if records:
                total += await db.insert_market_metrics(records)
    finally:
        await db.close()
    return total


async def fetch_and_store(db: Database) -> int:
    """Tüm semboller için son tamamlanmış mumu çekip DB'ye yazar. Eklenen satır sayısını döner."""
    total = 0
    for sym_raw in SYMBOLS:
        try:
            rows = fetch_klines(sym_raw, limit=LIMIT)
            # Son mum henüz kapanmamış → onu atla, kalan TÜM kapanmış mumları yaz.
            # INSERT OR REPLACE idempotent olduğu için tekrar yazmak zararsız.
            if len(rows) < 2:
                continue
            records = [
                {
                    "timestamp": int(row[0]),
                    "symbol":    normalize_symbol(sym_raw),
                    "open":      float(row[1]),
                    "high":      float(row[2]),
                    "low":       float(row[3]),
                    "close":     float(row[4]),
                    "volume":    float(row[5]),
                }
                for row in rows[:-1]
            ]
            n = await db.insert_klines(records)
            total += n
        except Exception as e:
            print(f"[WARN] {sym_raw}: {e}")
    return total


async def run_loop(once: bool = False) -> None:
    db = Database()
    await db.connect()
    exchange = build_exchange()
    last_metrics = 0.0    # son funding/OI çekiminin zamanı (monotonik değil, wall clock)
    try:
        while True:
            t0 = time.time()
            added = await fetch_and_store(db)
            now   = datetime.now(timezone.utc).strftime("%H:%M:%S")
            if added:
                print(f"[{now}] +{added} yeni mum eklendi")
            else:
                print(f"[{now}] Yeni mum yok (zaten mevcut)")

            # ── Piyasa metrikleri: her METRICS_POLL_S'de bir funding + OI ────
            if once or (t0 - last_metrics) >= METRICS_POLL_S:
                last_metrics = t0
                try:
                    m = await fetch_and_store_metrics(db, exchange)
                    if m:
                        print(f"[{now}] {m} metrik satırı (funding/OI) yazıldı")
                except Exception as e:
                    print(f"[WARN] metrik çekimi: {e}")

            if once:
                break

            # Bir sonraki tam dakikaya kadar bekle
            elapsed = time.time() - t0
            sleep_s = max(60 - elapsed, 5)
            await asyncio.sleep(sleep_s)
    finally:
        await db.close()
        try:
            exchange.close()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canlı 1m mum çekici")
    parser.add_argument("--once", action="store_true", help="Tek seferlik çek ve çık")
    args = parser.parse_args()
    asyncio.run(run_loop(once=args.once))
