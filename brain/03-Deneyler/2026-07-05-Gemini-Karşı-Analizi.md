---
tags: [analiz, karşı-analiz, dış-eleştiri]
tarih: 2026-07-05
durum: kapatıldı
---

# Gemini Eleştirisi — Karşı-Analiz (05.07)

Dış eleştiri (Gemini) panele bakarak 3 acil müdahale önerdi; kanıtlarla değerlendirildi, Gemini değerlendirmeyi kabul edip geri adım attı. Sonuç: **koda dokunulmadı** — mevcut duruş (kanıt biriktirme) doğrulandı.

## Kabul edilen ortak zemin
- Modelin henüz kanıtlanmış edge'i YOK (7 ardışık negatif test) — ama "kanama" da yok: paper-only + mainnet kilidi (K-23) + C-v-C (K-22) tam da bunun için var. Paper = veri toplama.
- **Asıl teşhis:** sorun filtre eksikliği değil; 45 günlük pencerede öğrenilebilir istikrarlı sinyalin zayıf olması (concept drift) olabilir. Cevap: N≥50 paper işlemde rolling WR val beklentisinin altındaysa B-4 yapısal adayları (walk-forward H-6, sembol genişletme H-5).

## Çürütülen iddialar (kanıtla)
| İddia | Gerçek |
|---|---|
| "Başabaş %33.3, WR %26.9 → kanama" | Maliyet-dahil başabaş **%40** — zaten tüm kapılar buna göre. Test WR ≠ canlı davranış: canlı zincir (SIGNAL_MARGIN + vetolar) testten daha seçici; kalibrasyon: ≥0.55 dilimleri %63-83 WR. Test dilimi penceresi gürültülü → [[Pencere-Hassasiyeti]] |
| "WS kopması → gecikme → dar stop patlar" | Mainnet'te SL/TP **borsa tarafında** reduceOnly stop_market — istemci gecikmesi çıkışı etkilemez. WS bu ağda zaten hiç veri akıtmıyor (ISS filtresi, belgeli) → REST 2sn ASIL kaynak, tasarım gereği → [[Ağ-ve-Ortam-Kısıtları]] |
| "Exponential backoff ekleyin" | 04.07'de eklendi (3sn→5dk tavan) |
| "Accuracy %64 yanıltıcı, F1 kötü" | Doğru ama bilinen: hiçbir kararda accuracy/F1 kullanılmıyor (K-15: val-EV) |
| "Sabit %70 güven eşiği" | R-1'in tekrarı — proba skalası eğitimler arası kayar, kalibre değil; göreli eşik + SIGNAL_MARGIN 0.07 + proba-ölçekli boyut (K-14) aynı hedefi kanıtla sağlıyor |

## Veri-tetikleyicili bekleyenlere dönüştürülenler
- ATR-ölçekli dinamik SL/TP → **B-5** (tetik: ≥30 SL örneğinde STOP_DAR oranı; FAZ 5 verisi)
- ADX tabanı 20→25 → **B-6** (tetik: decisions tablosunda ADX-dilimi × sonuç analizi)

Ders (kalıcı): dış tavsiye geldiğinde sıra hep aynı — **iddia → brain'deki kanıtla kıyas → ya çürüt ya veri-tetikleyicili bekleyene çevir; asla panele bakıp doğrudan koda dokunma.**

İlgili: [[Kararlar-Kaydı]], [[2026-07-04-Karşı-Trend-Analizi]], [[Risk-Yönetimi]]
