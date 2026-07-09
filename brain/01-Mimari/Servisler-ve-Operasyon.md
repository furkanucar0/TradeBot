---
tags: [mimari, operasyon]
---

# Servisler ve Operasyon

> **Bu sayfa yerel Windows geliştirme ortamını anlatır.** VPS/üretim dağıtımı Docker'a taşındı (05.07, K-24) → [[Dağıtım-Docker]]. İki model paralel var olabilir: yerelde geliştir/test et, VPS'te çalıştır.

## Windows Görev Zamanlayıcısı Hizmetleri

| Görev | Çalıştırdığı | Log |
|---|---|---|
| TradingBotBackend | api.py (bot dahil) | `backend/logs/api.log` |
| TradingBotFetcher | live_fetcher.py | `backend/logs/live_fetcher.log` |
| TradingBotTelegram | telegram_bot.py | `backend/logs/telegram_bot.log` |
| TradingBotFrontend | Vite dev sunucusu | `backend/logs/frontend.log` |

Özellikler: oturum açılışında otomatik başlar, çökünce 1 dk sonra yeniden başlar (999 kez), pilde çalışır, loglar 5 MB'da döner.

- **Kur:** `install-services.ps1` · **Kaldır:** `uninstall-services.ps1`
- Sarmalayıcı: `backend/run_service.py` — çocuğu kill-on-close **Job Object**'e atar (öksüz süreç birikmez, bkz. [[Ağ-ve-Ortam-Kısıtları]])
- Durum: `Get-ScheduledTask -TaskName 'TradingBot*' | ft TaskName, State`

## Telegram Komutları

> VPS'te (Docker, `DOCKER_MODE=true`) `/backend /fetcher /frontend /durdur /durdur_front` komutları artık işlem YAPMAZ — sadece bilgi/yönlendirme mesajı döner, çünkü her bileşen kendi container'ında `restart: unless-stopped` ile zaten 7/24 çalışır. Yerel Windows'ta (hizmet kuruluysa) bu komutlar hâlâ schtasks üzerinden gerçek başlat/durdur yapar.

| Komut | Ne yapar | Ne zaman kullanılır |
|---|---|---|
| `/paper` | Paper (sanal kasa) trade botunu başlatır | Eğitim bitti, canlı izlemeye geçmek istiyorsun |
| `/durdur_bot` | Sadece trading döngüsünü durdurur — API/veri toplama devam eder | Bakım öncesi, veya botu geçici durdurmak için |
| `/status` | Bot çalışıyor mu, açık pozisyonlar + anlık K/Z, son eğitim WR/R:R, son 5 işlem PnL | Günlük hızlı kontrol |
| `/health` | 0-100 sağlık skoru + 5 bileşenin çubuk grafiği (düşüş, ardışık zarar-kes, günlük PnL, WR trendi, veri tazeliği) | Skor <40 olunca bot otomatik duraklar — nedenini görmek için |
| `/train` | Son 45 gün ile yeniden eğitir; Şampiyon-Aday kıyası otomatik | Manuel eğitim tetiklemek istediğinde (otomatik olan zaten var: her 20 işlemde) |
| `/panik` | 🚨 Pozisyonları kapat + botu durdur + kilitle (restart'a dayanıklı) | Acil durum — piyasa çılgınlaştı, botu ANINDA durdurmak istiyorsun |
| `/panik_kaldir` | Panik kilidini kaldırır (bot otomatik başlamaz) | Panik sonrası, tekrar çalıştırmaya hazır olduğunda |
| `/mainnet_check` | 8 maddelik gerçek-para geçiş kontrol listesi | Paper'da ne kadar ilerlediğini görmek için |
| `/canli` → `/canli_onay` | Gerçek para açılışı, iki adımlı (5 dk onay penceresi) | 8/8 madde geçildiğinde, gerçek paraya geçerken |
| `/backend` `/fetcher` `/frontend` | Docker'da: sadece durum bilgisi. Windows'ta: gerçekten başlatır | Servisin ayakta olup olmadığını hızlı kontrol |
| `/durdur` `/durdur_front` | Docker'da: yönlendirme mesajı (`docker compose down/stop` kullanmanı söyler). Windows'ta: gerçekten durdurur | — |
| `/help` | Bu listeyi Telegram'da gösterir | — |

⚠️ **Yerel Windows'ta** (hizmet kuruluyken): backend'i asla `taskkill` ile öldürme — Task Scheduler "çöktü" sanıp geri getirir; temiz kapatma `/shutdown` endpoint'idir (çıkış kodu 0 → restart tetiklenmez).

## Sık işlemler

- **Backend'i yeni kodla başlatma:** `schtasks /end /tn TradingBotBackend` → `schtasks /run /tn TradingBotBackend` → `POST /bot/start?testnet=true`
- **Eğitim:** `POST /train` (varsayılan son 45 gün; `?days=0` tüm veri) veya Telegram `/train`
- **Mum boşluğu doldurma:** scratchpad'deki `backfill_gaps.py` deseni — DB'deki >1 dk boşlukları REST'ten tamamlar

İlgili: [[Sistem-Mimarisi]], [[Ağ-ve-Ortam-Kısıtları]]
