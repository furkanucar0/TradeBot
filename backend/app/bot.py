import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .ai_engine import AIEngine
from .config import BotConfig
from .data_fetcher import BinanceDataFetcher
from .database import Database
from .execution_engine import ExecutionEngine

logger = logging.getLogger("tradebot.bot")

UpdateCallback = Callable[[Dict[str, Any]], Awaitable[None]]


class BotCoordinator:
    def __init__(
        self,
        config: BotConfig,
        database: Database,
        fetcher: BinanceDataFetcher,
        ai_engine: AIEngine,
        execution_engine: ExecutionEngine,
    ) -> None:
        self.config = config
        self.database = database
        self.fetcher = fetcher
        self.ai_engine = ai_engine
        self.execution_engine = execution_engine
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self.last_cycle: Optional[int] = None
        self.last_retrain: Optional[datetime] = None
        self.update_listeners: List[UpdateCallback] = []

    def add_listener(self, callback: UpdateCallback) -> None:
        self.update_listeners.append(callback)

    async def _notify_update(self, payload: Dict[str, Any]) -> None:
        if not self.update_listeners:
            return
        await asyncio.gather(*(listener(payload) for listener in self.update_listeners), return_exceptions=True)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("BotCoordinator started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("BotCoordinator stopped")

    async def _run_loop(self) -> None:
        while self._running:
            self.last_cycle = int(datetime.utcnow().timestamp() * 1000)
            logger.info("Starting bot cycle")
            try:
                await self.perform_cycle()
            except Exception as error:
                await self.database.insert_log("error", f"Bot cycle error: {error}")
                logger.error("Bot cycle error: %s", error)
            logger.info("Bot cycle completed")
            await asyncio.sleep(self.config.loop_interval_seconds)

    async def perform_cycle(self) -> None:
        raw_data = await self._fetch_latest_ohlcv()
        latest_prices = {symbol: data["close"] for symbol, data in raw_data.items()}

        await self._persist_latest_ohlcv(raw_data)
        messages = await self._predict_and_trade(raw_data, latest_prices)

        if self._is_time_to_retrain():
            await self._retrain_model()

        payload = {
            "timestamp": self.last_cycle,
            "open_positions": len(self.execution_engine.get_open_positions()),
            "closed_positions": len(self.execution_engine.get_closed_positions()),
            "unrealized_pnl": self.execution_engine.get_total_unrealized_pnl(latest_prices),
            "realized_pnl": self.execution_engine.get_total_realized_pnl(),
            "model_loaded": self.ai_engine.model is not None,
            "messages": messages[-10:],
        }
        await self._notify_update(payload)

    async def _fetch_latest_ohlcv(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for symbol in self.config.symbol_list:
            ohlcv = await self.fetcher.fetch_ohlcv(symbol, limit=2)
            if not ohlcv:
                continue
            latest = ohlcv[-1]
            result[symbol] = {
                "symbol": symbol,
                "timestamp": int(latest[0]),
                "open": float(latest[1]),
                "high": float(latest[2]),
                "low": float(latest[3]),
                "close": float(latest[4]),
                "volume": float(latest[5]),
            }
        return result

    async def _persist_latest_ohlcv(self, raw_data: Dict[str, Dict[str, Any]]) -> None:
        for symbol, candle in raw_data.items():
            await self.database.insert_ohlcv(symbol, [candle])

    async def _predict_and_trade(self, raw_data: Dict[str, Dict[str, Any]], latest_prices: Dict[str, float]) -> List[str]:
        events: List[str] = []
        if self.ai_engine.model is None:
            events.append("Model not loaded; skipping trade evaluation.")
            logger.warning("Skipping trade evaluation because model is not loaded")
            return events

        for symbol in self.config.symbol_list:
            ohlcv = await self.fetcher.fetch_ohlcv(symbol, limit=50)
            feature_rows = self.fetcher.prepare_features(symbol, ohlcv)
            if not feature_rows:
                events.append(f"Not enough history for {symbol}; skipping.")
                continue
            latest_feature = feature_rows[-1]
            prediction = self.ai_engine.predict(latest_feature)

            events.append(
                f"Signal {symbol}: prob={prediction['probability']:.2f}, predicted={prediction['prediction']}"
            )

            if prediction["probability"] >= self.config.signal_threshold and self.execution_engine.can_open_new_position():
                position = self.execution_engine.open_position(
                    symbol=symbol,
                    side="long",
                    entry_price=latest_feature["close"],
                    quantity=self.config.paper_trade_size,
                    timestamp=int(datetime.utcnow().timestamp() * 1000),
                )
                await self.database.insert_log(
                    "info",
                    f"Open paper trade for {symbol} at {latest_feature['close']} with prob={prediction['probability']:.2f}",
                )
                events.append(
                    f"Opened paper trade {position.symbol} @ {position.entry_price:.2f} size={position.quantity}"
                )
                logger.info("Opened paper trade: %s @ %s", position.symbol, position.entry_price)

        closed = self.execution_engine.update_positions(latest_prices)
        for position in closed:
            await self.database.insert_trade(
                {
                    "symbol": position.symbol,
                    "side": position.side,
                    "entry_price": position.entry_price,
                    "exit_price": position.exit_price,
                    "quantity": position.quantity,
                    "entry_timestamp": position.entry_timestamp,
                    "exit_timestamp": position.exit_timestamp,
                    "profit_loss": position.profit_loss,
                    "status": position.status,
                    "stop_loss": position.stop_loss,
                    "take_profit": position.take_profit,
                }
            )
            events.append(
                f"Closed {position.symbol}: pnl={position.profit_loss:.8f}, status={position.status}"
            )
            logger.info("Closed paper trade: %s pnl=%s", position.symbol, position.profit_loss)

        if not events:
            events.append("Trade evaluation cycle completed with no actions.")

        return events

    def _is_time_to_retrain(self) -> bool:
        if self.last_retrain is None:
            return True
        return datetime.utcnow() - self.last_retrain >= timedelta(hours=self.config.retrain_interval_hours)

    async def _retrain_model(self) -> None:
        feature_rows = await self.database.fetch_training_data(limit=2000)
        if not feature_rows:
            return
        try:
            result = self.ai_engine.retrain(feature_rows, model_type="xgboost")
            self.last_retrain = datetime.utcnow()
            await self.database.insert_log(
                "info",
                f"Model retrained: accuracy={result['accuracy']:.4f}, train_rows={result['train_rows']}",
            )
        except Exception as error:
            await self.database.insert_log("error", f"Retrain failed: {error}")
            logger.error("Retrain failed: %s", error)

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self._running,
            "open_positions": len(self.execution_engine.get_open_positions()),
            "closed_positions": len(self.execution_engine.get_closed_positions()),
            "last_cycle": self.last_cycle,
            "model_loaded": self.ai_engine.model is not None,
            "symbol_watchlist": self.config.symbol_list,
        }
