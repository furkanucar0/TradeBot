"""
Binance USDT-M Futures historical klines zip loader.
Zip naming: BTCUSDT-5m-2024-01.zip  (data.binance.vision format)
Usage:
    python zip_loader.py            # append new data
    python zip_loader.py --reset    # clear DB first, then load
"""
import argparse
import asyncio
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional
from zipfile import ZipFile

import pandas as pd

from database import Database

ZIP_FOLDER = Path(__file__).resolve().parent / "zips"
# Hem aylık (BTCUSDT-5m-2024-01.zip) hem günlük (BTCUSDT-1m-2026-05-01.zip) formatı
FILENAME_RE = re.compile(
    r"(?P<symbol>[A-Z0-9]+)-(?P<tf>[^-]+)-(?P<year>\d{4})-(?P<month>\d{2})(?:-(?P<day>\d{2}))?\.zip$",
    re.IGNORECASE,
)


def normalize_symbol(raw: str) -> str:
    raw = raw.strip().upper()
    if raw.endswith("USDT"):
        return f"{raw[:-4]}/USDT"
    if raw.endswith("BUSD"):
        return f"{raw[:-4]}/BUSD"
    if "/" in raw:
        return raw
    return raw


def parse_zip_meta(path: Path) -> Optional[Dict[str, str]]:
    m = FILENAME_RE.search(path.name)
    if not m:
        return None
    day = m.group("day")
    period = f"{m.group('year')}-{m.group('month')}-{day}" if day else f"{m.group('year')}-{m.group('month')}"
    return {
        "symbol": normalize_symbol(m.group("symbol")),
        "tf": m.group("tf"),
        "period": period,
    }


def extract_csv(zip_bytes: bytes) -> Optional[BytesIO]:
    with ZipFile(BytesIO(zip_bytes)) as zf:
        csvs = [e for e in zf.infolist() if e.filename.lower().endswith(".csv")]
        if not csvs:
            return None
        with zf.open(csvs[0]) as f:
            return BytesIO(f.read())


def read_ohlcv(buf: BytesIO) -> pd.DataFrame:
    buf.seek(0)
    # Binance günlük zip'lerde başlık satırı var, aylıklarda yok; otomatik tespit et
    peek = buf.read(64).decode("utf-8", errors="ignore")
    buf.seek(0)
    has_header = not peek.lstrip().startswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"))

    col_names = [
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.read_csv(
        buf,
        header=0 if has_header else None,
        names=None if has_header else col_names,
    )
    # Başlık varsa Binance sütun isimlerini normalleştir
    if has_header:
        df.columns = col_names[:len(df.columns)]

    df = df[["timestamp", "open", "high", "low", "close", "volume"]].dropna()
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("int64")
    df = df.dropna(subset=["timestamp"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df.dropna()


async def load_zip(db: Database, path: Path) -> None:
    meta = parse_zip_meta(path)
    if meta is None:
        print(f"[SKIP] {path.name} — isim formatı eşleşmiyor")
        return

    csv_buf = extract_csv(path.read_bytes())
    if csv_buf is None:
        print(f"[SKIP] {path.name} — ZIP içinde CSV bulunamadı")
        return

    df = read_ohlcv(csv_buf)
    rows = [
        {
            "timestamp": int(row["timestamp"]),
            "symbol": meta["symbol"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for _, row in df.iterrows()
    ]
    n = await db.insert_klines(rows)
    print(f"[OK] {meta['symbol']} {meta['period']} ({meta['tf']}) — {n} satır yüklendi")


async def main(reset: bool = False) -> None:
    if not ZIP_FOLDER.exists():
        print(f"[ERROR] ZIP klasörü bulunamadı: {ZIP_FOLDER}")
        sys.exit(1)

    zips = sorted(ZIP_FOLDER.glob("*.zip"))
    if not zips:
        print(f"[INFO] {ZIP_FOLDER} içinde .zip dosyası yok")
        return

    db = Database()
    await db.connect()
    try:
        if reset:
            await db.reset_market_data()
            print("[INFO] Veritabanı temizlendi")

        for path in zips:
            await load_zip(db, path)

        print(f"\n[DONE] {len(zips)} zip dosyası işlendi")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Binance Futures zip loader")
    parser.add_argument("--reset", action="store_true", help="DB'yi temizle ve yeniden yükle")
    args = parser.parse_args()
    asyncio.run(main(reset=args.reset))
