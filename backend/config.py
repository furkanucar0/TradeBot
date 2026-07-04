"""
CTOS FAZ 1 — Merkezi konfigürasyon (K-17).
TÜM ayarlanabilir sabitler burada; live_trader ve train_engine buradan import
eder. Eskiden LEVERAGE/RISK gibi kritik değerler iki dosyada MÜKERRERDİ ve
sessizce ayrışabiliyordu (POSITION_USDT kazası: backtest 10x'ken canlı yol
tanımsız sabit kullanıyordu).

Karar dayanakları için: brain/04-Kararlar/Kararlar-Kaydı.md
"""

# ── İşlem evreni ──────────────────────────────────────────────────────────────
SYMBOLS = ["BTC/USDT", "ETH/USDT"]
TIMEFRAME = "1m"

# ── Risk (K-6 kararlılık paketi + K-14 proba ölçeği) ─────────────────────────
LEVERAGE = 5               # taban kaldıraç; drawdown ile 4x→3x'e iner
RISK_PER_TRADE = 0.005     # SL vurursa kasanın maks %0.5'i (proba/Kelly/DD sadece düşürür)
MAX_POSITIONS = 2          # sembol başına 1
DAILY_LOSS_LIMIT_PCT  = -0.015   # gün içi -%1.5 → o gün yeni işlem yok
DAILY_PROFIT_LOCK_PCT =  0.02    # gün içi +%2  → kâr kilidi

# ── Maliyet modeli (backtest = paper = canlı) ────────────────────────────────
FEE_RATE = 0.0004          # %0.04 taker (giriş + çıkış ayrı kesilir)
SLIPPAGE_RATE = 0.0002     # %0.02 market emir kayması (çıkışta uygulanır)
FUNDING_PER_8H = 0.0001    # tahmini funding / 8 saat

# ── Sinyal seçiciliği (K-9, K-11, K-13) ──────────────────────────────────────
SIGNAL_MARGIN = 0.07       # proba, model eşiğini bu kadar da aşmalı (kalibrasyon kanıtlı)
TREND_VETO_MARGIN = 0.15   # 1h trend aleyhteyken sinyal ancak eşiği bu kadar aşarsa geçer

# ── Canlı döngü ───────────────────────────────────────────────────────────────
LOOP_INTERVAL = 30         # saniye — sinyal değerlendirme periyodu
DEMO_START_BALANCE = 100.0 # paper kasa başlangıcı
CANDLE_BUFFER_SIZE = 3000  # 1m buffer (50 saat) — 1h MTF warmup için

# ── Yeniden eğitim (K-4, K-13b) ──────────────────────────────────────────────
RETRAIN_DAYS = 45          # kayan eğitim penceresi
RETRAIN_MIN_TRADES = 20    # otomatik retrain için asgari yeni kapanan işlem
RETRAIN_MIN_GAP_S = 12 * 3600  # retrainler arası asgari süre

# ── Eğitim / backtest (K-2, K-7, K-8, K-10) ──────────────────────────────────
WIN_RATE_TARGET = 0.60     # dinamik WR hedefinin üst sınırı
RR_TARGET = 2.0            # min R:R
MAX_RR = 4.0               # R:R≤2.5 kısıtı DENENDİ ve GERİ ALINDI (K-7)
VAL_DAYS  = 21             # doğrulama dilimi
TEST_DAYS = 21             # dokunulmamış test dilimi
PURGE_HOURS = 24           # bölme sınırlarında etiket sızıntısı tamponu
MIN_DIRECTION_PREC = 0.35  # mutlak precision tabanı (dinamik taban bununla max'lanır)
SL_GRID = [0.003, 0.004, 0.005]
TP_GRID = [0.006, 0.008, 0.010, 0.012]

# ── Risk duvarı (FAZ 3 — K-19) ───────────────────────────────────────────────
HEALTH_PAUSE_SCORE  = 40   # sağlık skoru bunun ALTINA inerse yeni işlem duraklar
HEALTH_RESUME_SCORE = 55   # histerezis: bu skora çıkmadan devam edilmez
ADX_RANGING_FLOOR   = 20   # 1h ADX bunun altı = yönsüz piyasa, sinyal yok (live_trader'dan taşındı)
OB_IMBALANCE_LIMIT  = 0.15 # emir defteri dengesizlik veto eşiği (live_trader'dan taşındı)

# ── Karar kaydı (FAZ 4 — K-20) ───────────────────────────────────────────────
DECISIONS_KEEP_DAYS = 7    # decisions tablosunda tutulacak gün sayısı

# ── MFE/MAE hafızası (FAZ 5 — K-21) ──────────────────────────────────────────
# Öz-değerlendirme eşikleri: MFE = işlem boyunca lehte en uç hareket,
# MAE = aleyhte en uç hareket (giriş fiyatına oran)
MFE_NEAR_TP_RATIO = 0.8    # SL yedi ama MFE ≥ TP'nin %80'i → "stop dar / TP uzak"
MAE_NEAR_SL_RATIO = 0.8    # TP vurdu ama MAE ≥ SL'in %80'i → "şanslı kazanç"
MFE_LOW_RATIO     = 0.3    # SL yedi ve MFE < TP'nin %30'u → "yanlış yön"

# ── Champion vs Challenger (FAZ 6 — K-22) ────────────────────────────────────
# Retrain'de yeni model (challenger), mevcut şampiyonu ORTAK doğrulama
# diliminde yenemezse model.bin DEĞİŞMEZ (pencere hassasiyetine karşı sigorta)
CHALLENGER_MIN_IMPROVE = 0.05   # şampiyon EV'sinin en az %5 üstü gerekir

# ── Mainnet Geçiş Protokolü (FAZ 7 — K-23) ───────────────────────────────────
# "Paper'a sabır" ilkesinin resmileşmesi: TÜM koşullar sağlanmadan gerçek para
# açılmaz; sağlansa bile Telegram'dan iki adımlı onay şarttır (/canli → /canli_onay)
MAINNET_MIN_TRADES    = 100    # asgari kapanmış paper işlem (TP/SL çıkışlı)
MAINNET_MIN_DAYS      = 14     # asgari paper kanıt süresi (gün)
MAINNET_MAX_DD        = 0.15   # paper equity maks. drawdown
MAINNET_WORST_DAY_PCT = -0.03  # tek günde bundan kötü kayıp varsa geçilmez
MAINNET_CONFIRM_S     = 300    # /canli sonrası onay penceresi (saniye)

# ── Sağlık skoru (FAZ 2 — K-18) ──────────────────────────────────────────────
# Bileşen ağırlıkları (toplam 100)
HEALTH_WEIGHTS = {
    "drawdown":    30,   # zirveden düşüş
    "streak":      20,   # ardışık kayıp serisi
    "daily_pnl":   15,   # günlük PnL'in fren bandındaki yeri
    "wr_trend":    20,   # son 20 işlem WR'ı vs başabaş
    "data_fresh":  15,   # fiyat beslemesinin tazeliği
}
HEALTH_DD_FLOOR = 0.15     # bu drawdown'da bileşen 0 puan
HEALTH_STREAK_FLOOR = 5    # bu kadar ardışık kayıpta bileşen 0 puan
HEALTH_STALE_S = 120       # fiyat beslemesi bundan eskiyse bileşen 0 puan
