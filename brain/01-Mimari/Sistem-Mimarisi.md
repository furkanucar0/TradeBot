---
tags: [mimari]
---

# Sistem Mimarisi

## Bileşenler

| Bileşen | Dosya | Görev | Port |
|---|---|---|---|
| Backend API | `backend/api.py` | FastAPI + WebSocket/SSE event bus; eğitim ve bot start/stop | 8000 |
| Canlı Trader | `backend/live_trader.py` | Paper/canlı işlem motoru (backend içinde thread) | — |
| Eğitim Motoru | `backend/train_engine.py` | Grid search + model eğitimi + backtest + rapor | — |
| Mum Toplayıcı | `backend/live_fetcher.py` | Dakikada bir kapanan 1m mumları DB'ye yazar | — |
| Telegram | `backend/telegram_bot.py` | Uzaktan kontrol (süreç yönetimi + bot komutları) | — |
| Frontend | `frontend/` (Vite/React) | Dashboard: canlı akış, grafik, metrikler, kasa | 5173 |
| Özellikler | `backend/features.py` | **TEK özellik kaynağı** — eğitim ve canlı aynı kodu kullanır | — |
| Konfig | `backend/config.py` | **TEK ayar kaynağı** (K-17) — tüm sabitler; mükerrer tanım yasak | — |
| Sağlık | `backend/health.py` | 0-100 Health Score (K-18) — 15 sn'de bir yayın, /health, Telegram /health | — |
| Veritabanı | `backend/bot.sqlite` | 3 tablo: historical_market_data, trades, model_runs | — |

## Veri Akışı

```
Binance REST ──► live_fetcher ──► SQLite ──► train_engine ──► model.bin
                                     │                            │
Binance REST/WS ──► live_trader ◄────┴────────────────────────────┘
                        │
                        ├──► trades tablosu (paper/canlı işlemler)
                        ├──► Telegram bildirimleri
                        └──► WS/SSE event bus ──► Frontend
```

## Kritik tasarım kararları

- **Tek özellik kaynağı:** `features.py` hem eğitimde hem canlıda kullanılır → train/serve kayması yok (doğrulandı: 33 özelliğin 31'i <%2 fark). Yeni özellik SADECE buraya eklenir.
- **`ready_for_live` tek doğruluk kaynağı:** train_engine hesaplar, `backtest_summary.json`'a yazar; api.py oradan okur.
- **Canlı fiyat:** WS + 5 sn REST yedeği (bkz. [[Ağ-ve-Ortam-Kısıtları]] — bu ağda REST asıl kaynak).
- **Mainnet kilidi:** dinamik WR hedefi + R:R≥2 + pozitif EV + Sharpe≥0.5 + MaxDD≤%25 sağlanmadan gerçek para açılmaz.

İlgili: [[Servisler-ve-Operasyon]], [[Karar-Zinciri]]
