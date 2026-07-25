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

# ── Turnuva varyantları (2026-07-23 deney notundaki ÖN-KAYITLI hipotezler) ────
# Hepsi AYNI eğitilmiş modelleri paylaşır (fark sadece eşik/filtre) → turnuva
# tek eğitim maliyetine koşar. prec_bump: precision tabanı tamponu (canlı 0.05);
# adx_floor: OOS'ta uygulanan ADX maskesi; extra_margin: canlı SIGNAL_MARGIN
# benzeri, seçilen eşiğin ÜSTÜNE tahmin anında eklenir.
VARIANTS = [
    {"ad": "temel",       "prec_bump": 0.05, "adx_floor": 20, "extra_margin": 0.0},
    {"ad": "H-A_prec10",  "prec_bump": 0.10, "adx_floor": 20, "extra_margin": 0.0},
    {"ad": "H-B_adx25",   "prec_bump": 0.05, "adx_floor": 25, "extra_margin": 0.0},
    {"ad": "H-C_margin7", "prec_bump": 0.05, "adx_floor": 20, "extra_margin": 0.07},
    # H-G (26.07, "düşen piyasada hiç short yok" olayı): precision kapısı
    # TAMAMEN kapalı — eşik sadece EV-maks ile seçilir. Kapının 12 haftada
    # kaç para kurtardığının/kaçırdığının doğrudan ölçümü. prec_bump<0 özel
    # değeri "taban yok" demektir.
    {"ad": "H-G_kapisiz", "prec_bump": -1.0, "adx_floor": 20, "extra_margin": 0.0},
]

# R-baseline (15m range-fade) ön-kayıtlı parametreleri — kullanıcının "15m'de
# gridlenebilir alanlar var" gözleminin kural-bazlı, MODELSİZ testi. Tek
# konfigürasyon, ayar taraması YOK (tarama = çoklu-karşılaştırma tuzağı).
RANGE_SL, RANGE_TP = 0.004, 0.006   # mean-reversion tipik R:R 1.5


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


