# TradeBot

Bu proje, React tabanlı bir web panel ile yönetilen, Python/FastAPI backend ve Binance verisiyle çalışacak bir kripto scalping trading botu prototipidir.

## Klasör yapısı

- `backend/`: Python backend servisi
  - `backend/app/`: Bot modülleri, veri çekme, model ve API
  - `backend/run.py`: FastAPI uygulamasını başlatmak için run script
  - `backend/requirements.txt`: Python bağımlılıkları
  - `backend/README.md`: Backend bileşenlerinin dokümantasyonu
- `frontend/`: React + Vite + Tailwind ön yüzü
  - `frontend/README.md`: Frontend bileşenlerinin dokümantasyonu

## Kurulum

### Backend

1. `cd backend`
2. `python -m venv .venv`
3. `.venv\Scripts\Activate.ps1` veya `source .venv/bin/activate`
4. `pip install -r requirements.txt`
5. `.env.example` dosyasını kopyalayın ve `BINANCE_API_KEY` / `BINANCE_API_SECRET` değerlerini ekleyin.

### Frontend

1. `cd frontend`
2. `npm install`

## Çalıştırma

### Backend

- `cd backend`
- `python run.py`

Uygulama `http://localhost:8000` adresinde çalışacaktır.

### Frontend

- `cd frontend`
- `npm run dev`

### Ayrı PowerShell pencerelerinde çalıştırma

1. Bir PowerShell penceresinde:
   - `.
un-backend.ps1`
2. Diğer PowerShell penceresinde:
   - `.
un-frontend.ps1`

Backend konsolunda FastAPI ve bot döngüsü loglarını göreceksiniz.
Frontend tarayıcı ekranında canlı durum güncellemelerini ve web socket tabanlı log akışını izleyebilirsiniz.

## Notlar

- Bu ilk aşamada bot, gerçek emir yerine paper trading simülasyonuyle çalışacak.
- Model dosyası `backend/model.bin` olarak saklanır.
- API anahtarları `.env` içinde tutulmalıdır.
