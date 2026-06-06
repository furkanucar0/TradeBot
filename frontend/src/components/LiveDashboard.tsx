import { useEffect, useRef, useState } from 'react'
import ModelMetrics from './ModelMetrics'
import PositionsPanel from './PositionsPanel'
import TradeHistory from './TradeHistory'
import {
  fetchBacktest, fetchStatus, startBot, stopBot, triggerTrain,
  type BacktestSummary, type BotStatus,
} from '../api'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const WS_HOSTS = [
  API_BASE.replace(/^http/, 'ws'),
  'ws://127.0.0.1:8000',
  'ws://localhost:8000',
]

type LogLevel = 'info' | 'system' | 'trade_open' | 'profit' | 'loss' | 'error' | 'signal'

interface LogEntry { ts: number; level: LogLevel; msg: string }
interface ProgressState { msg: string; pct: number }
interface GridRow { sl: number; tp: number; wr: number; rr: number }

function logColor(l: LogLevel) {
  if (l === 'profit') return 'text-green-400 bg-green-900/20 border-green-800'
  if (l === 'loss') return 'text-red-400 bg-red-900/20 border-red-800'
  if (l === 'error') return 'text-red-300 bg-red-900/30 border-red-700'
  if (l === 'trade_open') return 'text-cyan-300 bg-cyan-900/20 border-cyan-800'
  if (l === 'signal') return 'text-yellow-300 bg-yellow-900/10 border-yellow-800'
  if (l === 'system') return 'text-blue-300 bg-blue-900/20 border-blue-800'
  return 'text-slate-300 bg-slate-800/40 border-slate-700'
}

