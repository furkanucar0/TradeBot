from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Position:
    symbol: str
    side: str
    entry_price: float
    quantity: float
    entry_timestamp: int
    stop_loss: float
    take_profit: float
    status: str = "open"
    exit_price: Optional[float] = None
    exit_timestamp: Optional[int] = None
    profit_loss: Optional[float] = None


class ExecutionEngine:
    def __init__(
        self,
        max_positions: int = 5,
        stop_loss_pct: float = 1.0,
        take_profit_pct: float = 1.5,
    ) -> None:
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.open_positions: List[Position] = []
        self.closed_positions: List[Position] = []

    def can_open_new_position(self) -> bool:
        return len(self.open_positions) < self.max_positions

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        timestamp: int,
    ) -> Position:
        if not self.can_open_new_position():
            raise RuntimeError("Maximum open position limit reached")

        take_profit = round(entry_price * (1 + self.take_profit_pct / 100.0), 8)
        stop_loss = round(entry_price * (1 - self.stop_loss_pct / 100.0), 8)

        position = Position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            entry_timestamp=timestamp,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        self.open_positions.append(position)
        return position

    def update_positions(self, latest_prices: Dict[str, float]) -> List[Position]:
        closed: List[Position] = []
        now_ts = int(datetime.utcnow().timestamp() * 1000)

        for position in list(self.open_positions):
            current_price = latest_prices.get(position.symbol)
            if current_price is None:
                continue

            if position.side == "long":
                if current_price >= position.take_profit or current_price <= position.stop_loss:
                    position.exit_price = current_price
                    position.exit_timestamp = now_ts
                    position.profit_loss = round((current_price - position.entry_price) * position.quantity, 8)
                    position.status = "closed"
                    self.open_positions.remove(position)
                    self.closed_positions.append(position)
                    closed.append(position)
            else:
                if current_price <= position.take_profit or current_price >= position.stop_loss:
                    position.exit_price = current_price
                    position.exit_timestamp = now_ts
                    position.profit_loss = round((position.entry_price - current_price) * position.quantity, 8)
                    position.status = "closed"
                    self.open_positions.remove(position)
                    self.closed_positions.append(position)
                    closed.append(position)

        return closed

    def get_open_positions(self) -> List[Position]:
        return list(self.open_positions)

    def get_closed_positions(self) -> List[Position]:
        return list(self.closed_positions)

    def get_total_unrealized_pnl(self, latest_prices: Dict[str, float]) -> float:
        total = 0.0
        for position in self.open_positions:
            current_price = latest_prices.get(position.symbol)
            if current_price is None:
                continue
            total += (current_price - position.entry_price) * position.quantity if position.side == "long" else (position.entry_price - current_price) * position.quantity
        return round(total, 8)

    def get_total_realized_pnl(self) -> float:
        return round(sum((position.profit_loss or 0.0) for position in self.closed_positions), 8)
