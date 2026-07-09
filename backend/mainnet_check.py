"""
CTOS FAZ 7 — Mainnet Geçiş Protokolü (K-23).
"Paper'a sabır" ilkesinin resmileşmesi: paper kanıtı 8 maddelik kontrol
listesinden geçmeden gerçek para açılamaz. api.py /bot/start(testnet=false)
bu kapıyı ZORUNLU uygular; Telegram /canli → /canli_onay iki adımlı onay ister.

Kanıt tabanı: trades tablosundaki kapanmış paper işlemler (yalnız TP/SL
çıkışlılar — MANUAL/BOT_RESTART strateji kanıtı sayılmaz). Equity ve günlük
yüzdeler DEMO_START_BALANCE (100) tabanına göre hesaplanır; demo kasa
restart'ta sıfırlansa da DB kayıtları kümülatif kanıt olarak birikir.
"""
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from config import (
    DEMO_START_BALANCE, FEE_RATE, MAINNET_MAX_DD, MAINNET_MIN_DAYS,
    MAINNET_MIN_TRADES, MAINNET_WORST_DAY_PCT, SLIPPAGE_RATE,
)
from database import get_database_path
import risk_gate

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def _wilson_lb(wins: int, n: int, z: float = 1.96) -> float:
    """Win rate'in %95 güven alt sınırı (Wilson). Küçük örneklemde WR'ın
    şansa borçlu olup olmadığını ayırt eder — 10 işlemde %60 geçmez,
    100 işlemde %60 geçebilir."""
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - adj) / denom)


def evaluate() -> Dict[str, Any]:
    """8 maddelik kontrol listesi + istatistikler. ready=True → tüm maddeler ✓."""
    conn = sqlite3.connect(str(get_database_path()))
    rows = conn.execute(
        "SELECT entry_ts, exit_ts, exit_reason, pnl_usdt FROM trades "
        "WHERE paper=1 AND status='closed' AND exit_reason IN ('TP','SL') "
        "ORDER BY exit_ts"
    ).fetchall()
    conn.close()

    n     = len(rows)
    wins  = sum(1 for r in rows if r[2] == "TP")
    wr    = wins / n if n else 0.0
    wr_lb = _wilson_lb(wins, n)
    total_pnl = sum(r[3] or 0.0 for r in rows)

    # Kanıt süresi: ilk girişten son çıkışa
    days = 0.0
    if n:
        days = max(0.0, ((rows[-1][1] or rows[-1][0]) - rows[0][0]) / 86_400_000)

    # Equity eğrisi (100 tabanlı) → maks. drawdown
    equity, peak, max_dd = DEMO_START_BALANCE, DEMO_START_BALANCE, 0.0
    daily: Dict[str, float] = {}
    for r in rows:
        equity += (r[3] or 0.0)
        peak    = max(peak, equity)
        max_dd  = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)
        day = time.strftime("%Y-%m-%d", time.gmtime((r[1] or r[0]) / 1000))
        daily[day] = daily.get(day, 0.0) + (r[3] or 0.0)
    worst_day_pct = min((v / DEMO_START_BALANCE for v in daily.values()), default=0.0)

    # Görevdeki modelin başabaş WR'ı + backtest kilidi (tek doğruluk kaynağı: summary)
    summary: Dict[str, Any] = {}
    p = REPORTS_DIR / "backtest_summary.json"
    if p.exists():
        try:
            summary = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    sl_pct = float(summary.get("sl_pct", 0.005))
    tp_pct = float(summary.get("tp_pct", 0.010))
    cost   = FEE_RATE * 2 + SLIPPAGE_RATE
    breakeven_wr = (sl_pct + cost) / ((tp_pct - cost) + (sl_pct + cost))
    ready_for_live = bool(summary.get("ready_for_live", False))
    panic = risk_gate.panic_active()

    def _c(name: str, ok: bool, value: str, target: str) -> Dict[str, Any]:
        return {"name": name, "ok": bool(ok), "value": value, "target": target}

    checks: List[Dict[str, Any]] = [
        _c("İşlem sayısı", n >= MAINNET_MIN_TRADES,
           f"{n}", f"≥ {MAINNET_MIN_TRADES}"),
        _c("Kanıt süresi", days >= MAINNET_MIN_DAYS,
           f"{days:.1f} gün", f"≥ {MAINNET_MIN_DAYS} gün"),
        _c("WR %95 alt sınırı ≥ başabaş", wr_lb >= breakeven_wr and n > 0,
           f"%{wr_lb*100:.1f} (WR %{wr*100:.1f})", f"≥ %{breakeven_wr*100:.1f}"),
        _c("Toplam paper PnL", total_pnl > 0,
           f"{total_pnl:+.2f} USDT", "> 0"),
        _c("Paper MaxDD", max_dd <= MAINNET_MAX_DD,
           f"%{max_dd*100:.1f}", f"≤ %{MAINNET_MAX_DD*100:.0f}"),
        _c("En kötü gün", worst_day_pct >= MAINNET_WORST_DAY_PCT,
           f"%{worst_day_pct*100:+.2f}", f"≥ %{MAINNET_WORST_DAY_PCT*100:.0f}"),
        _c("Backtest kilidi (ready_for_live)", ready_for_live,
           "✓" if ready_for_live else "✗", "✓"),
        _c("Panik kilidi kapalı", not panic,
           "kapalı" if not panic else "AÇIK", "kapalı"),
    ]

    return {
        "ready": all(c["ok"] for c in checks),
        "checks": checks,
        "stats": {
            "trades": n, "wins": wins, "win_rate": round(wr, 4),
            "wr_lower_bound": round(wr_lb, 4),
            "breakeven_wr": round(breakeven_wr, 4),
            "total_pnl": round(total_pnl, 4),
            "days": round(days, 1),
            "max_dd": round(max_dd, 4),
            "worst_day_pct": round(worst_day_pct * 100, 2),
            "sl_pct": sl_pct, "tp_pct": tp_pct,
        },
        "ts": time.time(),
    }
