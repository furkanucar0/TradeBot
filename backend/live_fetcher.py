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

import requests

from database import Database

SYMBOLS = ["BTCUSDT", "ETHUSDT"]  # Binance public API formatı
TIMEFRAME = "1m"
LIMIT = 5       # Son 5 mumu çek — kısa ağ kesintilerinde kaçan mumlar kendiliğinden telafi olur
BASE_URL = "https://fapi.binance.com/fapi/v1/klines"


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
    try:
        while True:
            t0 = time.time()
            added = await fetch_and_store(db)
            now   = datetime.now(timezone.utc).strftime("%H:%M:%S")
            if added:
                print(f"[{now}] +{added} yeni mum eklendi")
            else:
                print(f"[{now}] Yeni mum yok (zaten mevcut)")

            if once:
                break

            # Bir sonraki tam dakikaya kadar bekle
            elapsed = time.time() - t0
            sleep_s = max(60 - elapsed, 5)
            await asyncio.sleep(sleep_s)
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canlı 1m mum çekici")
    parser.add_argument("--once", action="store_true", help="Tek seferlik çek ve çık")
    args = parser.parse_args()
    asyncio.run(run_loop(once=args.once))
