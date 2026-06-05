import asyncio
import logging
from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tradebot.api")

from .ai_engine import AIEngine
from .bot import BotCoordinator
from .config import BotConfig
from .data_fetcher import BinanceDataFetcher
from .database import Database
from .execution_engine import ExecutionEngine
from .schemas import BotStatusSchema, TradeRecordSchema


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        if not self.active_connections:
            return
        await asyncio.gather(*(ws.send_json(message) for ws in self.active_connections), return_exceptions=True)


app = FastAPI(title="Crypto Scalping Bot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Initializing backend services...")
    config = BotConfig()
    app.state.config = config
    app.state.db = Database(config.database_path)
    await app.state.db.connect()
    app.state.fetcher = BinanceDataFetcher(symbols=config.symbol_list, timeframe=config.timeframe)
    app.state.ai_engine = AIEngine(config.model_path)
    app.state.execution_engine = ExecutionEngine(
        max_positions=config.max_positions,
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.target_profit_pct,
    )
    app.state.coordinator = BotCoordinator(
        config=config,
        database=app.state.db,
        fetcher=app.state.fetcher,
        ai_engine=app.state.ai_engine,
        execution_engine=app.state.execution_engine,
    )
    app.state.coordinator.add_listener(manager.broadcast)

    try:
        app.state.ai_engine.load_model()
        logger.info("AI model loaded successfully")
    except FileNotFoundError:
        await app.state.db.insert_log("warning", "Model file not found on startup, training required.")
        logger.warning("AI model file not found on startup; training required")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if hasattr(app.state, "coordinator"):
        await app.state.coordinator.stop()
    if hasattr(app.state, "fetcher"):
        await app.state.fetcher.close()
    if hasattr(app.state, "db"):
        await app.state.db.close()


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/bot/start")
async def start_bot() -> Dict[str, str]:
    await app.state.coordinator.start()
    logger.info("Bot coordinator started")
    return {"status": "started"}


@app.post("/bot/stop")
async def stop_bot() -> Dict[str, str]:
    await app.state.coordinator.stop()
    logger.info("Bot coordinator stopped")
    return {"status": "stopped"}


@app.get("/bot/status", response_model=BotStatusSchema)
async def bot_status() -> Any:
    return app.state.coordinator.get_status()


@app.get("/positions")
async def get_positions() -> Dict[str, Any]:
    return {
        "open_positions": [position.__dict__ for position in app.state.execution_engine.get_open_positions()],
        "closed_positions": [position.__dict__ for position in app.state.execution_engine.get_closed_positions()],
    }


@app.get("/trades")
async def get_trades() -> List[TradeRecordSchema]:
    cursor = await app.state.db.conn.execute("SELECT * FROM trade_history ORDER BY entry_timestamp DESC LIMIT 100")
    rows = await cursor.fetchall()
    return [TradeRecordSchema(**dict(row)) for row in rows]


@app.websocket("/ws/updates")
async def websocket_updates(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
