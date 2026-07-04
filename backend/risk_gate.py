"""
CTOS FAZ 3 — Risk Duvarı (K-19).
Eskiden live_trader'da dağınık duran TÜM işlem-öncesi vetolar tek sınıfta:
ADX ranging, trend vetosu (güven ölçekli delme dahil), emir defteri,
çift-yön çözümü, pozisyon kapasitesi + YENİ: panik kilidi ve sağlık
duraklatması. Davranış birebir korunmuştur; mimari tekilleşmiştir.

FAZ 4 (K-20): her karar yapılandırılmış gerekçe (reason code) ile döner —
"decision" eventi + decisions tablosu bunu tüketir.

Karar yetkisi SADECE burada. health.py gözlemler, RiskGate karar verir.
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import (
    ADX_RANGING_FLOOR, HEALTH_PAUSE_SCORE, HEALTH_RESUME_SCORE,
    OB_IMBALANCE_LIMIT, TREND_VETO_MARGIN,
)

# ── Panik kilidi (kill switch) ────────────────────────────────────────────────
# Dosya tabanlı: restart'a dayanır — "elle kurma şartı" ancak /panik_kaldir
# (veya dosyayı silmek) ile kalkar. Bot çalışırken de her döngüde kontrol edilir.
PANIC_FILE = Path(__file__).resolve().parent / "panic.lock"


def panic_active() -> bool:
    return PANIC_FILE.exists()


def panic_engage(reason: str = "manual") -> None:
    PANIC_FILE.write_text(
        json.dumps({"ts": time.time(), "reason": reason}, ensure_ascii=False),
        encoding="utf-8",
    )


def panic_clear() -> None:
    try:
        PANIC_FILE.unlink()
    except FileNotFoundError:
        pass


def panic_info() -> Optional[Dict[str, Any]]:
    if not PANIC_FILE.exists():
        return None
    try:
        return json.loads(PANIC_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"ts": None, "reason": "?"}


# ── Reason kodları (FAZ 4 — K-20) ─────────────────────────────────────────────
REASON_LABELS = {
    "PANIC":          "Panik kilidi aktif",
    "MODEL_UPDATING": "Model güncelleniyor",
    "DAILY_BRAKE":    "Günlük fren devrede",
    "HEALTH_PAUSE":   "Sağlık skoru düşük",
    "BUFFER_SHORT":   "Mum buffer'ı dolmadı",
    "NO_PRICE":       "Anlık fiyat yok",
    "NO_FEATURES":    "Özellikler hesaplanamadı",
    "NO_SIGNAL":      "Sinyal yok (eşik altı)",
    "ADX_RANGING":    "1h ADX düşük — yönsüz piyasa",
    "TREND_VETO":     "1h trend aleyhte",
    "OB_IMBALANCE":   "Emir defteri aleyhte",
    "MAX_POSITIONS":  "Maks. pozisyon dolu",
}


class RiskGate:
    """Tek veto noktası. evaluate() sinyal başına; global_block() döngü başına."""

    def __init__(self) -> None:
        self.health_paused = False
        self.last_health_score: Optional[int] = None

    # ── Sağlık duraklatması (histerezisli) ───────────────────────────────────
    def update_health(self, score: int) -> Optional[str]:
        """Skor değişimini işler; durum değiştiyse 'paused'/'resumed' döner."""
        self.last_health_score = score
        if not self.health_paused and score < HEALTH_PAUSE_SCORE:
            self.health_paused = True
            return "paused"
        if self.health_paused and score >= HEALTH_RESUME_SCORE:
            self.health_paused = False
            return "resumed"
        return None

    # ── Döngü seviyesi bloklar ───────────────────────────────────────────────
    def global_block(self, model_updating: bool, daily_paused: bool) -> Optional[str]:
        if panic_active():
            return "PANIC"
        if model_updating:
            return "MODEL_UPDATING"
        if daily_paused:
            return "DAILY_BRAKE"
        if self.health_paused:
            return "HEALTH_PAUSE"
        return None

    # ── Sinyal seviyesi değerlendirme ────────────────────────────────────────
    def evaluate(
        self,
        *,
        sym: str,
        features: Dict[str, float],
        pred_long: int, proba_long: float,
        pred_short: int, proba_short: float,
        thr_long_eff: float, thr_short_eff: float,
        ob_imbalance: float,
        open_count: int,
        max_positions: int,
    ) -> Dict[str, Any]:
        """
        Döner: {allowed, direction, proba, threshold, blocked_by, ob_blocked,
                emit_signal, pred_long, pred_short, logs, detail}
        Kontrol sırası live_trader'ın eski davranışıyla BİREBİR aynıdır:
        ADX → trend vetosu → emir defteri → çift-yön çözümü → kapasite.
        """
        logs: List[str] = []
        adx       = features.get("h1_adx", 25.0)
        ema_cross = features.get("h1_ema_cross", 0.0)
        raw_long, raw_short = pred_long, pred_short
        detail: Dict[str, Any] = {
            "proba_long":  round(proba_long, 4),
            "proba_short": round(proba_short, 4),
            "thr_long":    round(thr_long_eff, 4),
            "thr_short":   round(thr_short_eff, 4),
            "ob":          round(ob_imbalance, 3),
            "adx":         round(adx, 1),
        }

        def _result(allowed, direction, proba, threshold, blocked_by,
                    ob_blocked=False, emit_signal=True):
            return {
                "allowed":     allowed,
                "direction":   direction,
                "proba":       proba,
                "threshold":   threshold,
                "blocked_by":  blocked_by,
                "ob_blocked":  ob_blocked,
                "emit_signal": emit_signal,
                "pred_long":   pred_long,
                "pred_short":  pred_short,
                "logs":        logs,
                "detail":      detail,
            }

        # 1) ADX ranging — tüm sinyaller durur (eski davranış: signal eventi de yok)
        if adx < ADX_RANGING_FLOOR:
            logs.append(f"{sym} 1h ADX={adx:.1f} < {ADX_RANGING_FLOOR} (ranging) — sinyal atlandı")
            pred_long = pred_short = 0
            return _result(False, None, max(proba_long, proba_short), None,
                           "ADX_RANGING", emit_signal=False)

        block_l: Optional[str] = None
        block_s: Optional[str] = None

        # 2) Trend vetosu — güven ölçekli (K-11): eşiği TREND_VETO_MARGIN kadar
        #    aşan güçlü sinyaller vetoyu deler
        if pred_long == 1 and ema_cross < 0:
            if proba_long >= thr_long_eff + TREND_VETO_MARGIN:
                logs.append(f"{sym} LONG karşı-trend ama sinyal çok güçlü (p={proba_long:.2f}) — veto delindi")
            else:
                logs.append(f"{sym} LONG sinyali var ancak 1h trendi bearish — atlandı")
                pred_long, block_l = 0, "TREND_VETO"
        if pred_short == 1 and ema_cross > 0:
            if proba_short >= thr_short_eff + TREND_VETO_MARGIN:
                logs.append(f"{sym} SHORT karşı-trend ama sinyal çok güçlü (p={proba_short:.2f}) — veto delindi")
            else:
                logs.append(f"{sym} SHORT sinyali var ancak 1h trendi bullish — atlandı")
                pred_short, block_s = 0, "TREND_VETO"

        # 3) Emir defteri dengesizliği
        ob_blocked = False
        if pred_long == 1 and ob_imbalance < -OB_IMBALANCE_LIMIT:
            pred_long, block_l, ob_blocked = 0, "OB_IMBALANCE", True
        if pred_short == 1 and ob_imbalance > OB_IMBALANCE_LIMIT:
            pred_short, block_s, ob_blocked = 0, "OB_IMBALANCE", True

        # 4) Her iki yön ateşlendiyse güçlü olan kalır
        if pred_long == 1 and pred_short == 1:
            if proba_long >= proba_short:
                pred_short = 0
            else:
                pred_long = 0

        # 5) Yön + kapasite
        if pred_long == 1:
            direction, proba, threshold = "LONG", proba_long, thr_long_eff
        elif pred_short == 1:
            direction, proba, threshold = "SHORT", proba_short, thr_short_eff
        else:
            direction, proba, threshold = None, max(proba_long, proba_short), None

        if direction and open_count >= max_positions:
            logs.append(f"{sym} {direction} sinyali var ama pozisyon limiti dolu ({open_count}/{max_positions})")
            return _result(False, direction, proba, threshold,
                           "MAX_POSITIONS", ob_blocked)

        if direction:
            return _result(True, direction, proba, threshold, None, ob_blocked)

        # Sinyal yok — ham sinyal vardıysa neden elendiğini raporla
        if raw_long or raw_short:
            if raw_long and raw_short:
                blocked = (block_l if proba_long >= proba_short else block_s) \
                          or block_l or block_s
            else:
                blocked = block_l if raw_long else block_s
            blocked = blocked or "NO_SIGNAL"
        else:
            blocked = "NO_SIGNAL"
        return _result(False, None, proba, None, blocked, ob_blocked)
