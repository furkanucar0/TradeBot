import os
import pickle
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split


DEFAULT_FEATURE_COLUMNS = [
    "rsi",
    "macd_line",
    "macd_signal",
    "macd_hist",
    "bb_upper",
    "bb_middle",
    "bb_lower",
    "bb_width",
    "return_1m",
    "return_5m",
    "close_to_upper",
    "close_to_lower",
]


class AIEngine:
    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self.model: Optional[Any] = None
        self.model_type: str = "unknown"
        self.feature_columns = DEFAULT_FEATURE_COLUMNS

    def _create_model(self, model_type: str = "xgboost") -> Any:
        if model_type == "xgboost":
            try:
                import xgboost as xgb

                return xgb.XGBClassifier(use_label_encoder=False, eval_metric="logloss", n_estimators=100)
            except ImportError as error:
                raise ImportError("xgboost is required for XGBoost model training") from error

        if model_type == "lightgbm":
            try:
                import lightgbm as lgb

                return lgb.LGBMClassifier(n_estimators=100)
            except ImportError as error:
                raise ImportError("lightgbm is required for LightGBM model training") from error

        raise ValueError("Unsupported model_type. Choose 'xgboost' or 'lightgbm'.")

    def _extract_xy(self, feature_rows: Iterable[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        records = [row for row in feature_rows if row.get("target_profit_1_5") is not None]
        if not records:
            raise ValueError("No training rows with target labels found.")

        x = np.array([[float(row.get(k, 0.0)) for k in self.feature_columns] for row in records], dtype=np.float32)
        y = np.array([int(row["target_profit_1_5"]) for row in records], dtype=np.int32)
        return x, y

    def save_model(self) -> None:
        if self.model is None:
            raise ValueError("No model available to save.")
        os.makedirs(os.path.dirname(self.model_path) or ".", exist_ok=True)
        with open(self.model_path, "wb") as model_file:
            pickle.dump({"model": self.model, "model_type": self.model_type, "feature_columns": self.feature_columns}, model_file)

    def load_model(self) -> None:
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model file not found at {self.model_path}")
        with open(self.model_path, "rb") as model_file:
            payload = pickle.load(model_file)
        self.model = payload["model"]
        self.model_type = payload.get("model_type", "unknown")
        self.feature_columns = payload.get("feature_columns", DEFAULT_FEATURE_COLUMNS)

    def train_model(
        self,
        feature_rows: Iterable[Dict[str, Any]],
        model_type: str = "xgboost",
        test_size: float = 0.2,
        random_state: int = 42,
    ) -> Dict[str, Any]:
        x, y = self._extract_xy(feature_rows)
        model = self._create_model(model_type)

        x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=test_size, random_state=random_state, stratify=y)
        model.fit(x_train, y_train)

        predictions = model.predict(x_test)
        accuracy = float(accuracy_score(y_test, predictions))

        self.model = model
        self.model_type = model_type
        self.save_model()

        return {
            "model_type": model_type,
            "train_rows": len(x_train),
            "test_rows": len(x_test),
            "accuracy": accuracy,
            "trained_at": int(datetime.utcnow().timestamp() * 1000),
        }

    def predict(self, feature_row: Dict[str, Any]) -> Dict[str, Any]:
        if self.model is None:
            raise ValueError("Model is not loaded. Call load_model or train_model first.")

        x = np.array([[float(feature_row.get(k, 0.0)) for k in self.feature_columns]], dtype=np.float32)
        prediction = int(self.model.predict(x)[0])
        probability = float(self.model.predict_proba(x)[0][1]) if hasattr(self.model, "predict_proba") else float(self.model.predict(x)[0])

        return {
            "symbol": feature_row["symbol"],
            "timestamp": int(feature_row["timestamp"]),
            "prediction": prediction,
            "probability": probability,
            "model_type": self.model_type,
        }

    def retrain(self, feature_rows: Iterable[Dict[str, Any]], model_type: str = "xgboost") -> Dict[str, Any]:
        return self.train_model(feature_rows, model_type=model_type)
