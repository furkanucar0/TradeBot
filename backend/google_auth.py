"""
CTOS FAZ ek (K-26): Google girişi.
Dashboard'a erişim artık iki yoldan biriyle kanıtlanabilir:
  1. Statik API_KEY (Telegram bot gibi sunucu-sunucu çağrıları — K-24)
  2. Google ile giriş yapmış, ALLOWED_EMAILS listesinde olan bir kullanıcının
     bu modülün ürettiği kısa ömürlü oturum JWT'si (tarayıcı kullanıcıları)

Akış: tarayıcı Google Identity Services ile ID token alır → backend'e
POST /auth/google ile gönderir → burada Google'ın imzasına karşı doğrulanır
(google-auth kütüphanesi, Google'ın genel anahtarlarını kullanır) → e-posta
ALLOWED_EMAILS'te mi kontrol edilir → geçerse bizim imzaladığımız kısa ömürlü
bir oturum JWT'si döner (SESSION_SECRET ile HS256).
"""
import time
from typing import Optional

import jwt as pyjwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from config import ALLOWED_EMAILS, GOOGLE_CLIENT_ID, SESSION_SECRET

SESSION_TTL_S = 24 * 3600   # 24 saat sonra yeniden Google ile giriş gerekir
_google_req = google_requests.Request()


class AuthError(Exception):
    pass


def verify_google_credential(credential: str) -> str:
    """Google ID token'ı doğrular, izinliyse e-postayı döner; değilse AuthError."""
    if not GOOGLE_CLIENT_ID:
        raise AuthError("Google girişi bu sunucuda yapılandırılmamış (GOOGLE_CLIENT_ID boş)")
    try:
        info = id_token.verify_oauth2_token(credential, _google_req, GOOGLE_CLIENT_ID)
    except Exception as e:
        raise AuthError(f"Geçersiz Google kimlik bilgisi: {e}")

    email = (info.get("email") or "").lower().strip()
    if not info.get("email_verified"):
        raise AuthError("Google e-postası doğrulanmamış")
    if not email or email not in ALLOWED_EMAILS:
        raise AuthError(f"{email or '?'} izinli e-posta listesinde değil")
    return email


def issue_session_token(email: str) -> str:
    payload = {"email": email, "exp": int(time.time()) + SESSION_TTL_S, "iat": int(time.time())}
    return pyjwt.encode(payload, SESSION_SECRET, algorithm="HS256")


def verify_session_token(token: str) -> Optional[str]:
    """Geçerliyse e-postayı, değilse None döner (asla exception fırlatmaz —
    çağıran taraf sadece 'geçerli mi' bilmek istiyor)."""
    if not token or not SESSION_SECRET:
        return None
    try:
        payload = pyjwt.decode(token, SESSION_SECRET, algorithms=["HS256"])
        email = payload.get("email", "")
        return email if email in ALLOWED_EMAILS else None
    except Exception:
        return None
