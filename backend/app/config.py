import os
from typing import List


class BotConfig:
    def __init__(self) -> None:
        self.database_path = os.getenv("DATABASE_PATH", "./backend/bot.sqlite")
        self.model_path = os.getenv("MODEL_PATH", "./backend/model.bin")
        self.timeframe = os.getenv("TIMEFRAME", "5m")
        self.symbols = os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT").split(",")
        self.max_positions = int(os.getenv("MAX_POSITIONS", "5"))
        self.target_profit_pct = float(os.getenv("TARGET_PROFIT_PCT", "1.5"))
        self.stop_loss_pct = float(os.getenv("STOP_LOSS_PCT", "1.0"))
        self.signal_threshold = float(os.getenv("SIGNAL_THRESHOLD", "0.65"))
        self.retrain_interval_hours = int(os.getenv("RETRAIN_INTERVAL_HOURS", "24"))
        self.loop_interval_seconds = int(os.getenv("LOOP_INTERVAL_SECONDS", "30"))
        self.paper_trade_size = float(os.getenv("PAPER_TRADE_SIZE", "0.001"))

    @property
    def symbol_list(self) -> List[str]:
        return [symbol.strip() for symbol in self.symbols if symbol.strip()]