export default function LiveDashboard() {
  const [status, setStatus] = useState<BotStatus | null>(null)
  const [summary, setSummary] = useState<BacktestSummary | null>(null)
  const [equityUrl, setEquityUrl] = useState<string | null>(null)
  const [progress, setProgress] = useState<ProgressState>({ msg: 'Bekleniyor...', pct: 0 })
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [gridRows, setGridRows] = useState<GridRow[]>([])
  const [activeTab, setActiveTab] = useState<'log' | 'grid'>('log')
  const [testnet, setTestnet] = useState(true)
  const logsRef = useRef<HTMLDivElement>(null)

  // Status polling
  useEffect(() => {
    const load = () => fetchStatus().then(setStatus).catch(() => null)
    load()
    const id = setInterval(load, 8000)
    return () => clearInterval(id)
  }, [])

  // Backtest sonucu (sayfa açılışında)
  useEffect(() => {
    fetchBacktest()
      .then(d => {
        setSummary(d)
        setEquityUrl(`${API_BASE}/reports/equity_curve.png?t=${Date.now()}`)
      })
      .catch(() => null)
  }, [])

  // WebSocket bağlantısı
  useEffect(() => {
    let ws: WebSocket | null = null
    let hostIdx = 0
    let retryTimer: ReturnType<typeof setTimeout>

    const pushLog = (level: LogLevel, msg: string) =>
      setLogs(prev => [{ ts: Date.now(), level, msg }, ...prev].slice(0, 500))

    const handleEvent = (ev: Record<string, any>) => {
      const phase = ev.phase as string | undefined

      if (phase === 'grid_search') {
        setProgress({ msg: ev.msg || 'Grid search...', pct: ev.progress || 15 })
        if (ev.sl_pct !== undefined) {
          setGridRows(prev => [
            { sl: ev.sl_pct, tp: ev.tp_pct, wr: ev.win_rate, rr: ev.rr },
            ...prev,
          ].slice(0, 50))
        }
      } else if (phase === 'labeling' || phase === 'features' || phase === 'data') {
        setProgress({ msg: ev.msg || phase, pct: ev.progress || 10 })
        pushLog('info', ev.msg || phase)
      } else if (phase === 'training') {
        setProgress({ msg: ev.msg || 'Eğitim...', pct: ev.progress || 50 })
        pushLog('info', ev.msg || 'Eğitim...')
      } else if (phase === 'backtest') {
        setProgress({ msg: ev.msg || 'Backtest...', pct: ev.progress || 90 })
        if (ev.summary) {
          setSummary(ev.summary)
          setEquityUrl(`${API_BASE}/reports/equity_curve.png?t=${Date.now()}`)
        }
      } else if (phase === 'complete') {
        setProgress({ msg: ev.msg || 'Tamamlandı', pct: 100 })
        if (ev.summary) setSummary(ev.summary)
        fetchStatus().then(setStatus).catch(() => null)
      } else if (phase === 'trade_open') {
        pushLog('trade_open', `${ev.symbol} LONG AÇILDI @ ${ev.entry} | SL=${ev.sl} TP=${ev.tp}`)
      } else if (phase === 'trade_close') {
        const lvl = ev.result === 'TP' ? 'profit' : 'loss'
        pushLog(lvl, `${ev.symbol} KAPANDI [${ev.result}] PnL=${ev.pnl >= 0 ? '+' : ''}${Number(ev.pnl).toFixed(4)} USDT`)
      } else if (phase === 'signal') {
        if (ev.pred === 1) pushLog('signal', `${ev.symbol} SİNYAL p=${(ev.proba * 100).toFixed(1)}%`)
      } else if (phase === 'error') {
        pushLog('error', ev.msg || 'Hata')
      } else if (phase === 'server') {
        pushLog('system', ev.msg || 'Sunucu mesajı')
      } else if (ev.msg) {
        pushLog('info', ev.msg)
      }
    }

    const connect = () => {
      const host = WS_HOSTS[hostIdx % WS_HOSTS.length]
      hostIdx++
      ws = new WebSocket(host + '/ws')
      ws.onopen = () => pushLog('system', `WS bağlandı: ${host}`)
      ws.onmessage = e => { try { handleEvent(JSON.parse(e.data)) } catch { } }
      ws.onerror = () => { ws?.close() }
      ws.onclose = () => {
        pushLog('system', 'WS kapandı, yeniden bağlanılıyor...')
        retryTimer = setTimeout(connect, 3000)
      }
    }

    connect()
    return () => {
      ws?.close()
      clearTimeout(retryTimer)
    }
  }, [])

  useEffect(() => {
    if (logsRef.current) logsRef.current.scrollTop = 0
  }, [logs])

  const handleTrain = async () => {
    try {
      await triggerTrain()
      setProgress({ msg: 'Eğitim tetiklendi...', pct: 1 })
    } catch (e: any) {
      setLogs(prev => [{ ts: Date.now(), level: 'error', msg: e?.response?.data?.detail || e?.message }, ...prev])
    }
  }

  const handleStart = async () => {
    try {
      await startBot(testnet)
    } catch (e: any) {
      setLogs(prev => [{ ts: Date.now(), level: 'error', msg: e?.response?.data?.detail || e?.message }, ...prev])
    }
  }

  const handleStop = async () => {
    try {
      await stopBot()
    } catch (e: any) {
      setLogs(prev => [{ ts: Date.now(), level: 'error', msg: e?.response?.data?.detail || e?.message }, ...prev])
    }
  }

  const ready = status?.ready_for_live ?? false

  return (
    <div className="space-y-6">

      {/* ── Kontrol Şeridi ────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/80 px-5 py-4">
        <button
          onClick={handleTrain}
          disabled={status?.is_training}
          className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm font-medium transition"
        >
          {status?.is_training ? 'Eğitiliyor...' : 'Eğitimi Başlat'}
        </button>

        <button
          onClick={handleStart}
          disabled={status?.is_running || !status?.model_exists}
          className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm font-medium transition"
        >
          Botu Başlat
        </button>

        <button
          onClick={handleStop}
          disabled={!status?.is_running}
          className="px-4 py-2 rounded-lg bg-red-700 hover:bg-red-600 disabled:opacity-40 text-sm font-medium transition"
        >
          Durdur
        </button>

        <label className="flex items-center gap-2 text-sm cursor-pointer select-none ml-2">
          <input
            type="checkbox"
            checked={testnet}
            onChange={e => setTestnet(e.target.checked)}
            className="accent-indigo-500"
          />
          <span className={testnet ? 'text-yellow-300' : 'text-red-400 font-semibold'}>
            {testnet ? 'Testnet' : '⚠️ Mainnet'}
          </span>
        </label>

        <div className="ml-auto flex flex-wrap gap-3 text-xs text-slate-400">
          <span>Açık Poz: <strong className="text-white">{status?.open_positions ?? '—'}</strong></span>
          <span>WR: <strong className={ready ? 'text-green-400' : 'text-yellow-400'}>{status?.last_win_rate != null ? `${(status.last_win_rate * 100).toFixed(1)}%` : '—'}</strong></span>
          <span>R:R: <strong className={ready ? 'text-green-400' : 'text-yellow-400'}>{status?.last_rr?.toFixed(2) ?? '—'}</strong></span>
          {ready && <span className="text-green-400 font-semibold">✓ Canlı Trade Hazır</span>}
          {!ready && status?.model_exists && <span className="text-yellow-400">Kriter bekleniyor (WR&gt;60% + R:R&gt;2.0)</span>}
        </div>
      </div>

      {/* ── Progress ─────────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/80 px-5 py-4">
        <div className="flex justify-between mb-2 text-sm">
          <span className="text-slate-300">{progress.msg}</span>
          <span className="text-slate-500 tabular-nums">{progress.pct}%</span>
        </div>
        <div className="h-2.5 w-full rounded-full bg-slate-800 overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-teal-400 transition-all duration-500"
            style={{ width: `${Math.min(Math.max(progress.pct, 0), 100)}%` }}
          />
        </div>
      </div>

      {/* ── Ana Grid (Log + Model Metrics) ───────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">

        {/* Log Paneli */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
          <div className="flex gap-3 mb-3 border-b border-slate-800 pb-2">
            <button
              onClick={() => setActiveTab('log')}
              className={`text-sm font-medium pb-1 ${activeTab === 'log' ? 'text-white border-b-2 border-indigo-500' : 'text-slate-400'}`}
            >
              Canlı Akış
            </button>
            <button
              onClick={() => setActiveTab('grid')}
              className={`text-sm font-medium pb-1 ${activeTab === 'grid' ? 'text-white border-b-2 border-indigo-500' : 'text-slate-400'}`}
            >
              R:R Grid Search {gridRows.length > 0 && `(${gridRows.length})`}
            </button>
          </div>

          {activeTab === 'log' && (
            <div ref={logsRef} className="h-72 overflow-y-auto space-y-1.5 pr-1">
              {logs.length === 0
                ? <div className="text-slate-500 text-sm text-center mt-8">Henüz olay yok — backend bağlantısı bekleniyor</div>
                : logs.map((l, i) => (
                  <div key={i} className={`rounded-lg border px-3 py-1.5 text-xs ${logColor(l.level)}`}>
                    <span className="text-slate-500 mr-2">{new Date(l.ts).toLocaleTimeString()}</span>
                    {l.msg}
                  </div>
                ))}
            </div>
          )}

          {activeTab === 'grid' && (
            <div className="h-72 overflow-y-auto">
              {gridRows.length === 0
                ? <div className="text-slate-500 text-sm text-center mt-8">Grid search henüz çalışmadı</div>
                : (
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-slate-900">
                      <tr className="text-slate-400 border-b border-slate-700">
                        <th className="text-right pr-3 py-1">SL</th>
                        <th className="text-right pr-3 py-1">TP</th>
                        <th className="text-right pr-3 py-1">Win Rate</th>
                        <th className="text-right py-1">R:R</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gridRows.map((r, i) => (
                        <tr key={i} className="border-b border-slate-800">
                          <td className="text-right pr-3 py-1 tabular-nums">{(r.sl * 100).toFixed(1)}%</td>
                          <td className="text-right pr-3 py-1 tabular-nums">{(r.tp * 100).toFixed(1)}%</td>
                          <td className={`text-right pr-3 py-1 tabular-nums ${r.wr >= 0.6 ? 'text-green-400' : 'text-slate-300'}`}>
                            {(r.wr * 100).toFixed(1)}%
                          </td>
                          <td className={`text-right py-1 tabular-nums ${r.rr >= 2 ? 'text-green-400' : 'text-slate-300'}`}>
                            {r.rr.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
            </div>
          )}
        </div>

        {/* Model Metrics Paneli */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
          <div className="text-sm font-medium text-white mb-4 border-b border-slate-800 pb-2">Model Metrikleri</div>
          <ModelMetrics summary={summary} equityUrl={equityUrl} />
        </div>
      </div>

      {/* ── Alt Grid (Positions + Trade History) ─────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">

        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
          <div className="text-sm font-medium text-white mb-4 border-b border-slate-800 pb-2">Açık Pozisyonlar</div>
          <PositionsPanel />
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
          <div className="text-sm font-medium text-white mb-4 border-b border-slate-800 pb-2">İşlem Geçmişi</div>
          <TradeHistory />
        </div>

      </div>
    </div>
  )
}
