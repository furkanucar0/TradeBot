---
tags: [index]
---

# 🧠 Bot Beyni — Ana Harita

Bu kasa, futures scalping botunun **kalıcı hafızası**: mimari, strateji mantığı, yapılan deneyler, alınan kararlar ve bilinen kısıtlar. Kod "ne yapıldığını" söyler; burası **neden yapıldığını** söyler.

## Bölümler

### 🏗 Mimari
- [[Sistem-Mimarisi]] — bileşenler, portlar, veri akışı
- [[Servisler-ve-Operasyon]] — Windows hizmetleri, Telegram komutları, loglar

### 📐 Strateji
- [[Karar-Zinciri]] — sinyalden işleme adım adım canlı mantık
- [[İndikatörler]] — 33 özellik ve hangilerinin gerçekten iş yaptığı
- [[Model-ve-Eğitim]] — LightGBM/XGBoost, etiketleme, veri disiplini
- [[Risk-Yönetimi]] — katman katman koruma mimarisi

### 🔬 Deneyler (kanıt arşivi)
- [[Eğitim-Günlüğü]] — her eğitimin otomatik kaydı ⚙️
- [[2026-07-03-RR-Bandı-Deneyi]] — R:R kısıtlama denemesi ve neden geri alındığı
- [[2026-07-03-Kalibrasyon-Kanıtı]] — proba dilimi → gerçek isabet tablosu
- [[2026-07-04-Karşı-Trend-Analizi]] — trend vetosunu delme kuralının doğrulanması
- [[Pencere-Hassasiyeti]] — backtest'in en önemli sınırı

### ⚖️ Kararlar
- [[Kararlar-Kaydı]] — alınan/reddedilen/bekleyen tüm kararlar ve dayanakları

### 🗺 Planlar
- [[2026-07-04-Kâr-Marjı-Raporu]] — ödül mantığı analizi + yükseltme hamleleri (karar bekliyor)

### ⚠️ Kısıtlar
- [[Ağ-ve-Ortam-Kısıtları]] — WebSocket engeli, Task Scheduler tuzakları

## Altın Kurallar

1. **Test setine göre model seçme.** "Yeşil rapor gelene kadar retrain" = sızıntıyı geri getirmek. → [[Pencere-Hassasiyeti]]
2. **Kör tavsiye uygulama, önce ölç.** Her strateji değişikliği bir deney notuna dayanmalı. → [[2026-07-04-Karşı-Trend-Analizi]]
3. **Asıl hakem paper sonuçlarıdır**, backtest değil.
4. **Filtreler eler, kolaylaştırmaz** (bonus tartışması → [[Kararlar-Kaydı]]).
