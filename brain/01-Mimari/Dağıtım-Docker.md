---
tags: [mimari, docker, dağıtım, vps]
---

# Dağıtım — Docker / VPS (K-24, K-25, K-26)

VPS: `45.155.124.53`, **Ubuntu 24.04 LTS** (native), 4 servis — eski Task Scheduler görevlerinin (TradingBotBackend/Fetcher/Telegram/Frontend) Docker karşılığı.

## Windows Server → Ubuntu pivotu (önemli ders)

VPS başlangıçta **Windows Server/11 Pro** olarak alınmıştı. Docker'ın Linux container'ları çalıştırabilmesi için WSL2 gerekiyordu; bu yol ciddi sürtünmeyle sonuçlandı:
- `wsl --update` / `wsl --install`, SSH (OpenSSH Server) üzerinden çalıştırılınca **"A specified logon session does not exist"** hatasıyla tutarlı şekilde başarısız oldu — MSIX/Store paket kurulumu SSH'ın oluşturduğu oturum türünü (network logon) desteklemiyor, gerçek interaktif (RDP/konsol) oturum şart. Scheduled Task (SYSTEM hesabıyla) ile bypass denendi, o da askıda kaldı.
- Docker Desktop kurulsa bile arka planının 7/24 çalışması için ya sürekli bir oturumun açık kalması ya da `AutoAdminLogon` (Administrator şifresini registry'ye DÜZ METİN yazmak) gerekiyordu — bu **güvenlik sınıflandırıcısı tarafından haklı olarak reddedildi** ve kullanıcıya soruldu.
- Kullanıcı kararı: **VPS sağlayıcıdan Ubuntu 24.04'e format atıldı.** Sonuç: `apt install docker.io` benzeri tek adımlı kurulum, SSH üzerinden hiçbir interaktif oturum kısıtı olmadan tam otomasyon, WSL2/Docker Desktop/AutoAdminLogon sorunlarının tamamı ortadan kalktı.

**Ders:** Docker container'ları %100 Linux tabanlıysa (bu projede öyle), hedef VPS'i baştan Linux seçmek — Windows+WSL2 katmanına hiç girmemek — çok daha az sürtünmeli. Windows sadece hedef ortam gerçekten Windows-native bir iş yükü gerektiriyorsa tercih edilmeli.

## Repo transferi: git değil, SFTP arşivi

Yerel repoda CTOS fazlarının ve Docker paketlemesinin tamamı **commit edilmemişti** (brain-workflow kuralı: kullanıcı istemeden commit atılmaz). Bu yüzden sunucuda `git clone` GitHub'daki eski sürümü getirirdi. Çözüm: `backend/`, `frontend/` (node_modules hariç), `brain/`, `docker-compose.yml`, `.env.docker.example`, `README.md` içeren bir `tar.gz` (~39 MB, `bot.sqlite` 104 MB'tan sıkışarak) yerelde oluşturulup SFTP ile `/opt/bot`'a yüklendi, orada açıldı. `backend/zips/` (46 MB, veri zaten içeri aktarılmış) ve `frontend/node_modules/` (145 MB, Docker build'de yeniden kurulacak) hariç tutuldu.

## Mimari tercih: kod imajda değil, bind-mount

`backend/Dockerfile` sadece Python + kütüphaneleri kurar. Gerçek kod ve veri (`bot.sqlite`, `model.bin`, `reports/`, `.env.docker`, `brain/`) **repo kökünün tamamının bind-mount edilmesiyle** gelir:

```yaml
volumes:
  - .:/workspace
working_dir: /workspace/backend
```

**Neden:** Kod içinde `../.env`, `../brain/03-Deneyler/...`, `bot.sqlite` gibi onlarca göreli yol varsayımı var. Container içindeki dizin yapısını yerel geliştirmeyle BİREBİR aynı tutmak sıfır kod-yolu riski demek. Kod güncellemesi = güncel arşivi tekrar SFTP'le + `docker compose up -d --force-recreate`, imaj yeniden build gerekmez (kütüphaneler değişmediyse).

Frontend istisna: statik SPA, çalışma zamanı verisi yok → normal multi-stage build (`node build → nginx serve`).

