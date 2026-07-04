---
tags: [plan, rapor]
tarih: 2026-07-04
durum: faz-1-uygulandı
---

> ✅ **Karar (04.07):** H-1+H-2+H-3+H-4 onaylandı ve uygulandı → [[Kararlar-Kaydı]] K-13..K-16.
> H-5..H-8 Faz 2'de (paper 50-100 işlem sonrası) → Kararlar-Kaydı B-4.

# Kâr Marjı Raporu — Ödül Mantığı ve Yükseltme Hamleleri

## 1. Mevcut durumda "ödül mantığı" var mı?

**Hayır — sistem parayı değil, sınıflandırmayı optimize ediyor.** Model "TP mi SL mi önce vurulur" sorusunda logloss/F1 ile eğitiliyor; para kavramı sadece üç dolaylı yerden giriyor:
1. Threshold seçimi: F1 maksimizasyonu + precision tabanı (başabaş+%5) — para *kısıtı* var ama *hedef* değil
2. Quarter-Kelly: son 20 işlemin WR'ına göre boyut — geriye dönük, işlem bazlı değil
3. Grid search: SL/TP kombosu wr²×rr skoruyla

**Boşluk:** %56 olasılıklı sinyal ile %85 olasılıklı sinyal AYNI parayla oynanıyor. Oysa [[2026-07-03-Kalibrasyon-Kanıtı]] dilimler arasında dev fark olduğunu kanıtladı (0.55-0.60: %42 · 0.70+: %89.6). Ödül mantığının en ucuz ve en kanıtlı hali burada duruyor.

## 2. Kâr marjını yükseltecek hamleler (öncelik sırasıyla)

| # | Hamle | Beklenen etki | Efor | Dayanak |
|---|---|---|---|---|
| H-1 | **Proba-ölçekli boyutlandırma** — işlemin KENDİ olasılığıyla Kelly: f ∝ (p·rr−(1−p))/rr, %0.5 tavan korunur | Yüksek — aynı sinyallerden daha çok EV/risk | Küçük | Kalibrasyon monoton ✓ |
| H-2 | **Threshold'u F1 yerine val-EV ile seç** — beklenen toplam net PnL'i maksimize eden eşik | Orta — eşik doğrudan paraya bağlanır | Küçük | Mevcut altyapı hazır |
| H-3 | **Beklemedeki B-1/B-2/B-3** (bonus yasağı, retrain arası 12s, REST 2sn) | Küçük ama bedava | Trivial | [[Kararlar-Kaydı]] |
| H-4 | **Günlük Telegram raporu** — dünün işlem/PnL/fren özeti her sabah | Dolaylı — görünürlük karar kalitesi | Küçük | — |
| H-5 | **Sembol genişletme** (SOL, BNB…) — günlük fırsat sayısı artar, işlem başına risk artmaz | Orta-yüksek | Orta (veri+korelasyon matrisi) | — |
| H-6 | **Walk-forward doğrulama** — 3-4 kayan test diliminin ortalaması | Dolaylı — ready kararı sağlamlaşır | Orta | [[Pencere-Hassasiyeti]] |
| H-7 | **Maker giriş denemesi** — limit emirle giriş: %0.04 → %0.02 komisyon | Küçük-orta (maliyetin ~%40'ı) | Orta (dolmama riski simüle edilmeli) | — |
| H-8 | **Kısmi TP / iz süren stop** — 1R'de yarım kapat, kalanı trail | Belirsiz — backtest'te ölçülmeli | Orta-büyük | — |

## 3. Tam RL (pekiştirmeli öğrenme) değerlendirmesi

"Ödül mantığı" denince akla gelen tam RL (durum→aksiyon→PnL ödülü) **bu ölçekte önerilmez**:
- Efektif temiz verimiz ~20 gün — RL ajanları milyonlarca adım ister, bizde ~30k karar noktası var
- RL finansal zaman serilerinde kararsızlığıyla ünlü; doğrulaması bizim [[Pencere-Hassasiyeti]] sorunumuzu katlar
- Aynı faydanın %80'i, denetimli öğrenmeye ödül enjekte ederek alınır: **H-1 + H-2** (literatürdeki "meta-labeling / reward-weighted learning" yaklaşımı)

**Yol haritası:** H-1+H-2 = "ödül mantığı v1". Paper'da 100+ işlem birikince sonuçlarına bakılır; ancak ondan sonra daha derin ödül mimarisi (örnek ağırlıklandırma, kısmi TP) düşünülür.

## 4. Claude'un kendi eklemek istedikleri

1. **H-1'i en öne alırdım** — elimizdeki en sağlam kanıt (kalibrasyon) hâlâ paraya çevrilmedi; düşük riskli, geri alınabilir.
2. **H-4 (günlük rapor)** — sistemin güvenilirliği kadar *gözlenebilirliği* de kâr getirir; yanlış gidişi 1 gün erken görmek frenlerden değerlidir.
3. **Paper'a sabır** — en az 50-100 kapanmış işlem birikmeden yeni büyük strateji değişikliği yapmamak. Şu an elimizdeki her kanıt doğrulama setinden; paper ilk bağımsız kanıt olacak.
4. Karşı görüş olarak: H-5 (sembol ekleme) cazip görünse de her sembol ayrı rejim demek — önce 2 sembolde kârlılık kanıtlanmalı.

## 5. Önerilen karar paketi

**Şimdi:** H-3 (bedava) + H-1 + H-2 + H-4 → sonra 45g yeniden eğitim → paper devam
**Paper 100 işlem sonrası:** sonuçlara göre H-5/H-6/H-7 önceliklendirmesi
**Yapılmayacak:** tam RL (gerekçe §3), erken sembol genişletme

> Karar verilince [[Kararlar-Kaydı]]'na işlenecek.
