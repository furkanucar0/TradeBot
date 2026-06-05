from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class PositionSchema(BaseModel):
    symbol: str
    side: str
    entry_price: float
    quantity: float
    entry_timestamp: int
    stop_loss: float
    take_profit: float
    status: str
    exit_price: Optional[float]
    exit_timestamp: Optional[int]
    profit_loss: Optional[float]


class TradeRecordSchema(BaseModel):
    id: int
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    entry_timestamp: int
    exit_timestamp: Optional[int]
    profit_loss: Optional[float]
    status: str
    stop_loss: Optional[float]
    take_profit: Optional[float]

    class Config:
        orm_mode = True


class BotStatusSchema(BaseModel):
    is_running: bool
    open_positions: int
    closed_trades: int
    last_cycle: Optional[int]
    model_loaded: bool
    symbol_watchlist: List[str]


class PredictionRequest(BaseModel):
    feature_row: dict


class PredictionResponse(BaseModel):
    symbol: str
    probability: float
    prediction: int
    model_type: str
    timestamp: int
