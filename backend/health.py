"""
CTOS FAZ 2 — Sağlık Katmanı (K-18).
Botun içsel sağlığını 0-100 skorda toplar; live_trader periyodik olarak
hesaplayıp "health" eventi olarak yayınlar (dashboard + /health + Telegram).

Skor SADECE gözlemdir — işlem kararlarına karışmaz (o iş RiskGate'in, FAZ 3).
Bileşenler ve ağırlıklar config.HEALTH_WEIGHTS'te.
"""
import time
from typing import Any, Dict, List, Optional

from config import (
    DAILY_LOSS_LIMIT_PCT, DAILY_PROFIT_LOCK_PCT,
    HEALTH_DD_FLOOR, HEALTH_STALE_S, HEALTH_STREAK_FLOOR, HEALTH_WEIGHTS,
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_health(
    *,
    balance: float,
    peak_balance: float,
    day_start_balance: float,
    realized_pnl_today: float,
    trades: List[Dict[str, Any]],       # demo_trades: [{"result": "TP"/"SL"/..., "pnl": ...}]
    breakeven_wr: float,                # aktif SL/TP kombosunun maliyet dahil başabaşı
    last_feed_ts: float,                # son başarılı fiyat güncellemesi (epoch sn)
    daily_paused: bool = False,
    open_positions: int = 0,
) -> Dict[str, Any]:
    """0-100 sağlık skoru + bileşen dökümü döner."""
    now = time.time()
    comp: Dict[str, Dict[str, Any]] = {}

    # ── 1. Drawdown (zirveden düşüş) ─────────────────────────────────────────
    dd = (peak_balance - balance) / peak_balance if peak_balance > 0 else 0.0
    dd_score = _clamp01(1.0 - dd / HEALTH_DD_FLOOR)
    comp["drawdown"] = {"score": dd_score, "value": round(dd * 100, 2), "label": f"DD %{dd*100:.1f}"}

    # ── 2. Ardışık kayıp serisi ──────────────────────────────────────────────
    streak = 0
    for t in reversed(trades):
        if t.get("result") == "SL":
            streak += 1
        else:
            break
    st_score = _clamp01(1.0 - streak / HEALTH_STREAK_FLOOR)
    comp["streak"] = {"score": st_score, "value": streak, "label": f"{streak} ardışık SL"}

    # ── 3. Günlük PnL'in fren bandındaki yeri ────────────────────────────────
    day_ret = realized_pnl_today / day_start_balance if day_start_balance > 0 else 0.0
    # -1.5% → 0 puan, 0% → 0.75 puan, +2% → 1.0 puan (kâr kilidi sağlıklıdır)
    if day_ret >= 0:
        dp_score = _clamp01(0.75 + 0.25 * day_ret / DAILY_PROFIT_LOCK_PCT)
    else:
        dp_score = _clamp01(0.75 * (1.0 - day_ret / DAILY_LOSS_LIMIT_PCT))
    comp["daily_pnl"] = {"score": dp_score, "value": round(day_ret * 100, 2), "label": f"Gün %{day_ret*100:+.2f}"}

    # ── 4. WR trendi (son 20 işlem vs başabaş) ───────────────────────────────
    recent = trades[-20:]
    if len(recent) >= 5:
        wr = sum(1 for t in recent if t.get("result") == "TP") / len(recent)
        # başabaşın 10 puan altı → 0; başabaş → 0.5; +15 puan üstü → 1.0
        wr_score = _clamp01(0.5 + (wr - breakeven_wr) / 0.30)
        wr_label = f"WR %{wr*100:.0f}/{len(recent)}"
    else:
        wr, wr_score, wr_label = None, 0.6, f"veri az ({len(recent)} işlem)"
    comp["wr_trend"] = {"score": wr_score, "value": round(wr * 100, 1) if wr is not None else None, "label": wr_label}

    # ── 5. Veri tazeliği ─────────────────────────────────────────────────────
    age = now - last_feed_ts if last_feed_ts > 0 else HEALTH_STALE_S
    df_score = _clamp01(1.0 - age / HEALTH_STALE_S)
    comp["data_fresh"] = {"score": df_score, "value": round(age, 1), "label": f"veri {age:.0f} sn önce"}

    # ── Toplam ───────────────────────────────────────────────────────────────
    total = sum(HEALTH_WEIGHTS[k] * comp[k]["score"] for k in HEALTH_WEIGHTS)
    score = int(round(total))
    status = "SAĞLIKLI" if score >= 75 else ("DİKKAT" if score >= 50 else "KRİTİK")

    return {
        "score": score,
        "status": status,
        "components": {
            k: {
                "weight": HEALTH_WEIGHTS[k],
                "points": round(HEALTH_WEIGHTS[k] * comp[k]["score"], 1),
                "label": comp[k]["label"],
            }
            for k in HEALTH_WEIGHTS
        },
        "balance": round(balance, 2),
        "open_positions": open_positions,
        "daily_paused": daily_paused,
        "ts": now,
    }
