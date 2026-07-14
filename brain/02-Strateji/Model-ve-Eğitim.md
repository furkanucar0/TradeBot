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
Doğrulamada **beklenen toplam net PnL maksimizasyonu (K-15)**: sinyal sayısı × işlem başına komisyon-dahil EV. Kısıt: **dinamik precision tabanı** = kombonun maliyet-dahil başabaş WR'ı + %5. Yön tabanı geçemezse threshold 1.01 → o yön kapalı (bilinçli güvenlik davranışı — "bot sinyal üretmiyor" şikayetinin meşru nedeni olabilir). Eskiden F1 maksimize ediliyordu — sınıflandırma metriği para ile hizalı değildi.

## Eğitimde örnek ağırlığı (K-29 — 13.07)
45 günlük pencerede satırlar zaman-doğrusal ağırlıklanır: en eski 0.5 → en yeni 1.0 (`RECENCY_WEIGHT_MIN`). Eski rejimlerin etkisi pencereyi kısaltmadan azaltılır. Ağırlık SADECE fit'e uygulanır — doğrulama seti ağırlıksızdır (erken durdurma, eşik ve yön seçimi tarafsız kalır). C-v-C bu değişikliğin zararlı çıkması ihtimaline karşı otomatik sigortadır.

## Yeniden eğitim
- Manuel: `/train` (Telegram/dashboard) → son 45 gün
- Otomatik, iki tetik (`_maybe_auto_retrain`, K-13 + K-29):
  - **İşlem tetiği:** ≥20 yeni kapanan paper işlem + ≥12 saat ara
  - **Yaş tetiği:** model.bin ≥7 gün eski (`RETRAIN_MAX_AGE_DAYS`) + ≥12 saat ara — yönsüz piyasada işlem-sayısı tetiği hiç ateşlenmediği için bayatlama önlemi. DİKKAT: yaş tetiği ana sinyal döngüsünde de kontrol edilir (sadece işlem kapanışında kontrol edilseydi işlemsiz dönemde hiç çalışmazdı); 12s gap guard'ı C-v-C reddi sonrası retrain fırtınasını engeller (red, mtime'ı değiştirmez)
- Eğitim sırasında yeni pozisyon açılmaz; yeni SL/TP devralınır
- Her eğitim `model_runs` tablosuna + [[Eğitim-Günlüğü]]'ne kaydolur

## Champion vs Challenger (K-22 — 05.07)
Retrain modeli körlemesine EZMEZ. Yeni model (challenger) ortak doğrulama diliminde şampiyonla **val toplam net EV** üzerinden kıyaslanır; şampiyonun EV'sinin **≥%5 üstünde** değilse `model.bin` ve dashboard raporu DEĞİŞMEZ (challenger raporu `reports/challenger_last.json`'a). Şampiyonun SL/TP kombosu farklıysa doğrulama etiketleri onun kombosuyla yeniden üretilir — adil kıyas. Kaçış kapısı: `/train?force=true`. Sonuç her eğitim günlüğü kaydında "C-v-C:" satırında.

İlgili: [[2026-07-03-Kalibrasyon-Kanıtı]], [[2026-07-03-RR-Bandı-Deneyi]]
