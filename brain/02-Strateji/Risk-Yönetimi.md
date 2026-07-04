---
tags: [strateji, risk]
---

# Risk Yönetimi (Kararlılık Paketi — 2026-07-03)

Hedef: günlük %1-2 istikrarlı getiri, düşük varyans. Kararlılık **R:R'ı kısıtlayarak değil** (deney bunu çürüttü → [[2026-07-03-RR-Bandı-Deneyi]]), risk katmanlarıyla sağlanır.

## Katmanlar

| Katman | Kural | Not |
|---|---|---|
| İşlem başına risk | SL kaybı ≤ kasanın **%0.5'i** | Backtest ve canlı AYNI formül |
| **Proba ölçeği (K-14)** | İşlemin KENDİ olasılığıyla Kelly: 0.4-1.0 çarpan | p=0.50→0.62× · p≥0.62→1.0× — kalibrasyon kanıtlı |
| Quarter-Kelly | Son 20 işlem WR'ına göre 0.30-1.0 çarpan | Kanıtsız model **%0.25** ile başlar |
| Drawdown ölçeği | Zirveden düşüşte boyut %30'a kadar iner | DD×7 formülü |
| Kaldıraç | **5x** taban; DD %5→4x, %8→3x | Gap/likidasyon koruması |
| Korelasyon | Aynı yönde 2. pozisyon **yarım boy** | BTC-ETH ~0.9 korele |
| Günlük kayıp freni | Gün içi **-%1.5** → o gün yeni işlem yok | Bot durmaz, UTC gece yarısı sıfırlanır |
| Günlük kâr kilidi | Gün içi **+%2** → kâr korunur | Aynı mekanizma |
| Maks pozisyon | 2 (sembol başına 1) | |
| Maliyet modeli | %0.10 komisyon+slippage + funding | Backtest ve paper'da aynen; rapor PnL'i giriş ücreti DAHİL |
| **RiskGate (K-19)** | TÜM vetolar tek sınıfta: ADX<20, trend vetosu, emir defteri, kapasite | `risk_gate.py` — davranış birebir, mimari tekil |
| **Panik kilidi (K-19)** | /panik → pozisyonlar kapanır + bot durur + `panic.lock` | Restart'a dayanır; /panik_kaldir olmadan bot BAŞLATILAMAZ (423) |
| **Sağlık duraklatması (K-19)** | Skor **<40** → yeni işlem yok; **≥55** olunca devam | Histerezis; veri kesintisi skoru düşürdüğünden besleme ölünce otomatik durur |

## Karar görünürlüğü (K-20)
Her sinyal kararı gerekçe koduyla kaydedilir: dashboard **Karar Paneli** (canlı), `GET /decisions` (7 gün geçmiş; NO_SIGNAL hariç). "Neden işlem yok" artık veriyle cevaplanır.

## Örnek (100 USDT kasa, SL %0.5)
Başlangıç: marjin 10 × 5x = 50 notional → SL kaybı 0.25 USDT (%0.25) · TP kazancı ~0.5 USDT.
DD %10'da: marjin 5 × 3x = 15 notional → kayıp %0.08'e çöker — sistem kötü seride kendini kısar.

## Mainnet farkları
- SL/TP **borsa tarafında duran emirler** (stop_market/take_profit_market, reduceOnly) → istemci gecikmesi çıkışları etkilemez
- Boyutlandırma gerçek USDT bakiyesinden, aynı formül
- Kilit: backtest kriterleri geçilmeden açılmaz

İlgili: [[Karar-Zinciri]], [[Kararlar-Kaydı]]
