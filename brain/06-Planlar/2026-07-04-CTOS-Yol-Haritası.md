---
tags: [plan, rapor, ctos]
tarih: 2026-07-04
durum: TAMAMLANDI
---

> 🏁 **CTOS TAMAMLANDI (7/7)** — 1-4: 04.07 (K-17..K-20) · 5+6: 05.07 (K-21, K-22) · 7: 05.07 (K-23 → [[Mainnet-Protokolü]]).
> Bundan sonrası: paper kanıtı biriktirme (100 işlem hedefi) → [[Mainnet-Protokolü]] geçilince /canli. Kâr adayları: [[Kararlar-Kaydı]] B-4.

# CTOS Yol Haritası — 7 Fazın Röntgeni ve Uyarlanmış Plan

Önerilen "Cognitive Trading OS" planı sistemimizle karşılaştırıldı. Sonuç: **~%40'ı zaten inşa edilmiş**, ~%35'i gerçekten değerli yeni iş, ~%25'i yeniden-markalama veya aşırı mühendislik riski.

## ⚠️ Baş uyarı: "Büyük Yeniden Yazım" tuzağı

Plan 4 yeni dosyaya (perception_memory, risk_execution, brain_engine, main_ctos) **komple yeniden yazım** öneriyor. Bu, çalışan ve hatalarını tek tek ayıklayarak stabilize ettiğimiz sistemi çöpe atıp sıfırdan hata ayıklamak demektir — yazılımın bilinen en pahalı tuzağı. Doğrusu: **aynı hedeflere evrimsel refaktörle gitmek** — her faz sonunda bot çalışır durumda kalır, her parça tek başına teslim edilebilir.

## Faz faz röntgen

