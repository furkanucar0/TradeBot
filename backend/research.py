"""
Gece araştırma koşusu (K-31): boşta duran sunucu kapasitesiyle walk-forward
değerlendirme.

CANLI DAVRANIŞI DEĞİŞTİRMEZ — model.bin'e, eşiklere, canlı botun hiçbir
parçasına dokunmaz. Çıktısı kanıt üretimidir: reports/walkforward_last.json
+ Telegram özeti. Sonuçlara göre parametre değişikliği İNSAN kararıdır
(brain'e işlenir) — "yeşil rapor gelene kadar dene" tuzağına otomasyonla
girilmez (bkz. Kararlar-Kaydı: kararlılık paketi dersi).

Walk-forward, canlıdaki 7 günlük yaş-tetikli retrain ritmini (K-29) simüle
eder: her katmanda (fold) "o gün retrain olsaydı" modeli, o günden geriye
WINDOW_DAYS'lik pencereyle eğitilir ve SONRAKİ OOS_DAYS günde — modelin hiç
görmediği gelecekte — test edilir. Eğitim etiketleri SADECE pencere içi
veriyle üretilir (pencere sonundaki çözülmemiş satırlar 0 kalır — gerçek
retrain anındaki durumla birebir aynı; ileri-bakış yok).
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score

import train_engine
from config import ADX_RANGING_FLOOR, FEE_RATE, MIN_DIRECTION_PREC, SLIPPAGE_RATE
from features import FEATURE_COLS, add_features

REPORT_PATH = Path(__file__).resolve().parent / "reports" / "walkforward_last.json"

# Canlı retrain 45 gün yükler ama 1d-özellik ısınması ilk ~24 günü dropna ile
# yer → EFEKTİF eğitim verisi son ~21 gündür ve bölme oransal 70/15/15'e düşer
# (bkz. brain/Pencere-Hassasiyeti). Burada özellikler TÜM veride hesaplandığı
# için ısınma kaybı yok — canlıyla birebir aynı koşulu kurmak için pencere
# doğrudan efektif 21 gün alınır (daha genişi canlının görmediği veriyi
# görür, sonuç iyimser sapar).
WINDOW_DAYS = 21   # canlının EFEKTİF penceresi
OOS_DAYS = 7       # out-of-sample dilim = canlı yaş-tetiği ritmi (K-29)
MAX_FOLDS = 4      # gecelik koşu ~20-40 dk kalsın diye üst sınır

_MS_DAY = 86_400_000


def _pick_threshold(proba: np.ndarray, y_true: np.ndarray,
                    net_tp: float, net_sl: float, min_prec: float) -> float:
    """train_engine._optimize_threshold'un K-15 semantiğinin kopyası:
    val'de beklenen toplam net PnL maksimizasyonu, precision tabanı kısıt,
    en az 10 sinyal. Taban geçilemezse 1.01 (yön kapalı)."""
    best_thr, best_ev = None, -1e18
    for thr in [i / 100 for i in range(20, 70, 2)]:
        yt = (proba >= thr).astype(int)
        ns = int(yt.sum())
        if ns < 10:
            continue
        prec = precision_score(y_true, yt, zero_division=0)
        if prec < min_prec:
            continue
        total_ev = (prec * net_tp - (1 - prec) * net_sl) * ns
        if total_ev > best_ev:
            best_ev, best_thr = total_ev, thr
    return best_thr if best_thr is not None else 1.01


def run_walkforward(window_days: int = WINDOW_DAYS, oos_days: int = OOS_DAYS,
                    max_folds: int = MAX_FOLDS) -> Dict[str, Any]:
    """Walk-forward koşusunu çalıştırır ve rapor sözlüğünü döner + JSON'a yazar."""
    t0 = time.time()
    # Düşük öncelik: canlı bot/API ile CPU yarışmasın (Linux; Windows'ta atla)
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass

    df = train_engine.load_data(days=0)
    if df.empty:
        return {"error": "veri yok"}
    metrics_df = train_engine.load_market_metrics()
    # Özellikler TÜM veride bir kez hesaplanır (indikatörler geriye bakışlı —
    # sızıntı yok) → fold başına 1d-ısınma kaybı yaşanmaz
    df_feat = add_features(df, metrics_df=metrics_df)
    df_feat = df_feat.dropna(subset=FEATURE_COLS).copy()
    if df_feat.empty:
        return {"error": "özellik hesabından sonra satır kalmadı"}

    ts_min = int(df_feat["timestamp"].min())
    ts_max = int(df_feat["timestamp"].max())
    avail_days = (ts_max - ts_min) / _MS_DAY

    # Fold uçları: en yeni OOS dilimi en sonda biter, geriye oos_days adımlarla
    folds_cfg: List[int] = []
    for k in range(1, max_folds + 1):
        fold_end = ts_max - (k - 1) * oos_days * _MS_DAY   # OOS diliminin sonu
        train_end = fold_end - oos_days * _MS_DAY
        if train_end - window_days * _MS_DAY < ts_min:
            break   # pencere veri başlangıcından taşıyor
        folds_cfg.append(train_end)
    folds_cfg.reverse()   # eskiden yeniye

    fold_results: List[Dict[str, Any]] = []
    for i, train_end in enumerate(folds_cfg, 1):
        win_start = train_end - window_days * _MS_DAY
        oos_end = train_end + oos_days * _MS_DAY
        df_w = df_feat[(df_feat["timestamp"] > win_start)
                       & (df_feat["timestamp"] <= train_end)]
        df_oos = df_feat[(df_feat["timestamp"] > train_end)
                         & (df_feat["timestamp"] <= oos_end)]
        if len(df_w) < 2000 or len(df_oos) < 200:
            continue

        df_train, df_val, df_test_w = train_engine.split_train_val_test(df_w)

        # Grid search pencere içi train+val'de (canlı main() ile aynı disiplin)
        df_pretest = pd.concat([df_train, df_val])
        sl, tp, _, _, _ = train_engine.grid_search_rr(df_pretest)

        # Etiketler: pencere ve OOS AYRI AYRI — pencere-sonu etiketleri OOS
        # fiyatlarını göremez (görseydi eğitime gelecek sızardı)
        labels_w = train_engine.make_labels_bidir(df_w, sl, tp)
        labels_oos = train_engine.make_labels_bidir(df_oos, sl, tp)
        labels = pd.concat([labels_w, labels_oos])

        cost = FEE_RATE * 2 + SLIPPAGE_RATE
        net_tp, net_sl = tp - cost, sl + cost
        min_prec = max(MIN_DIRECTION_PREC, net_sl / (net_tp + net_sl) + 0.05)

        fold: Dict[str, Any] = {
            "fold": i,
            "train_end_utc": time.strftime("%Y-%m-%d", time.gmtime(train_end / 1000)),
            "sl_pct": sl, "tp_pct": tp,
            "window_rows": len(df_w), "oos_rows": len(df_oos),
        }
        # Canlı zincirin baskın filtresi: 1h ADX < taban → sinyal iptal (K-13).
        # Ham model sinyali ile ADX-filtreli sinyali AYRI AYRI ölçüyoruz —
        # fark, canlıdaki yatay-piyasa freninin kaç para kurtardığının kanıtı.
        adx_ok = (df_oos["h1_adx"] >= ADX_RANGING_FLOOR).astype(int).values

        for direction in ("LONG", "SHORT"):
            # df_test parametresine OOS verilir: train_model test setine hiç
            # bakmadan eğitir, proba_test bize hazır OOS olasılıkları döner
            model, y_val, proba_val, y_oos, proba_oos = train_engine.train_model(
                df_train, df_val, df_oos, labels, direction)
            thr = _pick_threshold(proba_val, y_val, net_tp, net_sl, min_prec)
            y_pred_oos = (proba_oos >= thr).astype(int)
            bt = train_engine.backtest(df_oos, y_pred_oos, proba_oos, sl, tp,
                                       direction=direction)
            bt_adx = train_engine.backtest(df_oos, y_pred_oos * adx_ok,
                                           proba_oos, sl, tp, direction=direction)
            fold[direction.lower()] = {
                "thr": thr,
                "oos_trades": bt["trades"],
                "oos_pnl": bt["total_pnl"],
                "oos_wr": bt["win_rate"],
                "oos_max_dd": bt["max_drawdown"],
                "adx_trades": bt_adx["trades"],
                "adx_pnl": bt_adx["total_pnl"],
                "adx_wr": bt_adx["win_rate"],
            }
        fold["oos_pnl_toplam"] = round(
            fold["long"]["oos_pnl"] + fold["short"]["oos_pnl"], 4)
        fold["adx_pnl_toplam"] = round(
            fold["long"]["adx_pnl"] + fold["short"]["adx_pnl"], 4)
        fold_results.append(fold)

    total_pnl = round(sum(f["oos_pnl_toplam"] for f in fold_results), 4)
    total_pnl_adx = round(sum(f["adx_pnl_toplam"] for f in fold_results), 4)
    total_trades = sum(f[d]["oos_trades"] for f in fold_results for d in ("long", "short"))
    total_trades_adx = sum(f[d]["adx_trades"] for f in fold_results for d in ("long", "short"))
    pos_folds = sum(1 for f in fold_results if f["oos_pnl_toplam"] > 0)
    pos_folds_adx = sum(1 for f in fold_results if f["adx_pnl_toplam"] > 0)

    report = {
        "ran_at_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
        "duration_min": round((time.time() - t0) / 60, 1),
        "params": {"window_days": window_days, "oos_days": oos_days,
                   "avail_days": round(avail_days, 1)},
        "folds": fold_results,
        "ozet": {
            "fold_sayisi": len(fold_results),
            "pozitif_fold": pos_folds,
            "toplam_oos_pnl": total_pnl,
            "toplam_oos_islem": total_trades,
            "adx_pozitif_fold": pos_folds_adx,
            "adx_toplam_pnl": total_pnl_adx,
            "adx_toplam_islem": total_trades_adx,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    return report


def format_telegram_summary(report: Dict[str, Any]) -> str:
    if report.get("error"):
        return f"🔬 <b>Walk-Forward Koşusu</b>\n❌ {report['error']}"
    o = report["ozet"]
    lines = [
        "🔬 <b>Gece Araştırma Koşusu — Walk-Forward</b>",
        f"({report['params']['window_days']}g pencere → {report['params']['oos_days']}g "
        f"görülmemiş gelecek, {o['fold_sayisi']} katman, {report['duration_min']} dk)",
        "",
    ]
    for f in report["folds"]:
        sign = "🟢" if f["adx_pnl_toplam"] > 0 else "🔴"
        lines.append(
            f"{sign} {f['train_end_utc']} sonrası 7g: "
            f"ham <b>{f['oos_pnl_toplam']:+.2f}</b> | "
            f"ADX filtreli <b>{f['adx_pnl_toplam']:+.2f} USDT</b>")
    lines += [
        "",
        f"Ham model: {o['toplam_oos_pnl']:+.2f} USDT ({o['toplam_oos_islem']} işlem, "
        f"{o['pozitif_fold']}/{o['fold_sayisi']} katman +)",
        f"ADX filtreli (canlı zincir): <b>{o['adx_toplam_pnl']:+.2f} USDT</b> "
        f"({o['adx_toplam_islem']} işlem, {o['adx_pozitif_fold']}/{o['fold_sayisi']} katman +)",
        "ℹ️ Rapor kanıttır — canlı model DEĞİŞMEDİ.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    rep = run_walkforward()
    print(json.dumps(rep, indent=2, ensure_ascii=False))
