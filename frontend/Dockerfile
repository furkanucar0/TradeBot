# Üretim derlemesi: Vite env değişkenleri BUILD zamanında JS bundle'ına
# gömülür (VITE_API_KEY dahil — tarayıcıya gönderilen kodda görünür olacağı
# için "sır" değil, sadece rastgele tarayan botlara karşı bir eşik; asıl
# koruma sunucu güvenlik duvarında IP kısıtlaması olmalı — bkz. README).
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_API_KEY
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
