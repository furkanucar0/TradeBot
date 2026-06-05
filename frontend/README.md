# Frontend Dokümantasyonu

Bu dizin React + Vite + Tailwind tabanlı ön yüz uygulamasını içerir.

## İçerik

- `frontend/src/App.tsx`: Bot kontrol paneli, durum kartları, pozisyon ve trade raporunu gösteren ana bileşen.
- `frontend/src/api.ts`: Backend API çağrılarını yöneten axios tabanlı servis fonksiyonları.
- `frontend/src/styles.css`: Tailwind tabanlı genel stil dosyası.
- `frontend/vite.config.ts`: Vite konfigürasyonu.
- `frontend/package.json`: Uygulama bağımlılıkları ve çalışma scriptleri.
- `frontend/.env.example`: Backend URL yapılandırması için örnek çevresel değişken.

## Kurulum

1. `cd frontend`
2. `npm install`

## Çalıştırma

- `npm run dev`

Uygulama `http://localhost:5173` üzerinde çalışacaktır.

## Notlar

- `frontend/src/api.ts` içindeki `VITE_API_BASE_URL` ortam değişkeni ile backend adresi ayarlanır.
- WebSocket bağlantısı `http://localhost:8000/ws/updates` adresinden durum güncellemelerini alacak şekilde yapılandırıldı.
- Dashboard, açık pozisyonları, kapalı işlemleri ve hızlı trade performans özetini gösterir.
