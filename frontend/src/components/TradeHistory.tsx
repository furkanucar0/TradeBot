import { useEffect, useState, useCallback } from 'react'
import { type Trade } from '../api'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

type Mode = 'all' | 'paper' | 'live'

function toUnixSec(dateStr: string) {
  return dateStr ? Math.floor(new Date(dateStr).getTime() / 1000) : 0
}

function fmtTs(ts: number) {
  return new Date(ts).toLocaleString('tr-TR')
}

// FAZ 5 (K-21): öz-değerlendirme etiketleri
const EVAL_TR: Record<string, { label: string; cls: string }> = {
  STOP_DAR:   { label: 'stop dar',    cls: 'bg-orange-900/60 text-orange-300' },
  YANLIS_YON: { label: 'yanlış yön',  cls: 'bg-red-900/50 text-red-300' },
  TEMIZ_TP:   { label: 'temiz',       cls: 'bg-green-900/60 text-green-300' },
  SANSLI_TP:  { label: 'şanslı',      cls: 'bg-yellow-900/60 text-yellow-300' },
  NORMAL_SL:  { label: 'normal',      cls: 'bg-slate-700 text-slate-300' },
  NORMAL_TP:  { label: 'normal',      cls: 'bg-slate-700 text-slate-300' },
  MANUEL:     { label: 'manuel',      cls: 'bg-slate-700 text-slate-300' },
}

