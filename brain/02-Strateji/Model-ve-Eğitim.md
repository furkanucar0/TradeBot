---
tags: [strateji, model]
---

# Model ve Eğitim

## Model
- İki bağımsız ikili sınıflandırıcı: **LONG kazanır mı** + **SHORT kazanır mı**
- LightGBM vs XGBoost her eğitimde doğrulama F1'iyle yarışır; kazanan `model.bin`'e yazılır
- Düzenlileştirme: num_leaves 20, min_child_samples 100, L1/L2 0.1, subsample/colsample 0.8, early stopping 50

## Etiketleme (çift yönlü)
Her mum için ileri tarama: `1` = LONG TP'si SL'den önce vurulur, `2` = SHORT kazanır, `0` = ikisi de değil. TP/SL seviyeleri grid search'ün seçtiği kombodan gelir (güncel: SL %0.5 / TP %1.0).

## Veri disiplini (üçlü sızıntı düzeltmesi — 2026-07-02)
```
[ eğitim ]--24s tampon--[ doğrulama 21g ]--24s tampon--[ test 21g ]
```
- Early stopping + threshold seçimi + yön seçimi + model yarışı: **doğrulamada**
- Rapor + backtest: **dokunulmamış testte**
- Grid search: sadece eğitim+doğrulamada
- Eski hal: üçü de aynı test setindeydi → metrikler şişkindi

## Pencere: kayan son 45 gün
Deneyle sabit: 90+ gün ve tam veri, her iki yönü precision kapısına takıyor (rejim karışıklığı). 45 günün ~24'ü 1d-özellik ısınmasına gider → efektif ~20 gün → bölme oransal 70/15/15'e düşer. → [[Pencere-Hassasiyeti]]

## Threshold seçimi
Doğrulamada F1 maksimizasyonu, **dinamik precision tabanıyla**: taban = kombonun komisyon+slippage dahil başabaş WR'ı + %5. Yön bu tabanı geçemezse threshold 1.01 → o yön kapalı (bilinçli güvenlik davranışı — "bot sinyal üretmiyor" şikayetinin meşru nedeni olabilir).

## Yeniden eğitim
- Manuel: `/train` (Telegram/dashboard) → son 45 gün
- Otomatik: her 20 kapanan paper işlemde (eğitim sırasında yeni pozisyon açılmaz; yeni SL/TP devralınır)
- Her eğitim `model_runs` tablosuna + [[Eğitim-Günlüğü]]'ne kaydolur

İlgili: [[2026-07-03-Kalibrasyon-Kanıtı]], [[2026-07-03-RR-Bandı-Deneyi]]
