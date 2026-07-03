---
tags: [strateji]
---

# Karar Zinciri (Canlı Döngü)

Her 30 saniyede, sembol başına:

## 1. Veri hazırlığı
3000 mumluk 1m buffer (REST init + WS/REST akış) + 60 günlük 1d barlar → [[İndikatörler|33 özellik]]. Herhangi biri NaN ise **sinyal yok** (nötr varsayılanla işlem açılmaz).

## 2. Efektif eşik
```
efektif eşik = model eşiği (val'de optimize)
             + SIGNAL_MARGIN (0.07, kalibrasyon kanıtlı)
             + dinamik ayar (volatilite/trend/ADX/F&G)
```
Dinamik ayar bileşenleri: 1h ATR oranının kendi 24s medyanına göre artışı (ceza), trend hizalama 0-3 (±0.038), 1h ADX (±0.03), Korku&Açgözlülük <20 veya >80 (+0.05).
→ Bekleyen karar: ayarın 0 altına inmesinin (bonus) yasaklanması — [[Kararlar-Kaydı]]

## 3. Çift yönlü tahmin
LONG ve SHORT modelleri ayrı proba üretir; eşiği geçen(ler) aday olur. İkisi birden geçerse güçlü olan alınır.

## 4. Sert filtreler (sırayla)
1. **1h ADX < 20** → yatay piyasa, tüm sinyaller iptal
2. **Trend vetosu (güven ölçekli):** sinyal 1h EMA9×21 trendinin aksine ise iptal; **ancak proba eşiği +0.15 aşarsa geçer** — kanıt: [[2026-07-04-Karşı-Trend-Analizi]]
3. **Emir defteri:** bid/ask dengesizliği sinyal aleyhine ±0.15'i aşarsa iptal

## 5. Boyutlandırma ve açılış
[[Risk-Yönetimi]] formülüyle marjin hesaplanır (risk tavanı %0.5), aynı yönde ikinci pozisyon yarım boy, işlem DB'ye yazılır, Telegram bildirimi gider.

## 6. Yönetim
- SL/TP kontrolü cari mumun high/low'u ile her saniye
- Günlük -%1.5 kayıp freni / +%2 kâr kilidi → o gün yeni işlem yok
- Her 20 kapanan işlemde otomatik yeniden eğitim (kayan 45 gün)

İlgili: [[Model-ve-Eğitim]], [[Risk-Yönetimi]]
