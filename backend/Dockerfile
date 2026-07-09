# Backend, fetcher ve telegram_bot servislerinin ORTAK imajı — hangi script'in
# çalışacağı docker-compose.yml'deki `command:` ile belirlenir (bkz. install-services.ps1
# eski Windows Task Scheduler eşleniği).
#
# Bağımlılıklar imaja gömülür; UYGULAMA KODU VE VERİ (bot.sqlite, model.bin,
# reports/, zips/, .env) docker-compose tarafında bind-mount ile üstüne biner.
# Böylece kod güncellemesi için imaj yeniden build ETMEYE gerek kalmaz (git pull
# + restart yeterli); imaj sadece Python + kütüphane katmanını taşır.
FROM python:3.11-slim

# lightgbm çalışma zamanı OpenMP kütüphanesi ister; libgomp1 olmadan
# "libgomp.so.1: cannot open shared object file" ile çöker.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Standalone build/test için kod da kopyalanır; runtime'da compose bind-mount
# ile host'un backend/ dizinini üstüne bindirir (canlı kod + gerçek veri).
COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "api.py"]