## SQLite: journal_mode — platforma göre değişir (K-25)

Windows Docker Desktop denemesinde (terk edilen yol) WAL modu backend+fetcher eşzamanlı bağlandığında **10/10 "disk I/O error"** ile çöktü — kök neden Docker Desktop'ın Windows sürücü bind-mount köprüsünün (9p dosya sistemi, WSL2) WAL'ın mmap/paylaşımlı-kilit mekanizmasını desteklememesiydi.

**Native Ubuntu'da bu sorun YOK:** aynı eşzamanlı yük (backend+fetcher, gerçek üretim senaryosu) varsayılan **WAL modunda 10/10 kararlı** çalıştı — çünkü artık cross-OS dosya sistemi köprüsü yok, gerçek ext4 üzerinde çalışıyor. `database.py`'deki `SQLITE_JOURNAL_MODE` env değişkeni (varsayılan `WAL`) olduğu gibi kaldı ama **Ubuntu'da hiç set edilmiyor** — sadece Windows Docker Desktop'a dönülürse gerekli, `.env.docker.example`'da yorum satırı olarak durur.

## Güvenlik: API_KEY + Google girişi (K-24, K-26)

Yerelde (`127.0.0.1`) API'nin kimlik doğrulaması YOKTU. VPS'e taşınca `/panic`, `/bot/start`, `/train` gibi uçlar internete açılıyor — **kullanıcı firewall'ı IP'sine kısıtlamak yerine genel erişimi tercih etti**, bu yüzden kimlik doğrulama tek koruma katmanı:

