---
tags: [deney]
tarih: 2026-07-03
sonuç: geri-alındı
---

# R:R Bandı Deneyi — Kısıtla ve Geri Al

**Hipotez:** R:R'ı 2.0-2.5'e kısıtlamak "sık küçük kazanç" profili yaratıp varyansı düşürür.

## Sonuçlar (hepsi 45 günlük pencere, temiz test seti)

| Konfig | Seçilen SL/TP | Test WR | Başabaş | PnL | Karar |
|---|---|---|---|---|---|
| R:R serbest (dün) | 0.3/1.2 (4.0) | %31.2 | %25.3 | **+13.76** ✓ | |
| R:R serbest (dün, 2. kez) | 0.3/1.2 (4.0) | %30.9 | %25.3 | **+19.68** ✓ | |
| R:R ≤ 2.5 | 0.3/0.6 (2.0) | %40.3 | %42.2 | -10.00 ✗ | |
| R:R ≤ 2.5 + maliyet-farkında skor | 0.3/0.6 (2.0) | %41.0 | %42.2 | -8.49 ✗ | |
| R:R ≤ 4.0 + eski skor | 0.5/1.0 (2.0) | %36.1 | %38.7 | -5.03 ✗ | pencere de kaymıştı |

## Öğrenilenler

1. **Dar SL/TP'de maliyet kenarı yutuyor:** %0.10 gidiş-dönüş maliyet, %0.6'lık TP'nin %17'si — başabaş WR %42.2'ye çıkıyor ve model bunu out-of-sample tutamıyor.
2. **Modelin kenarı momentum modunda:** "%1.2 koşacak hareketi %0.3 geri çekilmeden önce yakala" sorusunda kenar var; küçük 2:1 salınımlarda yok.
3. **Taban-istatistik (etiket bazlı WR/EV) ile kombo seçmek kırılgan** — pencere kaydıkça oynuyor. Kanıtlanmış skor: `wr² × rr`.
4. Varyans kontrolü R:R'dan değil [[Risk-Yönetimi]] katmanlarından gelir.

**Nihai karar:** MAX_RR = 4.0 (kısıt kaldırıldı), tüm risk katmanları korundu. → [[Kararlar-Kaydı]] K-7

⚠️ Bu tabloyu okurken [[Pencere-Hassasiyeti]] notunu unutma: son üç satırın negatifliğinde pencere kaymasının da payı var.
