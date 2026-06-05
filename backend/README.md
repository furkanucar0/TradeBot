# Backend Dokümantasyonu

Bu dizin FastAPI tabanlı backend servisini ve bot altyapısını içerir.

## İçerik

- `backend/app/data_fetcher.py`: Binance API'den async olarak geçmiş OHLCV verisi çeker ve RSI, MACD, Bollinger Bands gibi teknik indikatörleri hesaplayıp makine öğrenmesi için feature hazırlığı yapar.
- `backend/app/database.py`: Async SQLite yönetimi ve tablo şemaları. `market_data`, `market_features`, `trade_history`, `model_training_runs` ve `bot_logs` tablolarını içerir.
- `backend/app/ai_engine.py`: XGBoost / LightGBM modeli oluşturma, eğitim, kaydetme, yükleme ve tahmin fonksiyonları.
- `backend/app/execution_engine.py`: Pozisyon açma, stop-loss / take-profit kontrolü ve PnL hesaplama için paper trading motoru.
- `backend/app/bot.py`: Bot döngüsü, veri çekme, tahmin etme, pozisyon açma ve yeniden eğitim tetikleme işlemlerini yönetir.
- `backend/app/api.py`: FastAPI servisleri, WebSocket yayınları, bot start/stop fonksiyonları ve durum endpointleri.
- `backend/run.py`: Uvicorn ile backend sunucusunu başlatmak için çalıştırılabilir script.
- `backend/requirements.txt`: Backend için gerekli Python paketleri.

## Kurulum

1. `cd backend`
2. `python -m venv .venv`
3. `.venv\Scripts\Activate.ps1` veya `./.venv/Scripts/activate` (PowerShell)
4. `pip install -r requirements.txt`
5. `.env.example` dosyasını kopyalayın ve `BINANCE_API_KEY`, `BINANCE_API_SECRET` değerlerini ekleyin.

## Çalıştırma

- `python run.py`

Servis `http://localhost:8000` üzerinde çalışacaktır.

## Notlar

- İlk aşamada gerçek emirler yerine paper trading simülasyonu kullanılacak.
- Model `backend/model.bin` dosyasında saklanır.
- `backend/app/api.py` WebSocket endpointi `/ws/updates` yoluyla anlık durum güncellemeleri yayınlar.
- `backend/app/bot.py` her 30 saniyede bir döngü çalıştıracak şekilde tasarlandı.