export default function TradeHistory() {
  const [trades, setTrades]     = useState<Trade[]>([])
  const [mode, setMode]         = useState<Mode>('all')
  const [since, setSince]       = useState('')
  const [until, setUntil]       = useState('')
  const [error, setError]       = useState<string | null>(null)
  const [loading, setLoading]   = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(() => {
    const params = new URLSearchParams({ limit: '200', mode })
    if (since) params.set('since', String(toUnixSec(since)))
    if (until) params.set('until', String(toUnixSec(until)))

    setLoading(true)
    fetch(`${API_BASE}/trades?${params}`)
      .then(r => {
        if (!r.ok) throw new Error(`Sunucu hatası: ${r.status}`)
        return r.json()
      })
      .then(data => {
        if (!Array.isArray(data)) throw new Error('Beklenmeyen yanıt formatı')
        setTrades(data)
        setSelected(new Set())
        setError(null)
      })
      .catch(e => setError(e?.message ?? 'Bağlantı hatası'))
      .finally(() => setLoading(false))
  }, [mode, since, until])

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [load])

  // Sadece açık olmayan kayıtlar seçilebilir
  const deletable = trades.filter(t => t.status !== 'open')
  const allSelected = deletable.length > 0 && deletable.every(t => selected.has(t.id))

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(deletable.map(t => t.id)))
    }
  }

  function toggleOne(id: number, isOpen: boolean) {
    if (isOpen) return
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function deleteSelected() {
    if (selected.size === 0) return
    if (!confirm(`${selected.size} kayıt silinecek. Emin misin?`)) return
    setDeleting(true)
    fetch(`${API_BASE}/trades`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([...selected]),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(() => { setSelected(new Set()); load() })
      .catch(e => setError(`Silme hatası: ${e}`))
      .finally(() => setDeleting(false))
  }

  const closed = trades.filter(t => t.status === 'closed')
  const cumPnl = closed.reduce((acc, t) => acc + (t.pnl_usdt ?? 0), 0)

  return (
    <div className="space-y-3">

      {/* Filtre şeridi */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="flex rounded-lg overflow-hidden border border-slate-700 text-xs">
          {(['all', 'paper', 'live'] as Mode[]).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1.5 transition ${mode === m ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
            >
              {m === 'all' ? 'Tümü' : m === 'paper' ? 'Paper' : 'Canlı'}
            </button>
          ))}
        </div>

        <input
          type="date" value={since} onChange={e => setSince(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-xs text-slate-300 focus:outline-none"
          title="Başlangıç tarihi"
        />
        <span className="text-slate-600 text-xs">—</span>
        <input
          type="date" value={until} onChange={e => setUntil(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-xs text-slate-300 focus:outline-none"
          title="Bitiş tarihi"
        />
        {(since || until) && (
          <button onClick={() => { setSince(''); setUntil('') }}
            className="text-xs text-slate-500 hover:text-slate-300">
            Temizle
          </button>
        )}

        {/* Sil butonu — seçim varsa görünür */}
        {selected.size > 0 && (
          <button
            onClick={deleteSelected}
            disabled={deleting}
            className="text-xs px-3 py-1 rounded bg-red-700 hover:bg-red-600 text-white disabled:opacity-40 transition"
          >
            {deleting ? 'Siliniyor...' : `${selected.size} Kaydı Sil`}
          </button>
        )}

        <button
          onClick={load} disabled={loading}
          className="ml-auto text-xs px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-400 hover:text-white disabled:opacity-40"
        >
          {loading ? '...' : 'Yenile'}
        </button>
      </div>

      {error && (
        <div className="text-red-400 text-xs bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* Özet */}
      {trades.length > 0 && (
        <div className="flex justify-between items-center text-xs text-slate-400">
          <span>
            {trades.length} kayıt ({closed.length} kapandı)
            {selected.size > 0 && <span className="ml-2 text-indigo-400">{selected.size} seçili</span>}
          </span>
          {closed.length > 0 && (
            <span className={`font-semibold tabular-nums ${cumPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              Toplam: {cumPnl >= 0 ? '+' : ''}{cumPnl.toFixed(3)} USDT
            </span>
          )}
        </div>
      )}

      {trades.length === 0 ? (
        <div className="text-slate-500 text-sm text-center py-6">
          {loading ? 'Yükleniyor...' : error ? 'Bağlantı kurulamadı' : 'Kayıt yok'}
        </div>
      ) : (
        <div className="overflow-x-auto max-h-80 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-900">
              <tr className="text-slate-400 border-b border-slate-700">
                {/* Tümünü seç */}
                <th className="py-2 pr-2 w-6">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    className="accent-indigo-500 cursor-pointer"
                    title="Tümünü seç"
                  />
                </th>
                <th className="text-left py-2 pr-2">Sembol</th>
                <th className="text-left py-2 pr-2">Yön</th>
                <th className="text-right py-2 pr-2">Giriş</th>
                <th className="text-right py-2 pr-2">Çıkış</th>
                <th className="text-right py-2 pr-2">PnL</th>
                <th className="text-left py-2 pr-2">Neden</th>
                <th className="text-right py-2 pr-2" title="Lehte / aleyhte en uç hareket (%)">MFE·MAE</th>
                <th className="text-left py-2 pr-2" title="Kapanış öz-değerlendirmesi">Değ.</th>
                <th className="text-left py-2 pr-2">Tip</th>
                <th className="text-right py-2">Tarih</th>
              </tr>
            </thead>
            <tbody>
              {trades.map(t => {
                const isOpen    = t.status === 'open'
                const isChecked = selected.has(t.id)
                const pnlColor  = (t.pnl_usdt ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                const reasonColor =
                  t.exit_reason === 'TP' ? 'bg-green-900/60 text-green-300' :
                  t.exit_reason === 'SL' ? 'bg-red-900/60 text-red-300' :
                  'bg-slate-700 text-slate-300'
                const isPaper = (t as any).paper === 1 || (t as any).paper === true
                const rowOpacity =
                  t.status === 'cancelled' ? 'opacity-40' :
                  t.status === 'open' ? 'opacity-80' : ''
                const rowBg = isChecked ? 'bg-indigo-900/20' : 'hover:bg-slate-800/40'

                return (
                  <tr
                    key={t.id}
                    onClick={() => toggleOne(t.id, isOpen)}
                    className={`border-b border-slate-800 transition cursor-pointer ${rowOpacity} ${rowBg}`}
                  >
                    <td className="py-1.5 pr-2">
                      <input
                        type="checkbox"
                        checked={isChecked}
                        disabled={isOpen}
                        onChange={() => toggleOne(t.id, isOpen)}
                        onClick={e => e.stopPropagation()}
                        className="accent-indigo-500 cursor-pointer disabled:opacity-30"
                      />
                    </td>
                    <td className="py-1.5 pr-2 font-medium text-white">{t.symbol}</td>
                    <td className="py-1.5 pr-2">
                      <span className={`px-1.5 py-0.5 rounded text-xs font-semibold ${t.side === 'LONG' ? 'bg-green-900/60 text-green-300' : 'bg-red-900/60 text-red-300'}`}>
                        {t.side}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{t.entry_price.toFixed(2)}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums text-slate-300">{t.exit_price?.toFixed(2) ?? '—'}</td>
                    <td className={`py-1.5 pr-2 text-right tabular-nums font-medium ${t.pnl_usdt != null ? pnlColor : 'text-slate-500'}`}>
                      {t.pnl_usdt != null
                        ? `${t.pnl_usdt >= 0 ? '+' : ''}${t.pnl_usdt.toFixed(3)}`
                        : t.status === 'open' ? 'açık' : '—'}
                    </td>
                    <td className="py-1.5 pr-2">
                      {t.exit_reason
                        ? <span className={`px-1.5 py-0.5 rounded text-xs ${reasonColor}`}>{t.exit_reason}</span>
                        : <span className="text-slate-600 text-xs">{t.status}</span>
                      }
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums text-slate-400">
                      {t.mfe_pct != null && t.mae_pct != null
                        ? <><span className="text-green-500/80">{t.mfe_pct.toFixed(2)}</span><span className="text-slate-600">·</span><span className="text-red-500/80">{t.mae_pct.toFixed(2)}</span></>
                        : '—'}
                    </td>
                    <td className="py-1.5 pr-2">
                      {t.self_eval && EVAL_TR[t.self_eval]
                        ? <span className={`px-1.5 py-0.5 rounded text-xs ${EVAL_TR[t.self_eval].cls}`}>{EVAL_TR[t.self_eval].label}</span>
                        : <span className="text-slate-600 text-xs">—</span>}
                    </td>
                    <td className="py-1.5 pr-2">
                      <span className={`px-1.5 py-0.5 rounded text-xs ${isPaper ? 'bg-teal-900/60 text-teal-300' : 'bg-orange-900/60 text-orange-300'}`}>
                        {isPaper ? 'Paper' : 'Canlı'}
                      </span>
                    </td>
                    <td className="py-1.5 text-right text-slate-400 tabular-nums whitespace-nowrap">{fmtTs(t.entry_ts)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
