import { useEffect, useRef, useState } from 'react'
import type { SeriesMarker, Time } from 'lightweight-charts'
import CandleChart from './CandleChart'
import ModelMetrics from './ModelMetrics'
import TradeHistory from './TradeHistory'
import {
  clearPanic, fetchBacktest, fetchStatus, panicBot, startBot, stopBot, triggerTrain,
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
interface WalletState {
  balance: number; start: number; pnl: number; pnl_pct: number;
  open_count: number; trade_count: number; unrealized?: number;
}

interface LivePosition {
  symbol: string; side: string; entry: number; current_price: number;
  tp: number; sl: number; upnl: number; upnl_pct: number;
  open_ts?: number; proba?: number; db_id?: number;
  margin?: number; notional?: number; leverage?: number;
}

interface HealthComponent { weight: number; points: number; label: string }
interface HealthState {
  score: number; status: string;
  components: Record<string, HealthComponent>;
  balance?: number; open_positions?: number; daily_paused?: boolean;
  health_paused?: boolean; panic?: boolean;
}

// FAZ 4 (K-20): sinyal kararı — gerekçe koduyla
interface DecisionDetail {
  proba_long?: number; proba_short?: number;
  thr_long?: number; thr_short?: number;
  ob?: number; adx?: number;
}
interface DecisionState {
  symbol: string; blocked_by: string | null; direction: string | null;
  proba: number | null; threshold: number | null; opened: boolean;
  detail: DecisionDetail; ts: number;
}

const REASON_TR: Record<string, string> = {
  NO_SIGNAL:     'Sinyal yok — eşik altı',
  ADX_RANGING:   'ADX düşük — piyasa yönsüz',
  TREND_VETO:    '1h trend aleyhte — veto',
  OB_IMBALANCE:  'Emir defteri aleyhte',
  MAX_POSITIONS: 'Maks. pozisyon dolu',
  BUFFER_SHORT:  'Veri buffer doluyor',
  NO_PRICE:      'Anlık fiyat bekleniyor',
  NO_FEATURES:   'Özellik hesaplanamadı',
}

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
  const [wallet, setWallet] = useState<WalletState | null>(null)
  const [livePositions, setLivePositions] = useState<LivePosition[]>([])
  const [botStartTs, setBotStartTs] = useState(0)
  const [chartSymbol, setChartSymbol] = useState<'BTC' | 'ETH'>('BTC')
  const [tradeMarkers, setTradeMarkers] = useState<Record<'BTC' | 'ETH', SeriesMarker<Time>[]>>({ BTC: [], ETH: [] })
  const [health, setHealth] = useState<HealthState | null>(null)
  const [decisions, setDecisions] = useState<Record<string, DecisionState>>({})
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

    // İşlem olaylarını grafikte marker olarak göster
    const pushMarker = (symbol: string | undefined, marker: SeriesMarker<Time>) => {
      const key = symbol?.startsWith('BTC') ? 'BTC' : symbol?.startsWith('ETH') ? 'ETH' : null
      if (!key) return
      setTradeMarkers(prev => ({ ...prev, [key]: [...prev[key], marker].slice(-100) }))
    }
    const evMinute = (ev: Record<string, any>): Time =>
      (Math.floor((ev.ts ?? Date.now() / 1000) / 60) * 60) as Time

    const handleEvent = (ev: Record<string, any>) => {
      const phase = ev.phase as string | undefined

      if (phase === 'bot_start') {
        setBotStartTs(ev.ts as number)
        setLivePositions([])
      } else if (phase === 'positions') {
        setLivePositions(ev.positions ?? [])
      } else if (phase === 'grid_search') {
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
        // Eğitim bitti → backtest metriklerini ve equity grafiğini güncelle
        fetchBacktest()
          .then(d => {
            setSummary(d)
            setEquityUrl(`${API_BASE}/reports/equity_curve.png?t=${Date.now()}`)
          })
          .catch(() => null)
      } else if (phase === 'signal') {
        if (ev.pred === 1) {
          const obStr  = ev.ob_imbalance !== undefined ? ` | OB=${ev.ob_imbalance > 0 ? '+' : ''}${ev.ob_imbalance.toFixed(2)}` : ''
          const fngStr = ev.fng !== undefined ? ` | F&G=${ev.fng}` : ''
          pushLog('signal', `${ev.symbol} ${ev.direction ?? ''} SİNYAL p=${(ev.proba * 100).toFixed(1)}%${obStr}${fngStr} @ ${ev.price ?? ''}`)
        }
      } else if (phase === 'wallet') {
        setWallet({
          balance:     ev.balance,
          start:       ev.start,
          pnl:         ev.pnl,
          pnl_pct:     ev.pnl_pct,
          open_count:  ev.open_count,
          trade_count: ev.trade_count,
          unrealized:  ev.unrealized,
        })
      } else if (phase === 'trade_open') {
        pushLog('trade_open', `${ev.symbol} ${ev.side || 'LONG'} AÇILDI @ ${ev.entry} | SL=${ev.sl} TP=${ev.tp}${ev.paper ? ' [PAPER]' : ''}`)
        pushMarker(ev.symbol, {
          time: evMinute(ev),
          position: 'belowBar',
          shape: ev.side === 'SHORT' ? 'arrowDown' : 'arrowUp',
          color: ev.side === 'SHORT' ? '#ef4444' : '#22c55e',
          text: `${ev.side ?? 'LONG'}`,
        })
      } else if (phase === 'trade_close') {
        const lvl = ev.result === 'TP' ? 'profit' : 'loss'
        const pctStr = ev.pnl_pct !== undefined ? ` (${ev.pnl_pct >= 0 ? '+' : ''}${Number(ev.pnl_pct).toFixed(2)}%)` : ''
        pushLog(lvl, `${ev.symbol} KAPANDI [${ev.result}]${ev.paper ? ' [PAPER]' : ''} ${ev.pnl >= 0 ? '+' : ''}${Number(ev.pnl).toFixed(4)} USDT${pctStr}`)
        pushMarker(ev.symbol, {
          time: evMinute(ev),
          position: 'aboveBar',
          shape: 'circle',
          color: ev.result === 'TP' ? '#22c55e' : ev.result === 'SL' ? '#ef4444' : '#eab308',
          text: `${ev.result} ${ev.pnl >= 0 ? '+' : ''}${Number(ev.pnl).toFixed(2)}`,
        })
      } else if (phase === 'trade_analysis') {
        const wrStr = `Son ${ev.rolling_n} işlem WR: ${(ev.rolling_wr * 100).toFixed(0)}%`
        const probaStr = `Sinyal gücü: ${(ev.proba * 100).toFixed(1)}%`
        const verdict = ev.correct ? '✓ Doğru tahmin' : '✗ Yanlış tahmin'
        pushLog('info', `ANALİZ ${ev.symbol} — ${verdict} | ${probaStr} | ${wrStr} | Ort sinyal: ${(ev.avg_proba * 100).toFixed(1)}%`)
      } else if (phase === 'health') {
        setHealth(ev as unknown as HealthState)
      } else if (phase === 'decision') {
        setDecisions(prev => ({
          ...prev,
          [ev.symbol]: {
            symbol: ev.symbol, blocked_by: ev.blocked_by ?? null,
            direction: ev.direction ?? null, proba: ev.proba ?? null,
            threshold: ev.threshold ?? null, opened: !!ev.opened,
            detail: ev.detail ?? {}, ts: (ev.ts ?? Date.now() / 1000) * 1000,
          },
        }))
      } else if (phase === 'error') {
        pushLog('error', ev.msg || 'Hata')
      } else if (phase === 'server') {
        pushLog('system', ev.msg || 'Sunucu mesajı')
      } else if (ev.msg) {
        pushLog('info', ev.msg)
      }
    }

    let alive = true   // StrictMode çift mount'unu önler

    const connect = () => {
      if (!alive) return
      const host = WS_HOSTS[hostIdx % WS_HOSTS.length]
      hostIdx++
      ws = new WebSocket(host + '/ws')
      ws.onopen = () => { if (alive) pushLog('system', `WS bağlandı: ${host}`) }
      ws.onmessage = e => { try { if (alive) handleEvent(JSON.parse(e.data)) } catch { } }
      ws.onerror = () => { ws?.close() }
      ws.onclose = () => {
        if (!alive) return
        pushLog('system', 'WS kapandı, yeniden bağlanılıyor...')
        retryTimer = setTimeout(connect, 3000)
      }
    }

    connect()
    return () => {
      alive = false
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

  const handlePanic = async () => {
    if (!window.confirm('🚨 PANİK: Tüm pozisyonlar kapatılacak, bot durdurulacak ve kilitlenecek. Emin misin?')) return
    try {
      await panicBot()
      fetchStatus().then(setStatus).catch(() => null)
    } catch (e: any) {
      setLogs(prev => [{ ts: Date.now(), level: 'error', msg: e?.response?.data?.detail || e?.message }, ...prev])
    }
  }

  const handleClearPanic = async () => {
    try {
      await clearPanic()
      fetchStatus().then(setStatus).catch(() => null)
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
          className={`px-4 py-2 rounded-lg disabled:opacity-40 text-sm font-medium transition ${
            testnet
              ? 'bg-teal-700 hover:bg-teal-600'
              : 'bg-emerald-600 hover:bg-emerald-500'
          }`}
        >
          {status?.is_running
            ? 'Çalışıyor...'
            : testnet
              ? 'Paper Test Başlat'
              : 'Canlı Trade Başlat'}
        </button>

        <button
          onClick={handleStop}
          disabled={!status?.is_running}
          className="px-4 py-2 rounded-lg bg-red-700 hover:bg-red-600 disabled:opacity-40 text-sm font-medium transition"
        >
          Durdur
        </button>

        {/* Kill switch (FAZ 3 — K-19) */}
        {status?.panic ? (
          <button
            onClick={handleClearPanic}
            className="px-4 py-2 rounded-lg bg-amber-700 hover:bg-amber-600 text-sm font-bold transition"
          >
            🔓 Kilidi Kaldır
          </button>
        ) : (
          <button
            onClick={handlePanic}
            className="px-4 py-2 rounded-lg bg-red-950 border border-red-600 hover:bg-red-900 text-red-300 text-sm font-bold transition"
          >
            🚨 PANİK
          </button>
        )}
        {status?.panic && (
          <span className="text-red-400 text-xs font-bold animate-pulse">
            🚨 PANİK KİLİDİ AKTİF — bot başlatılamaz
          </span>
        )}

        {/* Mod seçici */}
        <div className="flex rounded-lg overflow-hidden border border-slate-700 text-xs font-medium ml-1">
          <button
            onClick={() => setTestnet(true)}
            className={`px-3 py-2 transition ${testnet ? 'bg-teal-700 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
          >
            Paper
          </button>
          <button
            onClick={() => setTestnet(false)}
            className={`px-3 py-2 transition ${!testnet ? 'bg-red-700 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
          >
            Canlı
          </button>
        </div>
        {!testnet && (
          <span className="text-red-400 text-xs font-semibold animate-pulse">
            ⚠ GERÇEK PARA
          </span>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-slate-400">
          {/* Demo Kasa */}
          {wallet && testnet && (
            <div className="flex items-center gap-2 bg-slate-800 border border-slate-700 rounded-xl px-3 py-1.5">
              <span className="text-slate-400">Demo:</span>
              <span className="font-mono font-bold text-white text-sm">
                {wallet.balance.toFixed(2)} USDT
              </span>
              <span className={`font-mono text-xs ${wallet.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {wallet.pnl >= 0 ? '+' : ''}{wallet.pnl.toFixed(2)} ({wallet.pnl_pct >= 0 ? '+' : ''}{wallet.pnl_pct.toFixed(1)}%)
              </span>
              {wallet.unrealized !== undefined && wallet.open_count > 0 && (
                <span className={`font-mono text-xs opacity-70 ${wallet.unrealized >= 0 ? 'text-emerald-400' : 'text-orange-400'}`}>
                  [{wallet.unrealized >= 0 ? '+' : ''}{wallet.unrealized.toFixed(2)}]
                </span>
              )}
              <span className="text-slate-500">{wallet.trade_count} işlem</span>
            </div>
          )}

          <span>Poz: <strong className="text-white">{wallet?.open_count ?? status?.open_positions ?? '—'}</strong></span>
          <span>WR: <strong className={ready ? 'text-green-400' : 'text-yellow-400'}>{status?.last_win_rate != null ? `${(status.last_win_rate * 100).toFixed(1)}%` : '—'}</strong></span>
          <span>R:R: <strong className={ready ? 'text-green-400' : 'text-yellow-400'}>{status?.last_rr?.toFixed(2) ?? '—'}</strong></span>
          {ready && <span className="text-green-400 font-semibold">✓ Hazır</span>}
          {!ready && status?.model_exists && <span className="text-yellow-400">Kriter bekleniyor</span>}
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${testnet ? 'bg-teal-900 text-teal-300' : 'bg-red-900 text-red-300'}`}>
            {testnet ? 'PAPER' : 'CANLI'}
          </span>
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

      {/* ── Sistem Sağlığı Şeridi (FAZ 2) ────────────────────────────── */}
      {health && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl border border-slate-800 bg-slate-900/80 px-5 py-3">
          <div className="flex items-center gap-2">
            <span
              className={`text-2xl font-bold tabular-nums ${
                health.score >= 75 ? 'text-green-400' : health.score >= 50 ? 'text-yellow-400' : 'text-red-400'
              }`}
            >
              {health.score}
            </span>
            <div className="leading-tight">
              <div className="text-xs font-semibold text-white">Sağlık</div>
              <div
                className={`text-[10px] font-medium ${
                  health.score >= 75 ? 'text-green-500' : health.score >= 50 ? 'text-yellow-500' : 'text-red-500'
                }`}
              >
                {health.status}
              </div>
            </div>
          </div>
          <div className="h-8 w-px bg-slate-800" />
          {Object.entries(health.components).map(([k, c]) => (
            <div key={k} className="text-xs leading-tight">
              <div className="text-slate-200 tabular-nums font-medium">
                {c.points.toFixed(0)}<span className="text-slate-500">/{c.weight}</span>
              </div>
              <div className="text-slate-500">{c.label}</div>
            </div>
          ))}
          {(health.daily_paused || health.health_paused || health.panic) && (
            <div className="ml-auto flex items-center gap-2">
              {health.panic && (
                <span className="rounded bg-red-900/70 px-2 py-1 text-xs font-bold text-red-300 animate-pulse">
                  🚨 Panik kilidi
                </span>
              )}
              {health.health_paused && (
                <span className="rounded bg-orange-900/60 px-2 py-1 text-xs font-medium text-orange-300">
                  ⛔ Sağlık duraklatması
                </span>
              )}
              {health.daily_paused && (
                <span className="rounded bg-amber-900/60 px-2 py-1 text-xs font-medium text-amber-300">
                  ⏸ Günlük fren aktif
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Karar Paneli (FAZ 4 — K-20): neden işlem var/yok ─────────── */}
      {Object.keys(decisions).length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 px-5 py-4">
          <div className="text-sm font-medium text-white mb-3 border-b border-slate-800 pb-2">
            Karar Paneli <span className="text-xs text-slate-500 ml-1">son sinyal değerlendirmesi · gerekçeli</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.values(decisions).map(d => {
              const label = d.opened
                ? `${d.direction} AÇILDI`
                : REASON_TR[d.blocked_by ?? ''] ?? d.blocked_by ?? '—'
              const chipCls = d.opened
                ? 'bg-green-900/60 text-green-300'
                : d.blocked_by === 'NO_SIGNAL'
                  ? 'bg-slate-800 text-slate-400'
                  : 'bg-red-900/50 text-red-300'
              const det = d.detail ?? {}
              return (
                <div key={d.symbol} className="rounded-xl border border-slate-700 bg-slate-800/60 p-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-semibold text-white text-sm">{d.symbol}</span>
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-semibold ${chipCls}`}>{label}</span>
                      <span className="text-xs text-slate-500 tabular-nums">
                        {new Date(d.ts).toLocaleTimeString('tr-TR')}
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400 tabular-nums">
                    {det.proba_long !== undefined && det.thr_long !== undefined && (
                      <span>
                        L: <span className={det.proba_long >= det.thr_long ? 'text-green-400' : 'text-slate-300'}>
                          {(det.proba_long * 100).toFixed(1)}%
                        </span>
                        <span className="text-slate-600">/{(det.thr_long * 100).toFixed(1)}%</span>
                      </span>
                    )}
                    {det.proba_short !== undefined && det.thr_short !== undefined && (
                      <span>
                        S: <span className={det.proba_short >= det.thr_short ? 'text-green-400' : 'text-slate-300'}>
                          {(det.proba_short * 100).toFixed(1)}%
                        </span>
                        <span className="text-slate-600">/{(det.thr_short * 100).toFixed(1)}%</span>
                      </span>
                    )}
                    {det.adx !== undefined && <span>ADX: {det.adx}</span>}
                    {det.ob !== undefined && <span>OB: {det.ob > 0 ? '+' : ''}{det.ob}</span>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Canlı Grafik ─────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
        <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
          <div className="text-sm font-medium text-white">
            Canlı Grafik <span className="text-xs text-slate-500 ml-1">1m · işlem markerları</span>
          </div>
          <div className="flex rounded-lg overflow-hidden border border-slate-700 text-xs font-medium">
            {(['BTC', 'ETH'] as const).map(s => (
              <button
                key={s}
                onClick={() => setChartSymbol(s)}
                className={`px-3 py-1.5 transition ${
                  chartSymbol === s
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                }`}
              >
                {s}/USDT
              </button>
            ))}
          </div>
        </div>
        <CandleChart symbol={chartSymbol} markers={tradeMarkers[chartSymbol]} startTs={botStartTs} />
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

      {/* ── Demo Kasa Kartı + Alt Grid ───────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">

        {/* Demo Kasa Detay */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
          <div className="text-sm font-medium text-white mb-4 border-b border-slate-800 pb-2">
            Demo Kasa {testnet && <span className="text-teal-400 text-xs ml-1">PAPER</span>}
          </div>
          {wallet ? (
            <div className="space-y-3">
              <div className="flex justify-between items-baseline">
                <span className="text-slate-400 text-sm">Bakiye</span>
                <span className="font-mono text-xl font-bold text-white">{wallet.balance.toFixed(2)} USDT</span>
              </div>
              <div className="flex justify-between items-baseline">
                <span className="text-slate-400 text-sm">Net P&L</span>
                <span className={`font-mono text-lg font-semibold ${wallet.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {wallet.pnl >= 0 ? '+' : ''}{wallet.pnl.toFixed(2)} USDT
                </span>
              </div>
              {wallet.unrealized !== undefined && wallet.open_count > 0 && (
                <div className="flex justify-between items-baseline">
                  <span className="text-slate-400 text-sm">Açık Kar/Zarar</span>
                  <span className={`font-mono text-sm ${wallet.unrealized >= 0 ? 'text-emerald-400' : 'text-orange-400'}`}>
                    {wallet.unrealized >= 0 ? '+' : ''}{wallet.unrealized.toFixed(2)} USDT
                  </span>
                </div>
              )}
              <div className="flex justify-between items-baseline">
                <span className="text-slate-400 text-sm">Getiri</span>
                <span className={`font-mono font-semibold ${wallet.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {wallet.pnl_pct >= 0 ? '+' : ''}{wallet.pnl_pct.toFixed(2)}%
                </span>
              </div>
              <div className="flex justify-between text-xs text-slate-500 pt-2 border-t border-slate-800">
                <span>Açık: {wallet.open_count}</span>
                <span>Toplam: {wallet.trade_count} işlem</span>
                <span>Başlangıç: {wallet.start} USDT</span>
              </div>
            </div>
          ) : (
            <div className="text-slate-500 text-sm text-center py-8">
              <div className="text-2xl mb-2">💼</div>
              <div>Paper test başlatınca</div>
              <div>kasa burada görünür</div>
              <div className="mt-3 font-mono text-slate-600">100 USDT ile başlar</div>
            </div>
          )}
        </div>

        {/* Açık Pozisyonlar — anlık WS verisi */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
          <div className="text-sm font-medium text-white mb-4 border-b border-slate-800 pb-2">
            Açık Pozisyonlar
            {livePositions.length > 0 && (
              <span className="ml-2 text-xs text-teal-400">{livePositions.length} açık</span>
            )}
          </div>
          {livePositions.length === 0 ? (
            <div className="text-slate-500 text-sm text-center py-8">Açık pozisyon yok</div>
          ) : (
            <div className="space-y-3">
              {livePositions.map(pos => {
                const upnlColor = pos.upnl >= 0 ? 'text-green-400' : 'text-red-400'
                const pct = pos.upnl_pct ?? 0
                const margin   = pos.margin   ?? 10
                const notional = pos.notional ?? margin * (pos.leverage ?? 10)
                const lev      = pos.leverage ?? 10
                return (
                  <div key={pos.symbol} className="rounded-xl border border-slate-700 bg-slate-800/60 p-3 space-y-2">
                    {/* Başlık satırı */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-white text-sm">{pos.symbol}</span>
                        {pos.open_ts && (
                          <span className="text-xs text-slate-500 tabular-nums">
                            {new Date(pos.open_ts).toLocaleTimeString('tr-TR')}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-bold ${pos.side === 'LONG' ? 'bg-green-900/60 text-green-300' : 'bg-red-900/60 text-red-300'}`}>
                          {pos.side}
                        </span>
                        <button
                          onClick={() =>
                            fetch(`${API_BASE}/positions/${encodeURIComponent(pos.symbol)}/close`, { method: 'POST' })
                          }
                          className="px-2 py-0.5 rounded text-xs font-medium bg-slate-700 hover:bg-red-800/70 text-slate-300 hover:text-red-200 transition"
                        >
                          Kapat
                        </button>
                      </div>
                    </div>

                    {/* Fiyat bilgisi */}
                    <div className="grid grid-cols-2 gap-x-4 text-xs text-slate-400">
                      <span>Giriş: <span className="text-white tabular-nums">{pos.entry.toFixed(2)}</span></span>
                      <span>Şu an: <span className="text-yellow-300 tabular-nums font-semibold">{pos.current_price.toFixed(2)}</span></span>
                      <span>TP: <span className="text-green-400 tabular-nums">{pos.tp.toFixed(2)}</span></span>
                      <span>SL: <span className="text-red-400 tabular-nums">{pos.sl.toFixed(2)}</span></span>
                    </div>

                    {/* PnL */}
                    <div className="flex items-baseline justify-between">
                      <span className={`text-base font-bold tabular-nums ${upnlColor}`}>
                        {pos.upnl >= 0 ? '+' : ''}{pos.upnl.toFixed(3)} USDT
                      </span>
                      <span className={`text-sm font-semibold tabular-nums ${upnlColor}`}>
                        {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                      </span>
                    </div>

                    {/* Marjin × Kaldıraç */}
                    <div className="flex items-center gap-1.5 text-xs pt-1 border-t border-slate-700/60">
                      <span className="text-slate-400 tabular-nums font-mono">{margin.toFixed(2)} USDT</span>
                      <span className="text-slate-600">×</span>
                      <span className="text-indigo-400 font-semibold">{lev}x</span>
                      <span className="text-slate-600">=</span>
                      <span className="text-slate-200 tabular-nums font-semibold">{notional.toFixed(2)} USDT</span>
                      {pos.proba !== undefined && (
                        <span className="ml-auto text-slate-500">
                          Sinyal: <span className="text-slate-300">{(pos.proba * 100).toFixed(1)}%</span>
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* İşlem Geçmişi */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
          <div className="text-sm font-medium text-white mb-4 border-b border-slate-800 pb-2">İşlem Geçmişi</div>
          <TradeHistory />
        </div>

      </div>
    </div>
  )
}
