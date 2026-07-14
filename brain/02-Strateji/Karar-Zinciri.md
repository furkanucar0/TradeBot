---
tags: [strateji]
---

# Karar Zinciri (Canlı Döngü)

Her 30 saniyede, sembol başına:

## 1. Veri hazırlığı
3000 mumluk 1m buffer (REST init + WS/REST akış) + 60 günlük 1d barlar + funding/OI rolling buffer (5 dk'da bir, K-29) → [[İndikatörler|35 özellik]]. Herhangi biri NaN ise **sinyal yok** (nötr varsayılanla işlem açılmaz; funding/OI eksikse 0.0 nötr dolgu — bloklamaz).

## 2. Efektif eşik
```
efektif eşik = model eşiği (val'de optimize)
             + SIGNAL_MARGIN (0.07, kalibrasyon kanıtlı)
             + dinamik ayar (volatilite/trend/ADX/F&G)
```
Dinamik ayar bileşenleri: 1h ATR oranının kendi 24s medyanına göre artışı (ceza), trend hizalama, 1h ADX, Korku&Açgözlülük. **Ayar 0'ın altına inemez (K-13):** filtreler sadece eler, bonus tabanı asla düşüremez.

## 3. Çift yönlü tahmin
LONG ve SHORT modelleri ayrı proba üretir; eşiği geçen(ler) aday olur. İkisi birden geçerse güçlü olan alınır.

## 4. Sert filtreler (sırayla)
1. **1h ADX < 20** → yatay piyasa, tüm sinyaller iptal
2. **Trend vetosu (güven ölçekli):** sinyal 1h EMA9×21 trendinin aksine ise iptal; **ancak proba eşiği +0.15 aşarsa geçer** — kanıt: [[2026-07-04-Karşı-Trend-Analizi]]
3. **Emir defteri:** bid/ask dengesizliği sinyal aleyhine ±0.15'i aşarsa iptal

## 5. Boyutlandırma ve açılış
[[Risk-Yönetimi]] formülüyle marjin hesaplanır: risk tavanı %0.5 × **işlemin kendi olasılık ölçeği (K-14)** × Kelly × DD ölçeği. Aynı yönde ikinci pozisyon yarım boy. İşlem DB'ye yazılır, Telegram bildirimi gider.

## 6. Yönetim
- SL/TP kontrolü cari mumun high/low'u ile her saniye (REST beslemesi 2 sn — K-13)
- Günlük -%1.5 kayıp freni / +%2 kâr kilidi → o gün yeni işlem yok
- Otomatik yeniden eğitim: **≥20 yeni kapanan işlem VE ≥12 saat ara** (K-13) VEYA **model ≥7 gün eski** (K-29 yaş tetiği — yönsüz piyasada bayatlama önlemi), kayan 45 gün
- UTC gün dönümünde günlük Telegram raporu (K-16)

İlgili: [[Model-ve-Eğitim]], [[Risk-Yönetimi]]