def _resample_bars(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """1m OHLCV'yi N-dakikalık barlara toplar (H-D: 15m çerçeve testi)."""
    out = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("timestamp")
        idx = pd.to_datetime(g["timestamp"], unit="ms")
        r = (g.set_index(idx)
              .resample(f"{minutes}min")
              .agg(open=("open", "first"), high=("high", "max"),
                   low=("low", "min"), close=("close", "last"),
                   volume=("volume", "sum"))
              .dropna())
        r["timestamp"] = r.index.astype("int64") // 10**6
        r["symbol"] = sym
        out.append(r.reset_index(drop=True))
    return pd.concat(out, ignore_index=True)


def _range_fade_fold(df_oos: pd.DataFrame) -> Dict[str, Any]:
    """R-baseline: 15m Bollinger dönüş kuralı — SADECE ADX<20 (yatay) rejimde,
    yani ML stratejisinin bilerek oynamadığı saatlerde. Sinyal bir ÖNCEKİ
    kapanmış 15m bardan (bar içi lookahead yok), giriş sinyal barının
    kapanışında (backtest'in standart konvansiyonu)."""
    import ta as _ta
    frames = {"LONG": [], "SHORT": []}
    for sym, g in df_oos.groupby("symbol"):
        g = g.sort_values("timestamp")
        idx = pd.to_datetime(g["timestamp"], unit="ms")
        g15 = (g.set_index(idx)
                .resample("15min")
                .agg(open=("open", "first"), high=("high", "max"),
                     low=("low", "min"), close=("close", "last"),
                     h1_adx=("h1_adx", "last"))
                .dropna())
        if len(g15) < 25:
            continue
        bb = _ta.volatility.BollingerBands(g15["close"], window=20, window_dev=2)
        rsi = _ta.momentum.RSIIndicator(g15["close"], window=14).rsi()
        ranging = g15["h1_adx"] < ADX_RANGING_FLOOR
        long_sig = ((g15["close"] <= bb.bollinger_lband()) & (rsi < 30) & ranging).shift(1)
        short_sig = ((g15["close"] >= bb.bollinger_hband()) & (rsi > 70) & ranging).shift(1)
        base = g15.reset_index(drop=True)
        base["timestamp"] = (g15.index.astype("int64") // 10**6).values
        base["symbol"] = sym
        for sig, direction in ((long_sig, "LONG"), (short_sig, "SHORT")):
            d = base.copy()
            d["_sig"] = sig.fillna(False).astype(int).values
            frames[direction].append(d)

    out = {"pnl": 0.0, "trades": 0, "wins": 0}
    for direction, lst in frames.items():
        if not lst:
            continue
        d = pd.concat(lst).sort_values("timestamp").reset_index(drop=True)
        preds = d["_sig"].values
        if preds.sum() == 0:
            continue
        # sabit 0.60 proba → Kelly ölçeği nötr (kural stratejisinde olasılık yok)
        proba = np.where(preds == 1, 0.60, 0.0)
        bt = train_engine.backtest(d, preds, proba, RANGE_SL, RANGE_TP,
                                   direction=direction)
        out["pnl"] = round(out["pnl"] + bt["total_pnl"], 4)
        out["trades"] += bt["trades"]
        out["wins"] += bt["wins"]
    return out


def run_walkforward(window_days: int = WINDOW_DAYS, oos_days: int = OOS_DAYS,
                    max_folds: int = MAX_FOLDS, bar_minutes: int = 1,
                    fixed_sl: Optional[float] = None,
                    fixed_tp: Optional[float] = None) -> Dict[str, Any]:
    """Walk-forward koşusunu çalıştırır ve rapor sözlüğünü döner + JSON'a yazar.

    bar_minutes>1 (H-D): tüm hat N-dakikalık barlarda çalışır — aynı
    indikatörler daha kaba zaman ölçeğinde hesaplanır, SL/TP sabit verilir
    (grid atlanır; ön-kayıt disiplini: tarama = çoklu-karşılaştırma tuzağı).
    Amaç maliyet oranını değiştirmek: 1m'de maliyet TP'nin ~%15-20'si,
    15m + TP %2'de ~%6'sı."""
    t0 = time.time()
    # Düşük öncelik: canlı bot/API ile CPU yarışmasın (Linux; Windows'ta atla)
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass

    df = train_engine.load_data(days=0)
    if df.empty:
        return {"error": "veri yok"}
    if bar_minutes > 1:
        df = _resample_bars(df, bar_minutes)
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

        if fixed_sl is not None and fixed_tp is not None:
            sl, tp = fixed_sl, fixed_tp   # H-D: ön-kayıtlı sabit kombo, grid yok
        else:
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
        # ── Eğitim: yön başına BİR kez — tüm varyantlar bu modelleri paylaşır
        # (fark sadece eşik/filtre; turnuva tek eğitim maliyetine koşar)
        trained: Dict[str, Dict[str, np.ndarray]] = {}
        for direction in ("LONG", "SHORT"):
            # df_test parametresine OOS verilir: train_model test setine hiç
            # bakmadan eğitir, proba_test bize hazır OOS olasılıkları döner
            model, y_val, proba_val, y_oos, proba_oos = train_engine.train_model(
                df_train, df_val, df_oos, labels, direction)
            trained[direction] = {"y_val": y_val, "proba_val": proba_val,
                                  "proba_oos": proba_oos}

        # ── Varyant turnuvası (VARIANTS ön-kayıtlı; canlı zincir yaklaşımı =
        # her varyant kendi ADX maskesiyle). "temel" varyantın ham hâli de
        # ölçülür (önceki raporlarla süreklilik + ADX freninin kazancı).
        fold["varyant"] = {}
        for v in VARIANTS:
            # prec_bump < 0 → precision tabanı YOK (H-G): eşik salt EV-maks
            v_min_prec = (0.0 if v["prec_bump"] < 0 else
                          max(MIN_DIRECTION_PREC, net_sl / (net_tp + net_sl) + v["prec_bump"]))
            v_adx_ok = (df_oos["h1_adx"] >= v["adx_floor"]).astype(int).values
            v_pnl = v_pnl_ham = 0.0
            v_tr = v_tr_ham = 0
            per_dir = {}
            for direction in ("LONG", "SHORT"):
                t = trained[direction]
                thr = _pick_threshold(t["proba_val"], t["y_val"],
                                      net_tp, net_sl, v_min_prec)
                y_pred = (t["proba_oos"] >= thr + v["extra_margin"]).astype(int)
                bt_ham = train_engine.backtest(df_oos, y_pred, t["proba_oos"],
                                               sl, tp, direction=direction)
                bt_flt = train_engine.backtest(df_oos, y_pred * v_adx_ok,
                                               t["proba_oos"], sl, tp,
                                               direction=direction)
                v_pnl_ham += bt_ham["total_pnl"]; v_tr_ham += bt_ham["trades"]
                v_pnl += bt_flt["total_pnl"];     v_tr += bt_flt["trades"]
                per_dir[direction.lower()] = {"thr": thr,
                                              "pnl": bt_flt["total_pnl"],
                                              "trades": bt_flt["trades"],
                                              "wr": bt_flt["win_rate"]}
            fold["varyant"][v["ad"]] = {"pnl": round(v_pnl, 4), "trades": v_tr,
                                        "pnl_ham": round(v_pnl_ham, 4),
                                        "trades_ham": v_tr_ham, **per_dir}

        # Eski rapor şemasıyla süreklilik: temel varyantın ham/ADX değerleri
        base_v = fold["varyant"]["temel"]
        for dl in ("long", "short"):
            fold[dl] = {"thr": base_v[dl]["thr"], "oos_trades": base_v[dl]["trades"],
                        "oos_pnl": base_v[dl]["pnl"], "oos_wr": base_v[dl]["wr"],
                        "adx_trades": base_v[dl]["trades"], "adx_pnl": base_v[dl]["pnl"],
                        "adx_wr": base_v[dl]["wr"]}
        fold["oos_pnl_toplam"] = base_v["pnl_ham"]
        fold["adx_pnl_toplam"] = base_v["pnl"]

        # ── R-baseline: kullanıcının 15m grid gözlemi — modelsiz kural testi
        fold["range_15m"] = _range_fade_fold(df_oos)
        fold_results.append(fold)

    total_pnl = round(sum(f["oos_pnl_toplam"] for f in fold_results), 4)
    total_pnl_adx = round(sum(f["adx_pnl_toplam"] for f in fold_results), 4)
    total_trades = sum(f[d]["oos_trades"] for f in fold_results for d in ("long", "short"))
    total_trades_adx = sum(f[d]["adx_trades"] for f in fold_results for d in ("long", "short"))
    pos_folds = sum(1 for f in fold_results if f["oos_pnl_toplam"] > 0)
    pos_folds_adx = sum(1 for f in fold_results if f["adx_pnl_toplam"] > 0)

    # Turnuva sıralaması (varyantlar + R-baseline) — hepsi aynı OOS haftaları
    turnuva: Dict[str, Any] = {}
    for v in VARIANTS:
        pnls = [f["varyant"][v["ad"]]["pnl"] for f in fold_results]
        turnuva[v["ad"]] = {
            "toplam_pnl": round(sum(pnls), 4),
            "islem": sum(f["varyant"][v["ad"]]["trades"] for f in fold_results),
            "pozitif_fold": sum(1 for p in pnls if p > 0),
        }
    r_pnls = [f["range_15m"]["pnl"] for f in fold_results]
    turnuva["R_range15m"] = {
        "toplam_pnl": round(sum(r_pnls), 4),
        "islem": sum(f["range_15m"]["trades"] for f in fold_results),
        "pozitif_fold": sum(1 for p in r_pnls if p > 0),
    }

    report = {
        "ran_at_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
        "duration_min": round((time.time() - t0) / 60, 1),
        "params": {"window_days": window_days, "oos_days": oos_days,
                   "avail_days": round(avail_days, 1),
                   "bar_minutes": bar_minutes,
                   "fixed_sl": fixed_sl, "fixed_tp": fixed_tp},
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
        "turnuva": turnuva,
    }
    # H-D koşusu ayrı dosyaya yazar — gece 1m otomatiğinin raporunu ezmesin
    out_path = (REPORT_PATH if bar_minutes == 1
                else REPORT_PATH.with_name(f"walkforward_{bar_minutes}m_last.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    return report


def format_telegram_summary(report: Dict[str, Any]) -> str:
    if report.get("error"):
        return f"🔬 <b>Walk-Forward Koşusu</b>\n❌ {report['error']}"
    o = report["ozet"]
    bm = report["params"].get("bar_minutes", 1)
    lines = [
        f"🔬 <b>Araştırma Koşusu — Walk-Forward{f' [{bm}m ÇERÇEVE]' if bm > 1 else ''}</b>",
        f"({report['params']['window_days']}g pencere → {report['params']['oos_days']}g "
        f"görülmemiş gelecek, {o['fold_sayisi']} katman, {report['duration_min']} dk)",
        "",
    ]
    lines.append("🏆 <b>Turnuva</b> (aynı OOS haftaları, toplam PnL):")
    siralama = sorted(report.get("turnuva", {}).items(),
                      key=lambda kv: kv[1]["toplam_pnl"], reverse=True)
    for ad, t in siralama:
        sign = "🟢" if t["toplam_pnl"] > 0 else "🔴"
        lines.append(f"{sign} {ad}: <b>{t['toplam_pnl']:+.2f} USDT</b> "
                     f"({t['islem']} işlem, {t['pozitif_fold']}/{o['fold_sayisi']} hafta +)")
    lines += [
        "",
        f"Temel ham: {o['toplam_oos_pnl']:+.2f} | ADX'li: {o['adx_toplam_pnl']:+.2f} USDT",
        "ℹ️ Rapor kanıttır — canlı model DEĞİŞMEDİ.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    rep = run_walkforward()
    print(json.dumps(rep, indent=2, ensure_ascii=False))
