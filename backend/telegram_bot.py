"""
Telegram Uzaktan Kontrol
Çalıştır: python telegram_bot.py

Komutlar:
  /baslat        — Her şeyi başlat (backend + fetcher + frontend + paper trade)
  /backend       — Sadece backend (api.py) başlat
  /fetcher       — Sadece mum fetcher (live_fetcher.py) başlat
  /frontend      — Sadece frontend (Vite) başlat
  /paper         — Paper trade botunu başlat (backend gerekli)
  /train         — Model eğitimi başlat (backend + fetcher da başlar)
  /durdur        — Her şeyi durdur
  /durdur_bot    — Sadece paper trade botunu durdur
  /durdur_front  — Sadece frontend'i durdur
  /status        — Anlık durum
  /help          — Komut listesi
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import requests as _req

# ── Dizinler ──────────────────────────────────────────────────────────────────
_HERE     = Path(__file__).resolve().parent
_ROOT     = _HERE.parent
_FRONTEND = _ROOT / "frontend"
_ENV_PATH = _ROOT / ".env"
_API_URL  = "http://localhost:8000"
_PYTHON   = sys.executable

_CREATE_NEW = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0


# ── .env yükle ────────────────────────────────────────────────────────────────
def _load_env() -> dict:
    cfg = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    cfg["TELEGRAM_TOKEN"]   = os.getenv("TELEGRAM_TOKEN",   cfg.get("TELEGRAM_TOKEN",   ""))
    cfg["TELEGRAM_CHAT_ID"] = os.getenv("TELEGRAM_CHAT_ID", cfg.get("TELEGRAM_CHAT_ID", ""))
    return cfg


# ── Süreç yönetimi ────────────────────────────────────────────────────────────
_procs: dict = {"backend": None, "fetcher": None, "frontend": None}

# ── Görev Zamanlayıcısı (hizmet) entegrasyonu ─────────────────────────────────
# install-services.ps1 ile kurulduysa bileşenler schtasks üzerinden yönetilir
# (çökme sonrası otomatik restart dahil); kurulu değilse eski subprocess
# yöntemi kullanılır.
_TASK_NAMES = {
    "backend":  "TradingBotBackend",
    "fetcher":  "TradingBotFetcher",
    "frontend": "TradingBotFrontend",
}
_task_exists_cache: dict = {}


def _task_exists(name: str) -> bool:
    tn = _TASK_NAMES.get(name)
    if not tn or sys.platform != "win32":
        return False
    if tn not in _task_exists_cache:
        r = subprocess.run(["schtasks", "/query", "/tn", tn], capture_output=True)
        _task_exists_cache[tn] = (r.returncode == 0)
    return _task_exists_cache[tn]


def _task_state(name: str) -> str:
    """Görev durumu: Running / Ready / Disabled (enum İngilizce, yerelleşmez)."""
    tn = _TASK_NAMES.get(name, "")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-ScheduledTask -TaskName '{tn}').State"],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _task_start(name: str) -> bool:
    r = subprocess.run(["schtasks", "/run", "/tn", _TASK_NAMES[name]], capture_output=True)
    return r.returncode == 0


def _task_stop(name: str) -> bool:
    r = subprocess.run(["schtasks", "/end", "/tn", _TASK_NAMES[name]], capture_output=True)
    return r.returncode == 0


def _alive(name: str) -> bool:
    if _task_exists(name):
        return _task_state(name) == "Running"
    p = _procs.get(name)
    return p is not None and p.poll() is None


def _start_component(name: str, cmd: list, cwd: Path) -> bool:
    """Hizmet kuruluysa görevi başlat, yoksa subprocess."""
    if _task_exists(name):
        return _task_start(name)
    return _start_proc(name, cmd, cwd)


def _stop_component(name: str) -> bool:
    if _task_exists(name):
        if _task_state(name) != "Running":
            return False
        return _task_stop(name)
    return _stop_proc(name)


def _start_proc(name: str, cmd: list, cwd: Path) -> bool:
    if _alive(name):
        return True
    try:
        _procs[name] = subprocess.Popen(
            cmd, cwd=str(cwd),
            creationflags=_CREATE_NEW,
            stdout=subprocess.DEVNULL,   # terminal karışmasın
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        print(f"{name} başlatılamadı: {e}")
        return False


def _kill_port(port: int):
    """Belirtilen portu dinleyen process'i (ve child'larını) zorla öldür."""
    try:
        result = subprocess.run(
            f"netstat -ano | findstr :{port} | findstr LISTENING",
            shell=True, capture_output=True, text=True
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if parts:
                pid = parts[-1]
                if pid.isdigit() and pid != "0":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", pid],
                                   capture_output=True)
    except Exception:
        pass


def _stop_proc(name: str) -> bool:
    p = _procs.get(name)
    if not p or p.poll() is not None:
        _procs[name] = None
        return False
    pid = p.pid
    if sys.platform == "win32":
        # /T: tüm child process'leri de öldür (npm→node, uvicorn→workers)
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True)
    else:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
    _procs[name] = None
    return True


def _api_ready() -> bool:
    try:
        _req.get(f"{_API_URL}/status", timeout=3)
        return True
    except Exception:
        return False


def _api(method: str, path: str, **kwargs):
    try:
        fn = getattr(_req, method)
        return fn(f"{_API_URL}{path}", timeout=10, **kwargs).json()
    except Exception as e:
        return {"error": str(e)}


# ── Bileşen başlatıcılar ──────────────────────────────────────────────────────
def cmd_backend() -> str:
    if _alive("backend"):
        return "⚠️ Backend zaten çalışıyor."
    _send("⏳ Backend başlatılıyor...")
    if not _start_component("backend", [_PYTHON, "api.py"], _HERE):
        return "❌ Backend başlatılamadı."
    for _ in range(15):
        time.sleep(1)
        if _api_ready():
            return "✅ <b>Backend başlatıldı</b>\nAPI: http://localhost:8000"
    return "⚠️ Backend başladı ama API yanıt vermiyor (15 sn timeout)."


def cmd_fetcher() -> str:
    if _alive("fetcher"):
        return "⚠️ Mum fetcher zaten çalışıyor."
    if _start_component("fetcher", [_PYTHON, "live_fetcher.py"], _HERE):
        return "✅ <b>Mum fetcher başlatıldı</b>\nBTC/USDT + ETH/USDT 1m verisi çekiliyor."
    return "❌ Mum fetcher başlatılamadı."


def cmd_frontend() -> str:
    if _alive("frontend"):
        return "⚠️ Frontend zaten çalışıyor."
    if _task_exists("frontend"):
        if _task_start("frontend"):
            return "✅ <b>Frontend başlatıldı</b> (hizmet)\nArayüz: http://localhost:5173"
        return "❌ Frontend hizmeti başlatılamadı."
    nm = _FRONTEND / "node_modules"
    if not nm.exists():
        _send("⏳ npm install çalıştırılıyor (ilk kez)...")
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        subprocess.run([npm, "install"], cwd=str(_FRONTEND), timeout=120)
    # Windows'ta npm/npx .cmd uzantısıyla çağrılmalı
    if sys.platform == "win32":
        cmd = ["npm.cmd", "run", "dev", "--", "--host"]
    else:
        cmd = ["npm", "run", "dev", "--", "--host"]
    if _start_proc("frontend", cmd, _FRONTEND):
        return "✅ <b>Frontend başlatıldı</b>\nArayüz: http://localhost:5173"
    return "❌ Frontend başlatılamadı."


def cmd_paper() -> str:
    if not _api_ready():
        return "❌ Backend çalışmıyor. Önce /backend yaz."
    r = _api("get", "/status")
    if r.get("is_running"):
        return "⚠️ Paper trade botu zaten çalışıyor."
    if not r.get("model_exists"):
        return "❌ Model bulunamadı. Önce /train yaz."
    r2 = _api("post", "/bot/start?testnet=true")
    if "error" in r2:
        return f"❌ Bot başlatılamadı: {r2['error']}"
    return "✅ <b>Paper trade botu başlatıldı</b>\nBTC/USDT + ETH/USDT izleniyor."


def cmd_train() -> str:
    if not _alive("backend"):
        _send("⏳ Backend başlatılıyor...")
        result = cmd_backend()
        if "❌" in result:
            return result
    if not _alive("fetcher"):
        cmd_fetcher()
    r = _api("post", "/train")
    if "error" in r:
        return f"❌ Eğitim başlatılamadı: {r['error']}"
    return (
        "🧠 <b>Model eğitimi başlatıldı</b>\n"
        "BTC/USDT + ETH/USDT — LONG + SHORT\n"
        "Bitince sonuçlar buraya gelecek.\n"
        "Ardından /paper ile botu başlat."
    )


def cmd_stop_bot() -> str:
    if not _api_ready():
        return "⚠️ Backend çalışmıyor, bot zaten durmuş."
    r = _api("get", "/status")
    if not r.get("is_running"):
        return "⚠️ Paper trade botu zaten durmuş."
    r2 = _api("post", "/bot/stop")
    if "error" in r2:
        return f"❌ Bot durdurulamadı: {r2['error']}"
    return "⏹ <b>Paper trade botu durduruldu.</b>\nBackend + Fetcher çalışmaya devam ediyor."


def cmd_stop_frontend() -> str:
    if _stop_component("frontend"):
        return "⏹ <b>Frontend durduruldu.</b>"
    return "⚠️ Frontend zaten durmuş."


def cmd_stop_all() -> str:
    _send("⏳ Her şey durduruluyor...")
    if _api_ready():
        # 1. Önce trading botunu düzgün durdur
        try:
            _req.post(f"{_API_URL}/bot/stop", timeout=5)
            time.sleep(0.5)
        except Exception:
            pass
        # 2. Backend'e shutdown komutu gönder (dışarıdan başlatılmış olsa bile durur)
        try:
            _req.post(f"{_API_URL}/shutdown", timeout=3)
            time.sleep(1)
        except Exception:
            pass
    # 3. Hizmet kuruluysa görevi durdur (schtasks /end), yoksa subprocess'i öldür
    for name in ["frontend", "fetcher", "backend"]:
        _stop_component(name)
    # 4. Port 8000 hâlâ doluysa PID'i bul ve zorla öldür.
    #    NOT: backend hizmet olarak kuruluysa taskkill KULLANMA — zorla öldürme
    #    "hata" sayılır ve Task Scheduler görevi 1 dk sonra yeniden başlatır.
    if sys.platform == "win32" and not _task_exists("backend"):
        _kill_port(8000)
    return (
        "🔴 <b>Her şey durduruldu</b>\n"
        "Backend · Fetcher · Frontend · Bot\n"
        "Yeniden başlatmak için /baslat yaz."
    )


def cmd_health() -> str:
    if not _api_ready():
        return "⚠️ Backend çalışmıyor."
    h = _api("get", "/health")
    if not h or h.get("score") is None:
        return "😴 Sağlık verisi yok — paper bot çalışmıyor olabilir (/paper)."
    emoji = "🟢" if h["score"] >= 75 else ("🟡" if h["score"] >= 50 else "🔴")
    lines = [
        f"{emoji} <b>Sağlık Skoru: {h['score']}/100 — {h['status']}</b>",
        f"Kasa: {h.get('balance', '?')} USDT | Açık poz: {h.get('open_positions', 0)}"
        + (" | ⏸ günlük fren aktif" if h.get("daily_paused") else ""),
        "",
    ]
    for name, c in (h.get("components") or {}).items():
        bar = "▰" * int(round(c["points"] / c["weight"] * 5)) if c["weight"] else ""
        bar = bar.ljust(5, "▱")
        lines.append(f"{bar} {c['points']:.0f}/{c['weight']} — {c['label']}")
    return "\n".join(lines)


def cmd_status() -> str:
    be = "🟢 Açık" if _alive("backend")  else "🔴 Kapalı"
    fe = "🟢 Açık" if _alive("fetcher") else "🔴 Kapalı"
    fr = "🟢 Açık" if _alive("frontend") else "🔴 Kapalı"

    lines = [
        "📡 <b>Süreç Durumu</b>",
        f"Backend   → {be}",
        f"Fetcher   → {fe}",
        f"Frontend  → {fr}",
    ]

    if not _api_ready():
        lines.append("\nAPI yanıt vermiyor — /backend ile başlat.")
        return "\n".join(lines)

    st = _api("get", "/status")
    bot_status = "▶️ Çalışıyor" if st.get("is_running") else "⏹ Durmuş"
    if st.get("is_training"):
        bot_status += " | 🧠 Eğitim var"

    wr = f"{st['last_win_rate']*100:.1f}%" if st.get("last_win_rate") else "—"
    rr = f"{st['last_rr']:.2f}"            if st.get("last_rr")       else "—"

    lines += [
        f"Paper Bot → {bot_status}",
        f"\nWin Rate: {wr} | R:R: {rr}",
    ]

    pos_list = _api("get", "/positions")
    if isinstance(pos_list, list) and pos_list:
        lines.append("\n<b>Açık Pozisyonlar:</b>")
        for p in pos_list:
            sym  = p.get("symbol", "?")
            side = p.get("side", "?")
            entry = p.get("entry_price", p.get("entry", 0))
            upnl  = p.get("upnl", 0)
            sign  = "+" if upnl >= 0 else ""
            lines.append(f"  {sym} {side} @ {entry:.2f}  ({sign}{upnl:.3f} USDT)")
    else:
        lines.append("\nAçık pozisyon yok.")

    trades = _api("get", "/trades?limit=5&mode=paper&status=closed")
    if isinstance(trades, list) and trades:
        total = sum(t.get("pnl_usdt") or 0 for t in trades)
        sign  = "+" if total >= 0 else ""
        lines.append(f"\nSon 5 işlem PnL: {sign}{total:.3f} USDT")

    return "\n".join(lines)


# ── Telegram gönderici ────────────────────────────────────────────────────────
_TOKEN   = ""
_CHAT_ID = ""


def _send(text: str):
    if not _TOKEN or not _CHAT_ID:
        return
    try:
        _req.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception:
        pass


# ── Komut yönlendirici ────────────────────────────────────────────────────────
_HELP = (
    "🤖 <b>Komut Listesi</b>\n\n"
    "<b>── Başlatma ──</b>\n"
    "/baslat       — Her şeyi başlat\n"
    "/backend      — Sadece backend\n"
    "/fetcher      — Sadece mum fetcher\n"
    "/frontend     — Sadece arayüz\n"
    "/paper        — Sadece paper trade botu\n"
    "/train        — Model eğitimi\n\n"
    "<b>── Durdurma ──</b>\n"
    "/durdur       — Her şeyi durdur\n"
    "/durdur_bot   — Sadece paper trade botunu durdur\n"
    "/durdur_front — Sadece frontend'i durdur\n\n"
    "<b>── Bilgi ──</b>\n"
    "/status       — Anlık durum\n"
    "/health       — Sağlık skoru (0-100)\n"
    "/help         — Bu mesaj"
)


def _handle(text: str):
    cmd = text.strip().lower().split()[0]

    if cmd in ("/start", "/help"):
        _send(_HELP)

    elif cmd == "/baslat":
        _send("⏳ Her şey başlatılıyor...")
        results = []
        r = cmd_backend();  results.append(r)
        if "❌" not in r:
            results.append(cmd_fetcher())
            results.append(cmd_frontend())
            results.append(cmd_paper())
        _send("🟢 <b>Tamamlandı</b>\n\n" + "\n".join(results))

    elif cmd == "/backend":
        _send(cmd_backend())

    elif cmd == "/fetcher":
        _send(cmd_fetcher())

    elif cmd == "/frontend":
        _send(cmd_frontend())

    elif cmd == "/paper":
        _send(cmd_paper())

    elif cmd == "/train":
        _send(cmd_train())

    elif cmd == "/durdur":
        _send(cmd_stop_all())

    elif cmd == "/durdur_bot":
        _send(cmd_stop_bot())

    elif cmd == "/durdur_front":
        _send(cmd_stop_frontend())

    elif cmd == "/status":
        _send(cmd_status())

    elif cmd == "/health":
        _send(cmd_health())

    else:
        _send(f"❓ Bilinmeyen komut: <code>{cmd}</code>\n/help yaz.")


# ── Ana döngü ─────────────────────────────────────────────────────────────────
def main():
    global _TOKEN, _CHAT_ID
    cfg      = _load_env()
    _TOKEN   = cfg["TELEGRAM_TOKEN"]
    _CHAT_ID = cfg["TELEGRAM_CHAT_ID"]

    if not _TOKEN or not _CHAT_ID:
        print("HATA: TELEGRAM_TOKEN veya TELEGRAM_CHAT_ID .env'de eksik.")
        sys.exit(1)

    print(f"Telegram bot dinleniyor... (Chat: {_CHAT_ID})")
    _send(
        "🟢 <b>Uzaktan kontrol aktif!</b>\n\n"
        "/baslat → Her şeyi başlat\n"
        "/help   → Tüm komutlar"
    )

    offset = 0
    while True:
        try:
            resp = _req.get(
                f"https://api.telegram.org/bot{_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                timeout=35,
            )
            for upd in resp.json().get("result", []):
                offset = upd["update_id"] + 1
                msg     = upd.get("message", {})
                from_id = str(msg.get("chat", {}).get("id", ""))
                text    = msg.get("text", "").strip()

                if from_id != _CHAT_ID or not text.startswith("/"):
                    continue

                print(f"Komut: {text}")
                _handle(text)

        except KeyboardInterrupt:
            print("\nDurduruldu — süreçler kapatılıyor...")
            # /shutdown API'si varsa önce düzgün durdur
            if _api_ready():
                try:
                    _req.post(f"{_API_URL}/bot/stop", timeout=3)
                except Exception:
                    pass
                try:
                    _req.post(f"{_API_URL}/shutdown", timeout=3)
                    time.sleep(1)
                except Exception:
                    pass
            for name in ["frontend", "fetcher", "backend"]:
                _stop_component(name)
            if sys.platform == "win32" and not _task_exists("backend"):
                _kill_port(8000)
            print("Tüm süreçler durduruldu.")
            break
        except Exception as e:
            print(f"Polling hatası: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
