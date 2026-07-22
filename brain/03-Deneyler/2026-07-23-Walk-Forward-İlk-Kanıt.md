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

## Sonraki adım adayları (ön-kayıtlı hipotezler — çoklu-karşılaştırma tuzağına dikkat)

Aynı 12-katman düzeneğinde, HERBİRİ ÖNCEDEN İLAN EDİLİP tek seferde test edilecek:
- H-A: precision tabanı +%5 → +%10 (daha az ama daha isabetli işlem)
- H-B: ADX tabanı 20 → 25 (yalnızca güçlü trendde)
- H-C: araştırma eşiğine canlıdaki SIGNAL_MARGIN(+0.07) eklenmesi (canlı seçiciliğin tam simülasyonu)
- Varyant OOS'ta tutarlı artıya dönmüyorsa canlı parametre DEĞİŞMEZ; "yeşile kadar deneme" yasağı burada da geçerli.

İlgili: [[Kararlar-Kaydı]] K-31, [[Model-ve-Eğitim]]
