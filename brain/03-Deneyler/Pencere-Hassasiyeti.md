---
tags: [deney, sınırlar]
tarih: 2026-07-03
---

# Pencere Hassasiyeti — Backtest'in En Önemli Sınırı

## Gözlem

45 günlük pencerede test dilimi **3-8 güne** iner (1d özellik ısınması ~24 gün yer). Bu boyutta:

- 2026-07-02 akşamı iki eğitim: **+13.8 ve +19.7 USDT, ready=True**
- Aynı konfigürasyonla ertesi gün (pencere 1 gün kaydı): **negatif, ready=False**

Model değişmedi — pencere kaydı. Tek günlük veri kayması sonucun işaretini değiştirebiliyor.

## Çıkarımlar

1. **"Yeşil rapor gelene kadar retrain" YASAK.** Test sonucuna göre model seçmek, özenle kaldırdığımız sızıntının geri gelmesidir. (2026-07-03'te bu tuzağa yaklaşıldı ve durduruldu.)
2. Backtest'in görevi **felaket kontrolü** (model saçmalıyor mu, riskler çalışıyor mu), kesin kârlılık sertifikası değil.
3. `ready_for_live` bayrağı bu yüzden gün gün değişebilir — panik sebebi değil.
4. **Asıl hakem paper işlem geçmişidir:** gerçek zamanlı, örneklem biriktikçe güç kazanır, sızıntısı imkânsız.

## Olası iyileştirmeler (yapılmadı, aday)
- Walk-forward: birden çok kayan test dilimi üzerinden ortalama metrik
- Test dilimini büyütmek ↔ eğitim verisinden çalar; 45g pencerede yer yok
- Pencereyi büyütmek ↔ rejim karışıklığı yönleri kapatıyor (denendi)

İlgili: [[Model-ve-Eğitim]], [[2026-07-03-RR-Bandı-Deneyi]]