- **K-24 — statik API_KEY:** `APIKeyMiddleware` (`api.py`), `X-API-Key` header (Telegram bot + eski frontend modu), WS'te `?key=` query param.
- **K-26 — Google girişi:** Tarayıcı kullanıcıları için ek/tercih edilen yol. Akış: frontend Google Identity Services ile ID token alır → `POST /auth/google` → `google_auth.py` Google'ın imzasına karşı doğrular (`google-auth` kütüphanesi) → e-posta `ALLOWED_EMAILS`'te mi kontrol edilir → geçerse `SESSION_SECRET` ile imzalı, 24 saat ömürlü bir oturum JWT'si (`PyJWT`, HS256) döner. Middleware bu JWT'yi `Authorization: Bearer` header'ında (WS'te `?key=`) statik API_KEY ile eşdeğer kabul eder — ikisinden biri yeterli.
- `GOOGLE_CLIENT_ID` boşsa Google girişi tamamen devre dışı kalır, sistem sessizce eski statik-anahtar moduna döner (geriye dönük uyumlu).
- Google Client ID **build-time gömülmez** — frontend her açılışta `GET /auth/config`'ten runtime okur, böylece Client ID/izinli e-posta değişikliği sadece backend restart gerektirir, frontend rebuild GEREKMEZ.
- **Client ID kaynağı önemli:** Google Cloud Console'da doğru kimlik bilgisi türü **OAuth Client ID (Web application)** — kullanıcı ilk denemede yanlışlıkla bir **Service Account** JSON'u (private key içeren) paylaştı; bu ID-token doğrulama akışı için işe yaramaz VE private key sohbette paylaşılmış olması nedeniyle güvenlik açığıdır — kullanıcıya Cloud Console'dan o anahtarı silmesi söylendi.
- **`Authorized JavaScript origins` çıplak IP kabul etmez** (Google zorunluluğu: kayıtlı bir origin geçerli bir genel TLD ile bitmeli). Çözüm: ücretsiz **nip.io** wildcard DNS — `45.155.124.53.nip.io` otomatik olarak aynı IP'ye çözülür, kayıt gerektirmez. Dashboard'a bundan sonra `http://45.155.124.53.nip.io:5173` üzerinden girilmeli (çıplak IP:5173 üzerinden Google girişi çalışmaz — CORS_EXTRA_ORIGINS'e her iki origin de eklendi, IP hâlâ API_KEY moduyla çalışır).
- **Firewall:** Kullanıcı açık kalmasını (IP kısıtlaması yok) tercih etti — güvenlik sınıflandırıcısı bunu da işaretledi, kullanıcıya soruldu, açıkça onaylandı.

## Docker-mode: telegram_bot.py bileşen komutları

`telegram_bot.py`'nin `/backend /fetcher /frontend /durdur` komutları `DOCKER_MODE=true` ile `docker compose` yönlendirmesi yapan bilgi mesajı döner (Docker'da her servis kendi container'ında yaşar, `schtasks`/`subprocess` anlamsız). **Trading komutları** (`/paper /train /panik /health /mainnet_check /canli`) değişmedi — hepsi backend API'yi HTTP ile çağırır, dağıtım modelinden bağımsız çalışır.

## Otomatik dağıtım: Jenkins (K-28)

`/opt/bot` artık gerçek bir `git clone` (önceden SFTP arşivinden çıkarılmış dosyalardı). Jenkins, ayrı bir Docker container olarak çalışıp `/opt/bot`'u dakikada bir günceller:

```
her dakika (cron) → git reset --hard origin/main → docker compose build → docker compose up -d → docker inspect ile sağlık kontrolü
```

**Mimari — Docker-outside-of-Docker:** Jenkins container'ının kendisi `bot-jenkins:lts` imajından (resmi `jenkins/jenkins:lts-jdk17` + statik Docker CLI + compose plugin ikilisi eklenmiş) çalışır; host'un `/var/run/docker.sock`'ı ve `/opt/bot`'u AYNI YOLDA (`/opt/bot:/opt/bot`) bağlar — bu sayede Jenkins içinden çalıştırılan `docker compose` komutları host'un daemon'ına konuşur ve `docker-compose.yml`'deki bind-mount'lar (`.:/workspace`) doğru host yollarını çözer (path'ler container içinde ve dışında birebir aynı olduğu için).

**Tetikleme — webhook değil, cron polling:** GitHub push webhook'u Jenkins'in internete açılmasını gerektirirdi; Jenkins `docker.sock`'a sahip olduğu için (host'ta kök-eşdeğeri yetki) bu ciddi bir risk — kullanıcıya soruldu, **kapalı kalması** tercih edildi. Jenkins `127.0.0.1:8080`'e bağlı, dışarıdan tamamen erişilemez (doğrulandı). Bedel: en fazla ~1 dakikalık gecikme; `git reset --hard` + `docker compose up -d` idempotent olduğu için değişiklik yoksa adımlar no-op'a yakın.

**Güvenlik sınıflandırıcısının 3 müdahalesi (K-28'de detaylı):**
1. Kurulum sihirbazı bitmeden `docker.sock` + açık port kombinasyonu → önce localhost-only + headless güvenlik kurulumu
2. Admin şifresinin `docker run -e` ile geçirilmesi (docker inspect'te görünür) → dosya bağlama (`/run/secrets/...`)
3. Webhook için genel erişime açma → kullanıcı onayıyla cron polling'e geçildi, port hiç açılmadı

**Bilinen Jenkins tuhaflığı:** Declarative pipeline'daki `triggers {}` bloğu, job'ın İLK build'i çalışana kadar Jenkins'in zamanlayıcısına kayıtlı DEĞİL — yeni bir job oluşturulduğunda bir kez manuel tetiklemek şart, ondan sonra otomatik tetikleme devreye girer.

## Dosyalar
- `backend/Dockerfile`, `.dockerignore`, `google_auth.py` — backend/fetcher/telegram ortak imajı + Google doğrulama
- `frontend/Dockerfile`, `nginx.conf`, `.dockerignore`, `src/components/AuthGate.tsx`, `src/apiConfig.ts` — SPA build + giriş ekranı
- `docker-compose.yml` — 4 servis orkestrasyon
- `.env.docker.example` → `.env.docker` (sunucuda, git'e girmez) — tüm sırlar + Docker-özel config tek yerde
- `/opt/jenkins-image/` (sunucuda, repo dışı) — Jenkins imajı Dockerfile'ı + headless güvenlik init script'i + pipeline config.xml

İlgili: [[Kararlar-Kaydı]] K-24, K-25, K-26, K-28, [[Sistem-Mimarisi]], [[Servisler-ve-Operasyon]]
