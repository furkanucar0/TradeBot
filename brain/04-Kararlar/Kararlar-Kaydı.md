---
tags: [kararlar]
---

# Kararlar Kaydı (ADR)

Her kararın dayanağıyla birlikte kaydı. Format: **K-# · karar · durum · dayanak**.

## Kabul edilenler

- **K-1 · Tek özellik kaynağı (features.py)** · ✅ 02.07 · Train/serve kayması %2 altına indi; eski çift kopyada OBV yapısal farklıydı.
- **K-2 · Train/val/test + 24s purge** · ✅ 02.07 · Üçlü test sızıntısı kaldırıldı (early stop + threshold + backtest aynı setteydi).
- **K-3 · Volatilite cezası göreli medyana** · ✅ 03.07 · h1_atr_ratio doğal bandı 7-17; mutlak ceza eşiği +0.25'e sabitleyip TÜM sinyalleri öldürüyordu.
- **K-4 · Eğitim penceresi 45 gün** · ✅ 03.07 · 90g ve tam veri her iki yönü precision kapısına takıyor; 45g çalışıyor.
- **K-5 · REST fiyat yedeği (5 sn)** · ✅ 03.07 · Bu ağda WS market datası hiç akmıyor → [[Ağ-ve-Ortam-Kısıtları]].
- **K-6 · Kararlılık paketi** · ✅ 03.07 · Risk %0.5, kaldıraç 5x, günlük -%1.5/+%2 frenler, korelasyon yarım-boy → [[Risk-Yönetimi]].
- **K-7 · MAX_RR kısıtı geri alındı (4.0)** · ✅ 03.07 · R:R 2.0'da kenar maliyet-sonrası başabaşı tutmuyor → [[2026-07-03-RR-Bandı-Deneyi]].
- **K-8 · Grid skoru wr²×rr** · ✅ 03.07 · Taban-EV skoru pencere kaymasına kırılgan çıktı; kanıtlanmış skora dönüldü.
- **K-9 · SIGNAL_MARGIN 0.07 (göreli taban ~0.55)** · ✅ 03.07 · Kalibrasyon monoton; 0.45-0.55 dilimleri zararına → [[2026-07-03-Kalibrasyon-Kanıtı]].
- **K-10 · Dinamik precision tabanı (başabaş+%5)** · ✅ 03.07 · Sabit 0.40 tabanı dar kombolarda başabaşın altındaydı → zararına aşırı işlem.
- **K-11 · Trend vetosu güven ölçekli (+0.15 delme)** · ✅ 03-04.07 · Mutlak veto SHORT-only model + yukarı trendde botu kilitliyordu; delen alt kümenin val WR'ı %70-83 → [[2026-07-04-Karşı-Trend-Analizi]].
- **K-12 · Rapor PnL'i giriş komisyonu dahil** · ✅ 03.07 · Günlük metrik kasayla çelişiyordu (+0.51 görünen gerçekte -0.59).
- **K-13 · B-1/B-2/B-3 paketi** · ✅ 04.07 · (a) Dinamik eşik ayarı ≥0 — filtreler sadece eler, bonus tabanı 0.50'ye çekemez; (b) otomatik retrain: ≥20 yeni işlem VE ≥12 saat ara (gürültüye eğitim engeli); (c) REST fiyat 5sn→2sn.
- **K-14 · Proba-ölçekli boyutlandırma (H-1)** · ✅ 04.07 · İşlemin kendi olasılığıyla Kelly: ölçek 0.4-1.0 (p=0.50→0.62×, p≥0.62→1.0×). Canlı+backtest aynı formül. Dayanak: [[2026-07-03-Kalibrasyon-Kanıtı]] monoton.
- **K-15 · Threshold seçimi val-EV ile (H-2)** · ✅ 04.07 · F1 yerine doğrulamada beklenen toplam net PnL maksimize edilir; precision tabanı kısıt olarak durur. "Ödül mantığı v1"in ikinci yarısı.
- **K-16 · Günlük Telegram raporu (H-4)** · ✅ 04.07 · UTC gün dönümünde dünün işlem/WR/PnL/kasa özeti otomatik gönderilir.

## Reddedilenler

- **R-1 · Sabit 0.65 olasılık eşiği** · ❌ · Olasılık ölçeği her eğitimde kayar; göreli taban doğru (K-9 zaten ~0.55 sağlıyor).
- **R-2 · Zarar sonrası eşik yükseltme (0.75)** · ❌ · İşlemler ~bağımsız; tekil sonuca tepki = kumarcı sezgisi. Kelly + DD ölçeği + günlük fren bunu doğru yapıyor.
- **R-3 · Trend vetosunu tamamen kaldırma/mutlaklaştırma** · ❌ 04.07 · Veri aksini gösterdi (K-11).
- **R-4 · SL/TP damping** · ❌ 04.07 · Aynı konfigde SL/TP 5 ardışık eğitimde hiç değişmedi; çözülmemiş sorun yok.
- **R-5 · Kör özellik kesimi (33→15)** · ❌ (şimdilik) · "Curse of dimensionality" ağaç modeli için yanlış çerçeve; ölü özellik zararsız. Kesim istenirse importance listesi hazır → [[İndikatörler]].
- **R-6 · Ek komisyon cezası** · ❌ · Zaten %0.10 + funding modelleniyor (önerilen %0.06'dan sert).

## Beklemede

- **B-4 · Faz 2 adayları (paper 100 işlem sonrası):** sembol genişletme (H-5), walk-forward (H-6), maker giriş (H-7), kısmi TP (H-8) → [[2026-07-04-Kâr-Marjı-Raporu]]. Ön şart: paper'da 50-100 kapanmış işlem birikmesi ("paper'a sabır" ilkesi).
