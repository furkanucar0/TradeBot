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
| 03.07 21:11 | 45g | 0.5/1.0 | %36.1 | -5.03 | ✗ |

> Aktif model: en alttaki otomatik kayıt (04.07 02:30 — thrL 0.62 / thrS 0.52, iki yön de açık).
> Paper gerçek sonuçları: 03-04.07 gecesi ilk 2 işlem SL (-0.59 USDT toplam, risk tavanı tasarlandığı gibi çalıştı).

---
<!-- Otomatik kayıtlar aşağıya eklenir -->

### 2026-07-04 02:30
- Pencere: son 45 gün | temiz satır: 72410
- SL/TP: 0.5%/1.0% (R:R 2.0) | rapor yönü: SHORT | thrL=0.62 thrS=0.52
- Test: 88 işlem | WR 28.4% | PnL -13.16 USDT | Sharpe -3.89 | MaxDD 15.0%
- Günlük ort -1.46% | en kötü gün -5.50% | Canlı hazır: ✗ HAYIR

### 2026-07-05 00:34
- Pencere: son 45 gün | temiz satır: 72174
- SL/TP: 0.5%/1.0% (R:R 2.0) | rapor yönü: SHORT | thrL=0.58 thrS=0.64
- Test: 26 işlem | WR 26.9% | PnL -5.03 USDT | Sharpe -4.73 | MaxDD 7.0%
- Günlük ort -1.68% | en kötü gün -6.17% | Canlı hazır: ✗ HAYIR
- C-v-C: 🏆 CHALLENGER geçti — challenger +974.10 vs şampiyon +772.20 (gereken fark ≥ 38.61)

### 2026-07-09 09:21
- Pencere: son 45 gün | temiz satır: 60433
- SL/TP: 0.5%/1.0% (R:R 2.0) | rapor yönü: SHORT | thrL=0.68 thrS=0.58
- Test: 69 işlem | WR 30.4% | PnL -9.47 USDT | Sharpe -3.24 | MaxDD 13.2%
- Günlük ort -1.35% | en kötü gün -5.79% | Canlı hazır: ✗ HAYIR
- C-v-C: 🏆 CHALLENGER geçti — challenger +1026.90 vs şampiyon +608.40 (gereken fark ≥ 30.42)
