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
   - `./run-backend.ps1`
2. Diğer PowerShell penceresinde:
   - `./run-frontend.ps1`

Backend konsolunda FastAPI ve bot döngüsü loglarını göreceksiniz.
Frontend tarayıcı ekranında canlı durum güncellemelerini ve web socket tabanlı log akışını izleyebilirsiniz.

## Yerel ZIP veri yükleme

- `backend/zip_loader.py` ile `backend/zips/` klasöründeki `.zip` dosyalarını SQLite veritabanına aktarabilirsiniz.
- ZIP dosya adı formatı örneği: `BTCUSDT-5m-2024-06.zip`
- Her ZIP içinde en az bir CSV olmalı. CSV sütunları `timestamp`, `open`, `high`, `low`, `close`, `volume` veya eşdeğer başlıklar içermelidir.
- Çalıştırmak için:
  - `cd backend`
  - `python zip_loader.py`

## Notlar

- Bu ilk aşamada bot, gerçek emir yerine paper trading simülasyonuyle çalışacak.
- Model dosyası `backend/model.bin` olarak saklanır.
- API anahtarları `.env` içinde tutulmalıdır.

## VPS Dağıtımı (Docker)

4 servis (backend, fetcher, telegram, frontend) Docker ile tek komutla ayağa kalkar. Detaylı mimari: `brain/01-Mimari/Dağıtım-Docker.md`.

**Sunucuda ilk kurulum:**

```powershell
git clone <repo-url> Bot
cd Bot
copy .env.docker.example .env.docker
notepad .env.docker   # BINANCE_*, TELEGRAM_*, API_KEY (rastgele üret), CORS_EXTRA_ORIGINS, VITE_API_BASE_URL doldur
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d
```

**Veriyi taşıma** (mevcut makineden, ilk kurulumda bir kez): `backend/bot.sqlite`, `backend/model.bin`, `backend/reports/` klasörünü sunucudaki aynı yollara kopyalayın (repo klonlandıktan, container'lar başlamadan önce).

**Güvenlik — mutlaka yapın:** API_KEY sadece rastgele tarayan botlara karşı bir eşiktir, gerçek erişim kontrolü değildir. Sunucunun güvenlik duvarında (Windows Firewall / bulut sağlayıcının güvenlik grubu) **8000 ve 5173 portlarını yalnızca kendi IP adresinize açın** — tüm internete açık bırakmayın.

**Durum kontrolü:** `docker compose ps` · **Loglar:** `docker compose logs -f backend` · **Güncelleme:** `git pull` → `docker compose up -d --build` · **Durdurma:** `docker compose down`

Yerel Windows geliştirme akışı (Task Scheduler, `install-services.ps1`) değişmedi — iki model paralel var olabilir.
