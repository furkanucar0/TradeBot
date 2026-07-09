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

`/baslat` hepsi · `/backend` `/fetcher` `/frontend` `/paper` `/train` tekil · `/durdur` hepsi · `/durdur_bot` sadece bot · `/status` durum

⚠️ Hizmet kuruluyken telegram_bot bileşenleri **schtasks üzerinden** yönetir. Backend'i asla `taskkill` ile öldürme — Task Scheduler "çöktü" sanıp geri getirir; temiz kapatma `/shutdown` endpoint'idir (çıkış kodu 0 → restart tetiklenmez).

## Sık işlemler

- **Backend'i yeni kodla başlatma:** `schtasks /end /tn TradingBotBackend` → `schtasks /run /tn TradingBotBackend` → `POST /bot/start?testnet=true`
- **Eğitim:** `POST /train` (varsayılan son 45 gün; `?days=0` tüm veri) veya Telegram `/train`
- **Mum boşluğu doldurma:** scratchpad'deki `backfill_gaps.py` deseni — DB'deki >1 dk boşlukları REST'ten tamamlar

İlgili: [[Sistem-Mimarisi]], [[Ağ-ve-Ortam-Kısıtları]]
