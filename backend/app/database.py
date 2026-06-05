import aiosqlite
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS market_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        UNIQUE(symbol, timestamp)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS market_features (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        rsi REAL,
        macd_line REAL,
        macd_signal REAL,
        macd_hist REAL,
        bb_upper REAL,
        bb_middle REAL,
        bb_lower REAL,
        bb_width REAL,
        return_1m REAL,
        return_5m REAL,
        close_to_upper REAL,
        close_to_lower REAL,
        future_return_10m REAL,
        target_profit_1_5 INTEGER,
        UNIQUE(symbol, timestamp)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        entry_price REAL NOT NULL,
        exit_price REAL,
        quantity REAL NOT NULL,
        entry_timestamp INTEGER NOT NULL,
        exit_timestamp INTEGER,
        profit_loss REAL,
        status TEXT NOT NULL,
        stop_loss REAL,
        take_profit REAL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS model_training_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER NOT NULL,
        symbol TEXT,
        model_type TEXT NOT NULL,
        train_rows INTEGER NOT NULL,
        accuracy REAL,
        loss REAL,
        notes TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS bot_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL
    );
    """,
]


class Database:
    def __init__(self, db_path: str = "./backend/bot.sqlite"):
        self.db_path = db_path
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON;")
        await self.create_tables()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def create_tables(self) -> None:
        assert self.conn is not None
        async with self.conn.executescript("\n".join(CREATE_TABLES_SQL)):
            pass
        await self.conn.commit()

    async def insert_ohlcv(self, symbol: str, ohlcv_rows: Iterable[Dict[str, Any]]) -> None:
        assert self.conn is not None
        query = """
            INSERT OR IGNORE INTO market_data
            (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        await self.conn.executemany(
            query,
            [
                (
                    symbol,
                    row["timestamp"],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                )
                for row in ohlcv_rows
            ],
        )
        await self.conn.commit()

    async def insert_features(self, symbol: str, feature_rows: Iterable[Dict[str, Any]]) -> None:
        assert self.conn is not None
        query = """
            INSERT OR IGNORE INTO market_features
            (symbol, timestamp, rsi, macd_line, macd_signal, macd_hist, bb_upper, bb_middle, bb_lower,
             bb_width, return_1m, return_5m, close_to_upper, close_to_lower, future_return_10m, target_profit_1_5)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        await self.conn.executemany(
            query,
            [
                (
                    symbol,
                    row["timestamp"],
                    row.get("rsi"),
                    row.get("macd_line"),
                    row.get("macd_signal"),
                    row.get("macd_hist"),
                    row.get("bb_upper"),
                    row.get("bb_middle"),
                    row.get("bb_lower"),
                    row.get("bb_width"),
                    row.get("return_1m"),
                    row.get("return_5m"),
                    row.get("close_to_upper"),
                    row.get("close_to_lower"),
                    row.get("future_return_10m"),
                    row.get("target_profit_1_5"),
                )
                for row in feature_rows
            ],
        )
        await self.conn.commit()

    async def insert_trade(self, trade: Dict[str, Any]) -> int:
        assert self.conn is not None
        query = """
            INSERT INTO trade_history
            (symbol, side, entry_price, exit_price, quantity, entry_timestamp, exit_timestamp,
             profit_loss, status, stop_loss, take_profit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.execute(
            query,
            (
                trade["symbol"],
                trade["side"],
                trade["entry_price"],
                trade.get("exit_price"),
                trade["quantity"],
                trade["entry_timestamp"],
                trade.get("exit_timestamp"),
                trade.get("profit_loss"),
                trade["status"],
                trade.get("stop_loss"),
                trade.get("take_profit"),
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def insert_log(self, level: str, message: str) -> None:
        assert self.conn is not None
        query = """
            INSERT INTO bot_logs (created_at, level, message)
            VALUES (?, ?, ?)
        """
        await self.conn.execute(query, (int(datetime.utcnow().timestamp() * 1000), level, message))
        await self.conn.commit()

    async def fetch_recent_ohlcv(self, symbol: str, limit: int = 500) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cursor = await self.conn.execute(
            "SELECT symbol, timestamp, open, high, low, close, volume FROM market_data WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
            (symbol, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def fetch_training_data(self, limit: int = 2000) -> List[Dict[str, Any]]:
        assert self.conn is not None
        cursor = await self.conn.execute(
            "SELECT * FROM market_features ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# helper import used by insert_log
from datetime import datetime
