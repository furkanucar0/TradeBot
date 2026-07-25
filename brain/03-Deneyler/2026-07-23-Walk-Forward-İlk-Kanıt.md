---
tags: [deney, walk-forward, kanıt]
---

# Walk-Forward İlk Kanıt (2026-07-23, K-31 koşusu)

**Soru:** Mevcut eğitim hattının (21g efektif pencere → haftalık retrain) görülmemiş gelecekte kenarı var mı?

**Yöntem:** 12 katman × 7 gün OOS (Nis sonu → Tem ortası, ~3 ay). Her katmanda "o gün retrain olsaydı" modeli pencereyle eğitildi, sonraki 7 günde test edildi. Ham model sinyali ve ADX-filtreli (canlı zincirin baskın freni, h1_adx≥20) ayrı ölçüldü. Sızıntı yok: etiketler pencere/OOS ayrı, eşik seçimi val'de (K-15 kopyası).

## Sonuç: kenar YOK (bu 3 aylık rejimde)

| | Toplam OOS PnL | İşlem | Pozitif katman |
|---|---|---|---|
| Ham model | **-60.20 USDT** | 839 | 0/12 |
| ADX filtreli | **-49.23 USDT** | 669 | 1/12 |

(100 USDT kasa bazında; katman detayı `reports/walkforward_last.json`.)

## Okumalar

1. **ADX freni gerçekten para kurtarıyor** (+11 USDT fark) ama işareti çevirmiyor. Canlının kalan filtreleri (trend vetosu, OB, SIGNAL_MARGIN+dinamik eşik) burada modellenmedi — kayıpları daha da kırpar ama -49'u artıya çevirmesi zor.
2. **Precision kapısı 12 haftanın 2'sinde alışverişi tamamen kapattı (0 işlem)** — "kenar yoksa işlem yapma" mekanizması çalışıyor; sorun şu ki diğer haftalarda val'de görülen precision OOS'ta tutmuyor (haftalık kalibrasyon çürümesi).
3. **SHORT/LONG ayrımı katmana göre değişiyor** — "SHORT'u kapat" hipotezi 4-katmanlı ilk koşudaki kadar net değil (2, 3, 6, 12. katmanlarda LONG da kaybetti). Tek yönlü kapatma kararına bu veriyle varılamaz.
4. Paper'daki 7 işlem/-0.65 USDT ve mainnet kapısının "hayır"ı artık bağımsız bir ölçümle tutarlı.

## Turnuva sonucu (23.07 gecesi, 12 katman, tek eğitim + varyant değerlendirme)

Ön-kayıtlı hipotezler + kullanıcının 15m grid gözlemi (R_range15m: BB(20,2)+RSI(14) banttan dönüş, SADECE ADX<20 rejimi, SL %0.4 / TP %0.6, tek konfig, tarama yok) aynı OOS haftalarında yarıştı:

| Yarışmacı | 12 hafta OOS | İşlem | + hafta |
|---|---|---|---|
| R_range15m | **-20.29** | 114 | 1/12 |
| H-A_prec10 | -29.03 | 647 | 3/12 |
| H-C_margin7 | -33.44 | 731 | 2/12 |
| temel | -35.42 | 848 | 3/12 |
| H-B_adx25 | -36.72 | 617 | 2/12 |

**Okumalar:**
1. **Hiçbir eşik/filtre ayarı işareti çevirmiyor** — sorun ayar değil, çekirdek kenar. H-A (+%10 precision tabanı) temele göre +6.4 iyileştirme sağlıyor ama yön aynı.
2. **Kayıp ~işlem sayısıyla orantılı** → maliyet baskın: komisyon+slippage gidiş-dönüş ~%0.13, TP %0.6-1.0'ın %13-22'si. 1m scalping'te kenar maliyetin altında.
3. **R_range15m** en az kaybeden ama artı değil (WR ~%30, başabaş ~%46). Kullanıcının grid sezgisinin BU kaba hâli maliyeti yenmiyor; gerçek grid (kademeli emir, envanter, SL'siz) farklı bir hayvan — bu sonuç "range'de para yok" demek DEĞİL, "bu basit versiyon yetmiyor" demek.
4. Varyant OOS'ta tutarlı artıya dönmediği için canlı parametre DEĞİŞMEDİ ("yeşile kadar deneme" yasağı uygulandı).

## H-G sonucu (26.07 koşusu — "precision kapısı olmasaydı?")

Bağlam: 20-26 Tem düşüş haftasında model SHORT'u gördü (proba 0.57-0.60) ama kapı eğitimde SHORT'u kapatmıştı (thr 1.01) → kullanıcı "düşüşte tek short yok" diye sordu. H-G kapıyı 12 hafta OOS'ta tamamen kaldırdı:

| | 12 hafta OOS | İşlem | + hafta |
|---|---|---|---|
| temel (kapılı) | -55.86 | 794 | 0/12 |
| **H-G kapısız** | **-74.04** | 1135 | 0/12 |

**Karar: kapı HAKLI — kaldırılırsa 12 haftada 18 USDT DAHA kaybedilirdi.** Kapısız SHORT sadece 2/12 haftada artı (+4.15, +2.93); kritik olarak **düşüş haftasının kendisinde bile** (18-25 Tem katmanı) kapısız SHORT -0.93 etti: model düşüşü "görmek" ile 1m ölçeğinde maliyet-sonrası kâra çevirmek ayrı şeyler. Kapı canlıda DEĞİŞMEDİ. (Not: koşular arası temel değerleri birkaç USDT oynuyor — veri ucu kaydıkça katman sınırları kayıyor; sıralama kararları tek koşuya değil desene dayandırılmalı.)

Bu turla birlikte çerçeve İÇİ tüm ana ayarlar ölçülmüş oldu (A/B/C/G: hepsi negatif, hiçbiri işaret çevirmiyor) → kalan yol yapısal: H-D (15m), H-E (maker), H-F (grid), dış stratejiler.

## Tur-2 adayları (ön-kayıt bekliyor — kullanıcı seçimi)

Maliyet-baskınlığı bulgusuna doğrudan saldıran hipotezler:
- **H-D · Zaman dilimi yükseltme:** 15m mumlarla etiket/eğitim, SL %1 / TP %2 civarı (maliyet TP'nin ~%6'sına düşer)
- **H-E · Maker giriş simülasyonu:** limit emirle giriş varsayımı (komisyon yarıya) — brain B-4/H-7'nin araştırma modu
- **H-F · Grid-gerçek:** kademeli çift yön emirler, envanter yönetimi (en karmaşık; ayrı motor ister)

İlgili: [[Kararlar-Kaydı]] K-31, [[Model-ve-Eğitim]]
