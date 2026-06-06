import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import aiosqlite


def load_env_dotenv(dotenv_path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not dotenv_path.is_file():
        return values
    with dotenv_path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_project_root() -> Path:
    return Path(__file__).resolve().parent


def get_database_path() -> Path:
    root = get_project_root()
    env_path = root.parent / ".env"
    env_values = load_env_dotenv(env_path)
    db_path = env_values.get("DATABASE_PATH") or os.getenv("DATABASE_PATH")
    if db_path:
        return Path(db_path).expanduser().resolve()
    return root / "bot.sqlite"


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS historical_market_data (
    timestamp INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    UNIQUE(symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    leverage INTEGER NOT NULL DEFAULT 5,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity_usdt REAL NOT NULL,
    notional REAL NOT NULL,
    entry_ts INTEGER NOT NULL,
    exit_ts INTEGER,
    exit_reason TEXT,
    pnl_usdt REAL,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS model_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trained_at INTEGER NOT NULL,
    symbols TEXT,
    sl_pct REAL,
    tp_pct REAL,
    leverage INTEGER,
    win_rate REAL,
    rr REAL,
    precision REAL,
    f1 REAL,
    accuracy REAL,
    train_rows INTEGER,
    test_rows INTEGER,
    notes TEXT
);
"""


class Database:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = Path(db_path).expanduser().resolve() if db_path else get_database_path()
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(str(self.db_path))
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode = WAL;")
        await self.conn.execute("PRAGMA synchronous = NORMAL;")
        for stmt in _CREATE_TABLES.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await self.conn.execute(stmt)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    async def reset_market_data(self) -> None:
        assert self.conn is not None
        await self.conn.execute("DELETE FROM historical_market_data")
        await self.conn.commit()

    async def insert_klines(self, klines_list: Iterable[Dict[str, Any]]) -> int:
        assert self.conn is not None
        rows = [
            (
                int(row["timestamp"]),
                str(row["symbol"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            )
            for row in klines_list
        ]
        if not rows:
            return 0
        await self.conn.executemany(
            "INSERT OR REPLACE INTO historical_market_data (timestamp, symbol, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await self.conn.commit()
        return len(rows)

    async def insert_trade(self, trade: Dict[str, Any]) -> int:
        assert self.conn is not None
        cursor = await self.conn.execute(
            """INSERT INTO trades (symbol, side, leverage, entry_price, quantity_usdt, notional, entry_ts, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                trade["symbol"],
                trade["side"],
                trade.get("leverage", 5),
                trade["entry_price"],
                trade["quantity_usdt"],
                trade["notional"],
                trade["entry_ts"],
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def close_trade(self, trade_id: int, exit_price: float, exit_ts: int, exit_reason: str, pnl_usdt: float) -> None:
        assert self.conn is not None
        await self.conn.execute(
            "UPDATE trades SET exit_price=?, exit_ts=?, exit_reason=?, pnl_usdt=?, status='closed' WHERE id=?",
            (exit_price, exit_ts, exit_reason, pnl_usdt, trade_id),
        )
        await self.conn.commit()

    async def fetch_open_trades(self) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cursor = await self.conn.execute("SELECT * FROM trades WHERE status='open' ORDER BY entry_ts DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def fetch_trades(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cursor = await self.conn.execute(
            "SELECT * FROM trades ORDER BY entry_ts DESC LIMIT ? OFFSET ?", (limit, offset)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def insert_model_run(self, run: Dict[str, Any]) -> int:
        assert self.conn is not None
        cursor = await self.conn.execute(
            """INSERT INTO model_runs (trained_at, symbols, sl_pct, tp_pct, leverage,
               win_rate, rr, precision, f1, accuracy, train_rows, test_rows, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run["trained_at"],
                run.get("symbols"),
                run.get("sl_pct"),
                run.get("tp_pct"),
                run.get("leverage"),
                run.get("win_rate"),
                run.get("rr"),
                run.get("precision"),
                run.get("f1"),
                run.get("accuracy"),
                run.get("train_rows"),
                run.get("test_rows"),
                run.get("notes"),
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def fetch_latest_model_run(self) -> Optional[Dict[str, Any]]:
        assert self.conn is not None
        cursor = await self.conn.execute("SELECT * FROM model_runs ORDER BY trained_at DESC LIMIT 1")
        row = await cursor.fetchone()
        return dict(row) if row else None
