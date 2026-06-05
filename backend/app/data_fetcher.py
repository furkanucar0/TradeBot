import os
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import ccxt.async_support as ccxt

DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]


class BinanceDataFetcher:
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        timeframe: str = "5m",
        limit: int = 1000,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.timeframe = timeframe
        self.limit = limit
        self.api_key = api_key or os.getenv("BINANCE_API_KEY")
        self.secret = secret or os.getenv("BINANCE_API_SECRET")
        self.exchange: Optional[ccxt.binance] = None

    async def init_exchange(self) -> None:
        if self.exchange is not None:
            return

        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
            "apiKey": self.api_key,
            "secret": self.secret,
        })

    async def close(self) -> None:
        if self.exchange is not None:
            await self.exchange.close()
            self.exchange = None

    async def fetch_ohlcv(
        self, symbol: str, since: Optional[int] = None, limit: Optional[int] = None
    ) -> List[List[Any]]:
        await self.init_exchange()
        if since is None:
            since = int((datetime.utcnow() - timedelta(days=30)).timestamp() * 1000)
        limit = limit or self.limit
        return await self.exchange.fetch_ohlcv(symbol, timeframe=self.timeframe, since=since, limit=limit)

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        await self.init_exchange()
        return await self.exchange.fetch_ticker(symbol)

    async def fetch_and_prepare_all(self) -> Dict[str, List[Dict[str, Any]]]:
        await self.init_exchange()
        tasks = [self.fetch_and_prepare_symbol(symbol) for symbol in self.symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        prepared: Dict[str, List[Dict[str, Any]]] = {}
        for symbol, result in zip(self.symbols, results):
            if isinstance(result, Exception):
                raise result
            prepared[symbol] = result
        return prepared

    async def fetch_and_prepare_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        ohlcv = await self.fetch_ohlcv(symbol)
        return self.prepare_features(symbol, ohlcv)

    def prepare_features(self, symbol: str, ohlcv: List[List[Any]]) -> List[Dict[str, Any]]:
        if len(ohlcv) < 50:
            return []

        timestamps = np.array([row[0] for row in ohlcv], dtype=np.int64)
        opens = np.array([row[1] for row in ohlcv], dtype=np.float64)
        highs = np.array([row[2] for row in ohlcv], dtype=np.float64)
        lows = np.array([row[3] for row in ohlcv], dtype=np.float64)
        closes = np.array([row[4] for row in ohlcv], dtype=np.float64)
        volumes = np.array([row[5] for row in ohlcv], dtype=np.float64)

        rsi = self.compute_rsi(closes, period=14)
        macd_line, macd_signal, macd_hist = self.compute_macd(closes)
        bb_upper, bb_middle, bb_lower, bb_bandwidth = self.compute_bollinger(closes)
        returns_1 = self.compute_returns(closes, period=1)
        returns_5 = self.compute_returns(closes, period=5)

        features: List[Dict[str, Any]] = []
        min_index = max(26, 20, 14)
        horizon = 10
        last_index = len(closes) - horizon

        for i in range(min_index, last_index):
            features.append(
                {
                    "symbol": symbol,
                    "timestamp": int(timestamps[i]),
                    "open": float(opens[i]),
                    "high": float(highs[i]),
                    "low": float(lows[i]),
                    "close": float(closes[i]),
                    "volume": float(volumes[i]),
                    "rsi": float(rsi[i]),
                    "macd_line": float(macd_line[i]),
                    "macd_signal": float(macd_signal[i]),
                    "macd_hist": float(macd_hist[i]),
                    "bb_upper": float(bb_upper[i]),
                    "bb_middle": float(bb_middle[i]),
                    "bb_lower": float(bb_lower[i]),
                    "bb_width": float(bb_bandwidth[i]),
                    "return_1m": float(returns_1[i]),
                    "return_5m": float(returns_5[i]),
                    "close_to_upper": float((closes[i] - bb_upper[i]) / bb_upper[i]) if bb_upper[i] != 0 else 0.0,
                    "close_to_lower": float((closes[i] - bb_lower[i]) / bb_lower[i]) if bb_lower[i] != 0 else 0.0,
                    "future_return_10m": float((closes[i + horizon] / closes[i] - 1.0) * 100.0),
                    "target_profit_1_5": int((closes[i + horizon] / closes[i] - 1.0) * 100.0 >= 1.5),
                }
            )

        return features

    @staticmethod
    def compute_returns(prices: np.ndarray, period: int = 1) -> np.ndarray:
        returns = np.full_like(prices, fill_value=0.0)
        returns[period:] = (prices[period:] / prices[:-period] - 1.0) * 100.0
        return returns

    @staticmethod
    def compute_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.empty_like(prices)
        avg_loss = np.empty_like(prices)
        avg_gain[: period + 1] = np.nan
        avg_loss[: period + 1] = np.nan

        gain = np.mean(gains[:period])
        loss = np.mean(losses[:period])

        for i in range(period, len(prices) - 1):
            gain = (gain * (period - 1) + gains[i]) / period
            loss = (loss * (period - 1) + losses[i]) / period
            avg_gain[i + 1] = gain
            avg_loss[i + 1] = loss

        rs = np.divide(avg_gain, avg_loss, out=np.full_like(avg_gain, np.nan), where=avg_loss != 0)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi[: period + 1] = np.nan
        return rsi

    @staticmethod
    def exponential_moving_average(values: np.ndarray, span: int) -> np.ndarray:
        ema = np.empty_like(values)
        alpha = 2.0 / (span + 1.0)
        ema[0] = values[0]
        for i in range(1, len(values)):
            ema[i] = alpha * values[i] + (1.0 - alpha) * ema[i - 1]
        return ema

    def compute_macd(
        self, prices: np.ndarray, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        ema_fast = self.exponential_moving_average(prices, fast_period)
        ema_slow = self.exponential_moving_average(prices, slow_period)
        macd_line = ema_fast - ema_slow
        signal_line = self.exponential_moving_average(macd_line, signal_period)
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    @staticmethod
    def compute_bollinger(prices: np.ndarray, period: int = 20, multiplier: float = 2.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        middle = np.full_like(prices, fill_value=np.nan)
        upper = np.full_like(prices, fill_value=np.nan)
        lower = np.full_like(prices, fill_value=np.nan)
        bandwidth = np.full_like(prices, fill_value=np.nan)

        for i in range(period - 1, len(prices)):
            window = prices[i - period + 1 : i + 1]
            mean = np.mean(window)
            std = np.std(window)
            upper[i] = mean + multiplier * std
            lower[i] = mean - multiplier * std
            middle[i] = mean
            bandwidth[i] = ((upper[i] - lower[i]) / mean) if mean != 0 else 0.0

        return upper, middle, lower, bandwidth


async def main() -> None:
    fetcher = BinanceDataFetcher()
    try:
        prepared = await fetcher.fetch_and_prepare_all()
        for symbol, rows in prepared.items():
            print(f"{symbol}: {len(rows)} feature rows hazır")
    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())
