---
tags: [strateji, özellikler]
---

# İndikatörler (33 Özellik)

Tek kaynak: `backend/features.py` — eğitim ve canlı aynı kodu kullanır.

## Gruplar

- **1m (19):** RSI-14, StochRSI K/D, MACD (3), Bollinger pozisyon+genişlik, ATR-14, hacim oranı/delta/ivme, işaretli hacim akışı (pencereli obv_ratio), Heikin-Ashi gövde+2 fitil, ATR-normalize 1/5/15dk getiriler
- **Zaman (4):** saat sin/cos, Londra (07-10 UTC), New York (13-16 UTC)
- **1h MTF (6):** RSI, MACD hist, EMA9×21 kesişimi, BB pozisyon, ADX, 1h/1m ATR oranı — hep bir önceki KAPANMIŞ bardan
- **1d MTF (3):** RSI, EMA20 eğimi, BB pozisyon — bir önceki kapanmış günden
- **Hizalama (1):** tf_alignment (0-3)

## 🔑 Importance bulgusu (2026-07-04, SHORT modeli, gain)

**İlk 9 özellik kazancın %95.6'sını taşıyor — hepsi 1h/1d + zaman:**

| # | Özellik | Pay |
|---|---|---|
| 1 | h1_adx | %22.9 |
| 2 | h1_macd_hist | %14.0 |
| 3 | h1_rsi | %12.8 |
| 4 | d1_rsi | %11.7 |
| 5 | d1_bb_pos | %10.7 |
| 6 | h1_bb_pos | %8.0 |
| 7 | hour_sin | %7.2 |
| 8 | atr_14 | %4.4 |
| 9 | hour_cos | %4.0 |

1m indikatörlerinin çoğu (RSI, MACD, BB pozisyon, hacim ailesi, HA, StochRSI, getiriler) **~%0 katkılı**. Model fiilen bir "saatlik rejim tanıyıcı" — 1m verisi sadece zamanlama hassasiyeti sağlıyor.

**Sonuç:** "33 özellik overfitting yaratır" iddiası ağaç modelleri için yanlış (130k satır yeterli, ölü özellik GBM'e zarar vermez); ama sadeleştirme istenirse kesim listesi hazır. Önce LONG modelde de doğrulanmalı. → [[Kararlar-Kaydı]]

## Uyarılar

- `h1_atr_ratio` doğal bandı **7-17'dir** (1h ATR >> 1m ATR). Mutlak değere eşik/ceza bağlama — bu hata botu bir kez tamamen kilitledi (bkz. [[Kararlar-Kaydı]] K-3).
- 1d özellikler ≥21 gün veri ister → eğitim penceresinin ilk ~24 günü dropna ile gider; `--days 45`'in efektif verisi ~20 gündür.
