import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Cpu, Play, Pause, TrendingUp, Clock3 } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { BotStatus, TradeRecord, fetchBotStatus, fetchPositions, fetchTrades, startBot, stopBot } from './api'

interface PositionSummary {
  symbol: string
  price: number
}

function formatDate(ts?: number) {
  return ts ? new Date(ts).toLocaleString() : '-'
}

function App() {
  const [status, setStatus] = useState<BotStatus | null>(null)
  const [openPositions, setOpenPositions] = useState<PositionSummary[]>([])
  const [trades, setTrades] = useState<TradeRecord[]>([])
  const [statusText, setStatusText] = useState('Loading...')
  const [chartData, setChartData] = useState<Array<{ name: string; value: number }>>([])
  const [liveLogs, setLiveLogs] = useState<string[]>([])

  const loadData = async () => {
    try {
      const statusData = await fetchBotStatus()
      const positionsPayload = await fetchPositions()
      const tradesPayload = await fetchTrades()

      setStatus(statusData)
      setStatusText(statusData.is_running ? 'Running' : 'Stopped')
      setOpenPositions(
        positionsPayload.open_positions.map((position: any) => ({
          symbol: position.symbol,
          price: position.entry_price,
        })),
      )
      setTrades(tradesPayload)

      setChartData([
        { name: 'Open', value: statusData.open_positions },
        { name: 'Closed', value: statusData.closed_positions },
      ])
    } catch (error) {
      setStatusText('API unavailable')
    }
  }

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 5000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const ws = new WebSocket(`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/ws/updates`)
    ws.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload.messages?.length) {
          setLiveLogs((previous) => [
            ...payload.messages.map((message: string) => `${new Date().toLocaleTimeString()}: ${message}`),
            ...previous,
          ].slice(0, 10))
        }
      } catch (error) {
        console.error('WS parse error', error)
      }
      loadData()
    })
    return () => ws.close()
  }, [])

  const tradeSummary = useMemo(
    () => ({
      totalTrades: trades.length,
      wins: trades.filter((trade) => trade.profit_loss && trade.profit_loss > 0).length,
      losses: trades.filter((trade) => trade.profit_loss && trade.profit_loss <= 0).length,
    }),
    [trades],
  )

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.25em] text-slate-500">Crypto Scalping Bot</p>
            <h1 className="text-3xl font-semibold text-white">TradeBot Dashboard</h1>
            <p className="mt-2 text-slate-400">Gerçek zamanlı bot durumu, pozisyonlar ve performans raporu.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              className="inline-flex items-center gap-2 rounded-xl bg-emerald-500 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-emerald-400"
              onClick={async () => {
                await startBot()
                loadData()
              }}
            >
              <Play size={16} /> Başlat
            </button>
            <button
              className="inline-flex items-center gap-2 rounded-xl bg-slate-700 px-4 py-3 text-sm font-semibold text-slate-100 transition hover:bg-slate-600"
              onClick={async () => {
                await stopBot()
                loadData()
              }}
            >
              <Pause size={16} /> Durdur
            </button>
          </div>
        </header>

        <section className="grid gap-6 lg:grid-cols-3">
          <div className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 shadow-lg shadow-slate-950/20">
            <p className="text-sm text-slate-500">Bot Durumu</p>
            <div className="mt-4 flex items-center gap-3">
              <Cpu className="h-10 w-10 rounded-2xl bg-slate-800 p-2 text-emerald-400" />
              <div>
                <p className="text-3xl font-semibold text-white">{statusText}</p>
                <p className="text-sm text-slate-400">Model: {status?.model_loaded ? 'Yüklendi' : 'Beklemede'}</p>
              </div>
            </div>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl bg-slate-950/70 p-4">
                <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Açık pozisyon</p>
                <p className="mt-2 text-2xl font-semibold text-white">{status?.open_positions ?? '-'}</p>
              </div>
              <div className="rounded-2xl bg-slate-950/70 p-4">
                <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Kapalı işlemler</p>
                <p className="mt-2 text-2xl font-semibold text-white">{status?.closed_positions ?? '-'}</p>
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 shadow-lg shadow-slate-950/20 lg:col-span-2">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm text-slate-500">Piyasa Raporu</p>
                <h2 className="text-xl font-semibold text-white">Pozisyon & Trade Eğrisi</h2>
              </div>
              <div className="rounded-2xl bg-slate-950/75 px-4 py-2 text-sm text-slate-300">Güncelleme periyodu: 5s</div>
            </div>
            <div className="mt-6 h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#334155" />
                  <XAxis dataKey="name" stroke="#94a3b8" />
                  <YAxis stroke="#94a3b8" allowDecimals={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={3} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>

        <section className="mt-8 grid gap-6 lg:grid-cols-2">
          <div className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 shadow-lg shadow-slate-950/20">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm text-slate-500">Açık Pozisyonlar</p>
                <h2 className="text-xl font-semibold text-white">Şu an takipte</h2>
              </div>
              <ArrowRight className="text-slate-400" />
            </div>
            <div className="space-y-4">
              {openPositions.length === 0 ? (
                <p className="text-slate-400">Açık pozisyon bulunmuyor.</p>
              ) : (
                openPositions.map((position) => (
                  <div key={position.symbol} className="rounded-3xl bg-slate-950/75 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-semibold text-white">{position.symbol}</p>
                      <p className="text-slate-400">{position.price.toFixed(2)} USD</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 shadow-lg shadow-slate-950/20">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm text-slate-500">Trade Geçmişi</p>
                <h2 className="text-xl font-semibold text-white">Son işlemler</h2>
              </div>
              <TrendingUp className="text-slate-400" />
            </div>
            <div className="space-y-3">
              {trades.slice(0, 5).map((trade) => (
                <div key={trade.id} className="rounded-3xl bg-slate-950/75 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-semibold text-white">{trade.symbol}</p>
                      <p className="text-sm text-slate-400">{trade.side.toUpperCase()}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-slate-400">PnL</p>
                      <p className={`font-semibold ${trade.profit_loss && trade.profit_loss > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {trade.profit_loss?.toFixed(4) ?? '-'}
                      </p>
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{formatDate(trade.entry_timestamp)}</p>
                </div>
              ))}
              {trades.length === 0 && <p className="text-slate-400">Henüz işlem geçmişi yok.</p>}
            </div>
          </div>
        </section>

        <section className="mt-8 rounded-3xl border border-slate-800 bg-slate-900/80 p-6 shadow-lg shadow-slate-950/20">
          <div className="flex items-center gap-3">
            <Clock3 className="h-5 w-5 text-sky-400" />
            <p className="text-sm text-slate-500">Bot simülasyon döngüsü, her 30 saniyede bir veri çeker ve pozisyonları günceller.</p>
          </div>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <div className="rounded-3xl bg-slate-950/75 p-4">
              <p className="text-sm text-slate-400">Toplam işlem</p>
              <p className="mt-2 text-2xl font-semibold text-white">{tradeSummary.totalTrades}</p>
            </div>
            <div className="rounded-3xl bg-slate-950/75 p-4">
              <p className="text-sm text-slate-400">Kârda</p>
              <p className="mt-2 text-2xl font-semibold text-emerald-400">{tradeSummary.wins}</p>
            </div>
            <div className="rounded-3xl bg-slate-950/75 p-4">
              <p className="text-sm text-slate-400">Zarar</p>
              <p className="mt-2 text-2xl font-semibold text-rose-400">{tradeSummary.losses}</p>
            </div>
          </div>
        </section>

        <section className="mt-8 rounded-3xl border border-slate-800 bg-slate-900/80 p-6 shadow-lg shadow-slate-950/20">
          <div className="mb-4 flex items-center gap-3">
            <p className="text-lg font-semibold text-white">Canlı Bot Logları</p>
          </div>
          <div className="max-h-56 overflow-y-auto rounded-3xl bg-slate-950/80 p-4 text-sm text-slate-300">
            {liveLogs.length === 0 ? (
              <p className="text-slate-500">Bekleniyor... Bot döngüsü başlatıldığında burada olaylar görünecek.</p>
            ) : (
              <ul className="space-y-2">
                {liveLogs.map((log, index) => (
                  <li key={index} className="rounded-2xl bg-slate-900/80 px-3 py-2 text-slate-200">
                    {log}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

export default App
