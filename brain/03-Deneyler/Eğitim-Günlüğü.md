---
tags: [günlük, otomatik]
---

# Eğitim Günlüğü

> ⚙️ Bu notun altına her eğitim **otomatik** eklenir (train_engine.py yazan kancayla).
> Geçmiş eğitimlerin tam listesi DB'de: `SELECT * FROM model_runs`.

## Özet geçmiş (kanca öncesi, elle derlendi)

| Tarih | Pencere | SL/TP | Test WR | PnL | Hazır |
|---|---|---|---|---|---|
| 02.07 21:44 | 45g | 0.3/1.2 | %27.7 | +2.78 | ✗ |
| 03.07 19:59 | 45g | 0.3/1.2 | %31.2 | +13.76 | ✓ |
| 03.07 20:42 | 45g | 0.3/1.2 | %30.9 | +19.68 | ✓ |
| 03.07 21:01-08 | 45g (R:R deneyi) | 0.3/0.6 | %40-42 | -8..-10 | ✗ |
| 03.07 21:11 | 45g | 0.5/1.0 | %36.1 | -5.03 | ✗ ← aktif model |

---
<!-- Otomatik kayıtlar aşağıya eklenir -->
