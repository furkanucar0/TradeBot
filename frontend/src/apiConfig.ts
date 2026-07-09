// K-24/K-26: VPS'e taşımada API internete açık — kimlik doğrulama zorunlu.
// İki mekanizma: statik API_KEY (build-time, .env — dev/legacy) VEYA Google
// girişiyle alınan kısa ömürlü oturum token'ı (runtime, localStorage).
// Oturum token'ı varsa o önceliklidir. Tarayıcı WebSocket API'si özel header
// taşıyamadığı için WS bağlantılarında anahtar query param olarak gider.
export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const STATIC_API_KEY = import.meta.env.VITE_API_KEY || ''

const SESSION_KEY = 'tradebot_session_token'
const EMAIL_KEY = 'tradebot_session_email'

export function getSessionToken(): string {
  return localStorage.getItem(SESSION_KEY) || ''
}

export function getSessionEmail(): string {
  return localStorage.getItem(EMAIL_KEY) || ''
}

export function setSession(token: string, email: string): void {
  localStorage.setItem(SESSION_KEY, token)
  localStorage.setItem(EMAIL_KEY, email)
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY)
  localStorage.removeItem(EMAIL_KEY)
}

function activeCredential(): string {
  return getSessionToken() || STATIC_API_KEY
}

export function apiHeaders(): Record<string, string> {
  const token = getSessionToken()
  if (token) return { Authorization: `Bearer ${token}` }
  if (STATIC_API_KEY) return { 'X-API-Key': STATIC_API_KEY }
  return {}
}

export function wsUrl(host: string, path: string): string {
  const cred = activeCredential()
  const sep = path.includes('?') ? '&' : '?'
  return cred ? `${host}${path}${sep}key=${encodeURIComponent(cred)}` : `${host}${path}`
}
