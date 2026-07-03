---
tags: [deney, kalibrasyon]
tarih: 2026-07-03
sonuç: uygulandı
---

# Kalibrasyon Kanıtı — Proba Dilimi → Gerçek İsabet

**Soru:** "Eşiği yükselt → WR yükselir" varsayımı doğru mu? (Ancak model olasılıkları sıralıysa doğrudur.)

**Yöntem:** model.bin'in doğrulama setindeki olasılıkları dilimlere ayrıldı, her dilimin gerçek etiket isabeti ölçüldü. Model: SL %0.5 / TP %1.0, maliyet dahil başabaş **%40**.

## SHORT modeli

| proba | n | gerçek WR | durum |
|---|---|---|---|
| 0.45–0.50 | 684 | %30.0 | ❌ zararına |
| 0.50–0.55 | 934 | %39.5 | ⚠️ sınırda |
| 0.55–0.60 | 1288 | %42.2 | ✓ |
| 0.60–0.65 | 1133 | **%69.2** | ✓✓ |
| 0.65–0.70 | 401 | **%72.1** | ✓✓ |
| 0.70+ | 701 | **%89.6** | ✓✓✓ |

LONG modeli de aynı şekilde monoton (0.50+ → %50.7, 0.65+ → %60.6).

## Uygulanan kararlar

- **SIGNAL_MARGIN 0.03 → 0.07:** efektif taban ~0.55 — zararına dilimler (0.45-0.55) tamamen dışarıda
- Trend vetosu delme çıtası (+0.15) böylece ~0.70'e denk gelir = %89.6'lık dilim

## Uyarılar

- Doğrulama seti early stopping'de kullanıldı → yüksek dilimlerin rakamları bir miktar iyimser olabilir; **monotonluk** asıl sağlam bulgu.
- Bu tablo modele özgüdür — her yeniden eğitimde olasılık ölçeği kayar. Bu yüzden **sabit mutlak eşik (örn. 0.65) yanlış**, göreli taban doğru yaklaşımdır. → [[Kararlar-Kaydı]] K-9

İlgili: [[2026-07-04-Karşı-Trend-Analizi]] (aynı yöntemin alt kümeye uygulanışı)
