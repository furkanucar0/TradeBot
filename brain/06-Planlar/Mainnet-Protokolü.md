---
tags: [plan, mainnet, protokol]
tarih: 2026-07-05
durum: aktif
---

# Mainnet Geçiş Protokolü (K-23 — CTOS FAZ 7)

"Paper'a sabır" ilkesinin resmi hali. Gerçek para, **8 maddelik kontrol listesi + iki adımlı Telegram onayı** olmadan AÇILAMAZ. Kapı `api.py /bot/start(testnet=false)` içinde zorunludur — arayüzden de, Telegram'dan da delinemez.

## Kontrol listesi (kanıt: kapanmış paper işlemler, yalnız TP/SL çıkışlı)

| # | Madde | Eşik | Neden |
|---|---|---|---|
| 1 | İşlem sayısı | ≥ 100 | Küçük örneklem şansa borçlu olabilir |
| 2 | Kanıt süresi | ≥ 14 gün | Tek rejimde toplanan kanıt yanıltır |
| 3 | **WR %95 Wilson alt sınırı** ≥ başabaş WR | model komboya göre (~%40) | WR'ın kendisi değil, güven alt sınırı — 10 işlemde %60 geçmez, 100 işlemde geçebilir |
| 4 | Toplam paper PnL | > 0 | Bariz |
| 5 | Paper equity MaxDD | ≤ %15 | Sermaye koruması |
| 6 | En kötü gün | ≥ -%3 | Günlük fren pratikte çalışıyor mu |
| 7 | Backtest kilidi (ready_for_live) | ✓ | Model tarafı kanıtı (dinamik WR + R:R≥2 + EV+ + Sharpe≥0.5 + DD≤%25) |
| 8 | Panik kilidi | kapalı | [[Kararlar-Kaydı]] K-19 |

Kaynak: `backend/mainnet_check.py` · `GET /mainnet-check` · Eşikler `config.py` (MAINNET_*).

## Açılış prosedürü (Telegram, iki adımlı)

1. `/mainnet_check` → listeyi gör (her an bakılabilir)
2. `/canli` → protokol yeniden koşulur; GEÇERSE 5 dk'lık onay penceresi açılır
3. `/canli_onay` → pencere içindeyse `/bot/start?testnet=false` çağrılır; API kapıyı BİR KEZ DAHA doğrular (savunma derinliği)
4. Açılış sonrası: acil durdurma `/panik` (K-19)

## Kanıt raporu şablonu (geçiş anında doldurulur)

```
## Mainnet Geçiş Kanıtı — <tarih>
- Dönem: <ilk işlem> → <son işlem> (<N> gün)
- İşlem: <n> (TP <w> / SL <l>) | WR %<wr> | Wilson alt %<lb> | başabaş %<be>
- PnL: <toplam> USDT | MaxDD %<dd> | en kötü gün %<worst>
- Model: SL/TP <sl>/<tp> | eğitim <trained_at> | C-v-C: <sonuç>
- Karar: 8/8 ✓ → /canli_onay verildi, başlangıç sermayesi <X> USDT
```

Notlar: yüzdeler 100 USDT tabanına göre (demo kasa restart'ta sıfırlansa da DB kayıtları kümülatif kanıttır). MANUAL/BOT_RESTART çıkışları kanıt sayılmaz.

İlgili: [[Kararlar-Kaydı]] K-23, [[Risk-Yönetimi]], [[2026-07-04-CTOS-Yol-Haritası]]
