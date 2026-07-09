import { useEffect, useRef, useState, type ReactNode } from 'react'
import { API_BASE, clearSession, getSessionEmail, getSessionToken, setSession } from '../apiConfig'

declare global {
  interface Window {
    google?: any
  }
}

interface AuthConfig {
  google_enabled: boolean
  google_client_id: string
}

// K-26: Google girişi. Backend Google girişi yapılandırılmamışsa (dev/legacy
// mod) kontrolsüz geçilir — VITE_API_KEY zaten apiConfig'te devrede.
export default function AuthGate({ children }: { children: ReactNode }) {
  const [cfg, setCfg] = useState<AuthConfig | null>(null)
  const [email, setEmail] = useState(getSessionEmail())
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)
  const buttonRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API_BASE}/auth/config`)
      .then(r => r.json())
      .then((c: AuthConfig) => setCfg(c))
      .catch(() => setCfg({ google_enabled: false, google_client_id: '' }))
      .finally(() => setChecking(false))
  }, [])

  const loggedIn = !cfg?.google_enabled || (!!getSessionToken() && !!email)

  useEffect(() => {
    if (!cfg?.google_enabled || loggedIn) return

    const init = () => {
      if (!window.google || !buttonRef.current) return
      window.google.accounts.id.initialize({
        client_id: cfg.google_client_id,
        callback: async (resp: { credential: string }) => {
          setError(null)
          try {
            const r = await fetch(`${API_BASE}/auth/google`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ credential: resp.credential }),
            })
            const data = await r.json()
            if (!r.ok) throw new Error(data.detail || 'Giriş reddedildi')
            setSession(data.session_token, data.email)
            setEmail(data.email)
          } catch (e: any) {
            setError(e?.message ?? 'Giriş başarısız')
          }
        },
      })
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: 'filled_black', size: 'large', text: 'signin_with',
      })
    }

    if (window.google) init()
    else {
      const id = setInterval(() => {
        if (window.google) { clearInterval(id); init() }
      }, 200)
      return () => clearInterval(id)
    }
  }, [cfg, loggedIn])

  if (checking) return null

  if (!loggedIn) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        <div className="rounded-3xl border border-slate-800 bg-slate-900/80 p-10 flex flex-col items-center gap-4 max-w-sm text-center">
          <h1 className="text-xl font-semibold text-white">TradeBot Dashboard</h1>
          <p className="text-slate-400 text-sm">Devam etmek için izinli bir Google hesabıyla giriş yapın.</p>
          <div ref={buttonRef} />
          {error && <p className="text-red-400 text-xs bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">{error}</p>}
        </div>
      </div>
    )
  }

  return (
    <>
      {cfg?.google_enabled && (
        <div className="fixed top-3 right-4 z-50 flex items-center gap-2 text-xs text-slate-400 bg-slate-900/90 border border-slate-800 rounded-full px-3 py-1.5">
          <span>{email}</span>
          <button
            onClick={() => { clearSession(); setEmail(''); window.google?.accounts.id.disableAutoSelect(); }}
            className="text-slate-500 hover:text-red-400 transition"
          >
            Çıkış
          </button>
        </div>
      )}
      {children}
    </>
  )
}