| CTOS Fazı | Zaten var | Gerçekten yeni ve değerli | Almayacağız / erteliyoruz |
|---|---|---|---|
| **1. Röntgen** | brain/ kasası, features.py birleştirmesi, servisler | **config.py** (sabitler live_trader+train_engine'de mükerrer!), ölü kod temizliği | Klasör yapısını komple değiştirme |
| **2. Algı+Sağlık** | Veri hattı, buffer'lar, REST/WS, tüm göstergeler | **HealthMonitor + Health Score** (DD, ardışık kayıp, WR trendi tek skorda; dashboard+Telegram'a) | Veri katmanını yeniden yazma |
| **3. Risk duvarı** | Günlük -%1.5/+%2 fren, işlem başı %0.5, DD ölçeği, kaldıraç kademesi, korelasyon, mainnet kilidi — **hepsi çalışıyor** | **RiskGate sınıfı** (dağınık kontrolleri TEK veto noktasında topla) + **Kill Switch** (/panik: tümünü kapat+durdur+elle kurma şartı) | Ardışık-zarar tavanı (günlük fren ~3 SL'de zaten devreye girer — mükerrer) |
| **4. Beyin** | Model zaten olasılıksal; EV-bazlı eşik (K-15); rejim bilgisi modelin İÇİNDE (h1_adx importance %22.9!) | **Reason Codes**: her karar yapılandırılmış gerekçeyle loglansın (analiz edilebilir) | Ayrı rejim sınıflandırıcısı — az veriyle yeni tuning yükü; model bunu zaten öğreniyor. Faz 2 kanıtı sonrası tekrar değerlendirilir |
| **5. Hafıza (MFE/MAE)** | Öz-analiz eventi (rolling WR) var ama sığ | ⭐ **MFE/MAE takibi** — işlem boyunca lehte/aleyhte en uç hareket kaydı → "stop dar mı, TP uzak mı" sorusuna VERİ ile cevap. Fiyat beslemesi zaten saniyelik: ucuz. + kapanışta öz-değerlendirme kaydı | — |
| **6. Evrim** | Otomatik retrain (12s+20 işlem korumalı) | ⭐ **Champion vs Challenger** — retrain, yeni modeli ancak mevcut şampiyonu DOĞRULAMADA yenerse canlıya alır. Şu an her retrain modeli körlemesine eziyor → [[Pencere-Hassasiyeti]] sorunumuzun doğrudan ilacı | Concept-drift ML'i — basit vekili yeterli: paper rolling WR, val beklentisinin altına düşerse alarm |
| **7. Shadow→Mainnet** | **Shadow mode = paper modumuz, birebir aynı tanım** (canlı veri, sanal kasa, emir yok) — plan yazarı bunu bilmiyordu | Mainnet geçiş **kontrol listesi**: N≥100 işlem, WR güven aralığı, günlük metrik eşikleri — "paper'a sabır" ilkesinin resmileşmesi | — |

## Uyarlanmış faz planı (onaya sunulan)

Her faz bağımsız teslim, bot hep çalışır durumda, her biri sonunda test onayı istenir:

- **FAZ 1 — Temel:** `config.py` (tüm sabitler tek yerde, iki dosyadaki mükerrer LEVERAGE/RISK biter) + ölü kod temizliği + bu rapor. *Efor: küçük*
- **FAZ 2 — Sağlık Katmanı:** `health.py` — Health Score (0-100: DD, ardışık kayıp, günlük PnL, WR trendi, veri tazeliği) + Market Snapshot eventi → dashboard kartı + Telegram `/health`. *Efor: orta*
- **FAZ 3 — Risk Duvarı:** `risk_gate.py` — mevcut TÜM risk kontrollerini tek veto sınıfına taşı (davranış birebir aynı, mimari tekilleşir) + `/panik` kill switch + Health Score < eşik → otomatik duraklat. *Efor: orta*
- **FAZ 4 — Reason Codes:** her sinyal kararı yapılandırılmış gerekçeyle (`{signal, blocked_by, ev, proba, thr}`) DB'ye/loga; dashboard'da "neden işlem yok" paneli. *Efor: küçük-orta*
- **FAZ 5 — MFE/MAE Hafızası:** ⭐ trades tablosuna mfe/mae kolonları, açık pozisyonda uç fiyat takibi, kapanışta öz-değerlendirme ("SL yedi ama MFE 0.8×TP'ye ulaşmıştı → stop dar" tipi sayısal etiket) + haftalık özet analizi. *Efor: orta* — **en yüksek bilgi getirisi**
- **FAZ 6 — Champion vs Challenger:** ⭐ retrain akışı: challenger'ı eğit → ortak doğrulama diliminde şampiyonla kıyasla → ancak anlamlı iyiyse model.bin'i değiştir; değilse şampiyon kalır + kayıt düş. *Efor: orta* — **en yüksek güvenlik getirisi**
- **FAZ 7 — Mainnet Protokolü:** kontrol listesi + shadow (paper) kanıt raporu şablonu + mainnet açılışının Telegram onaylı prosedürü. *Efor: küçük*

Sıra önerisi: 1 → 2 → 3 → 5 → 6 → 4 → 7 (MFE/MAE ve C-v-C, reason codes'tan daha acil bilgi/güvenlik üretir; istenirse plandaki sıra da olur).

## Yapılmayacaklar (gerekçeli)

1. Komple yeniden yazım / dosya yeniden adlandırma — çalışan sistemi bozar, servisler kırılır
2. Ayrı rejim sınıflandırıcısı (şimdilik) — model zaten rejimi 1h/1d özelliklerden öğreniyor; az veriyle yeni katman = yeni overfit yüzeyi
3. Ardışık-zarar tavanı — günlük fren zaten ~3 SL'de tetikleniyor (R-2 kararıyla tutarlı)
4. Concept-drift ML kütüphanesi — rolling WR vekili yeterli, kanıt birikince bakılır

> Onay gelince faz faz ilerlenecek; her fazın sonunda test onayı istenir, komut gelmeden sonraki faza geçilmez. Kararlar [[Kararlar-Kaydı]]'na işlenecek.
