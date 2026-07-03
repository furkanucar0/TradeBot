"""
Telegram bildirim modülü.
.env dosyasındaki TELEGRAM_TOKEN ve TELEGRAM_CHAT_ID kullanılır.
Chat ID yoksa bot'a herhangi bir mesaj gönder → otomatik algılanır.
"""
import os
import threading
import time
from pathlib import Path
from typing import Optional

import requests

_ENV_PATH  = Path(__file__).resolve().parent.parent / ".env"
_TOKEN     = ""
_CHAT_ID   = ""
_lock      = threading.Lock()
_last_sent = 0.0          # throttle: aynı mesajı 1 sn'de bir gönder
_MIN_INTERVAL = 1.0       # saniye


def _load_env() -> None:
    global _TOKEN, _CHAT_ID
    if not _ENV_PATH.exists():
        return
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k == "TELEGRAM_TOKEN" and v:
            _TOKEN = v
        elif k == "TELEGRAM_CHAT_ID" and v:
            _CHAT_ID = v
    # os.environ de kontrol et (override)
    _TOKEN   = os.getenv("TELEGRAM_TOKEN",   _TOKEN)
    _CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", _CHAT_ID)


def _get_chat_id() -> str:
    """getUpdates ile bota mesaj gönderen ilk kullanıcının chat_id'sini döner."""
    if not _TOKEN:
        return ""
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{_TOKEN}/getUpdates",
            timeout=5,
        )
        updates = resp.json().get("result", [])
        if updates:
            cid = str(updates[-1]["message"]["chat"]["id"])
            # .env'e kaydet ki bir sonraki başlatmada sormasın
            _save_chat_id(cid)
            return cid
    except Exception:
        pass
    return ""


def _save_chat_id(cid: str) -> None:
    try:
        text = _ENV_PATH.read_text(encoding="utf-8")
        if "TELEGRAM_CHAT_ID=" in text:
            lines = []
            for ln in text.splitlines():
                if ln.strip().startswith("TELEGRAM_CHAT_ID"):
                    lines.append(f"TELEGRAM_CHAT_ID={cid}")
                else:
                    lines.append(ln)
            _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            with _ENV_PATH.open("a", encoding="utf-8") as f:
                f.write(f"TELEGRAM_CHAT_ID={cid}\n")
    except Exception:
        pass


def send(text: str) -> None:
    """Ana bildirim fonksiyonu — thread-safe, throttled."""
    global _CHAT_ID, _last_sent

    if not _TOKEN:
        _load_env()
    if not _TOKEN:
        return

    with _lock:
        now = time.time()
        if now - _last_sent < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - (now - _last_sent))
        _last_sent = time.time()

        if not _CHAT_ID:
            _CHAT_ID = _get_chat_id()
        if not _CHAT_ID:
            return  # kullanıcı henüz bota mesaj göndermedi

        try:
            requests.post(
                f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
                json={"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception:
            pass


def send_async(text: str) -> None:
    """Bildirim gönderimi ana loop'u bloklamaz."""
    threading.Thread(target=send, args=(text,), daemon=True).start()


# Yükle
_load_env()
