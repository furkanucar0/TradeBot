---
tags: [kısıtlar, ortam]
---

# Ağ ve Ortam Kısıtları

Bu makineye/ağa özgü, **kod hatası olmayan** kalıcı gerçekler. Yeni bir "neden çalışmıyor" araştırmasına başlamadan önce burayı oku.

## 1. Binance WebSocket market datası AKMIYOR ⚠️
- Bağlantı kurulur, SUBSCRIBE ACK gelir, ama kline frame'leri **hiç gelmez** (path-based ve subscribe-based ikisi de denendi, 2026-07-03).
- Muhtemel neden: ISS/bölge filtresi. REST (fapi.binance.com) sorunsuz.
- Çözüm: `live_trader._rest_price_loop` — 5 sn'lik REST fiyat beslemesi. **Bunu kaldırma!** WS paralel durur; başka ağda çalışırsa hızlı tick sağlar.
- Botun tarihinde hiç işlem olmamasının üç nedeninden biri buydu (diğerleri: K-3 eşik bug'ı, tam-veri eğitimi).

## 2. Task Scheduler tuzakları
- **Pil:** Varsayılan ayar "pilde başlatma" — görevler Queued'da takılır. `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries` şart (laptop!).
- **Süreç öldürme:** `taskkill` ile öldürülen görev "çöktü" sayılır → 1 dk sonra otomatik geri gelir. Temiz durdurma: `/shutdown` endpoint'i (çıkış 0) veya `schtasks /end`.
- **Öksüz süreçler:** `schtasks /end` çocukları öldürmeyebiliyordu → `run_service.py` çocuğu kill-on-close **Job Object**'e atar. Bu satırları kaldırma.
- **venv shim'leri:** `.venv\Scripts\python(w).exe` başlatıcı kabuktur, gerçek yorumlayıcıyı çocuk olarak açar → servis başına 2 pythonw + 2 python görünür. **6+6 süreç = 3 servis, normal.**

## 3. Veri özellikleri
- 1d MTF özellikleri ≥21 gün ister → kısa `--days` değerleri (≤25) TÜM satırları dropna'ya kaptırır, eğitim "veri yok" der.
- Binance REST klines tek istekte maks 1500 mum → `_fetch_ohlcv` sayfalar; buffer 3000.
- live_fetcher her turda son 4 kapanmış mumu yazar (tekil mum kaçırma telafisi, INSERT OR REPLACE idempotent).
- Mum boşluğu tespiti/doldurması: timestamp'ler arası >60000 ms taraması + REST backfill deseni.

## 4. Konsol
- Windows konsolu cp1254: Türkçe/özel karakter basan scriptlerde `PYTHONIOENCODING=utf-8` kullan.
