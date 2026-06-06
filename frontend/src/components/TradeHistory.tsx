import { useEffect, useState } from 'react'
import { fetchTrades, type Trade } from '../api'

function fmtTs(ts: number) {
  return new Date(ts).toLocaleString('tr-TR')
}

export default function TradeHistory() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchTrades(50)
      .then(setTrades)
      .catch(e => setError(e?.message ?? 'Hata'))
  }, [])

  if (error) return <div className="text-red-400 text-sm">{error}</div>
  if (!trades.length) {
    return <div className="text-slate-500 text-sm text-center py-8">Henüz işlem yok</div>
  }

  const cumPnl = trades
    .filter(t => t.pnl_usdt !== null)
    .reduce((acc, t) => acc + (t.pnl_usdt ?? 0), 0)

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center text-sm">
        <span className="text-slate-400">{trades.length} işlem</span>
        <span className={`font-semibold tabular-nums ${cumPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          Toplam: {cumPnl >= 0 ? '+' : ''}{cumPnl.toFixed(2)} USDT
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-400 border-b border-slate-700">
              <th className="text-left py-2 pr-3">Sembol</th>
              <th className="text-left py-2 pr-3">Yön</th>
              <th className="text-right py-2 pr-3">Giriş</th>
              <th className="text-right py-2 pr-3">Çıkış</th>
              <th className="text-right py-2 pr-3">PnL</th>
              <th className="text-left py-2 pr-3">Neden</th>
              <th className="text-right py-2">Tarih</th>
            </tr>
          </thead>
          <tbody>
            {trades.map(t => {
              const pnlColor = (t.pnl_usdt ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
              const reasonColor =
                t.exit_reason === 'TP' ? 'bg-green-900/60 text-green-300' :
                t.exit_reason === 'SL' ? 'bg-red-900/60 text-red-300' :
                'bg-slate-700 text-slate-300'
              return (
                <tr key={t.id} className="border-b border-slate-800 hover:bg-slate-800/40">
                  <td className="py-1.5 pr-3 font-medium text-white">{t.symbol}</td>
                  <td className="py-1.5 pr-3">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-semibold ${t.side === 'LONG' ? 'bg-green-900/60 text-green-300' : 'bg-red-900/60 text-red-300'}`}>
                      {t.side}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{t.entry_price.toFixed(2)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{t.exit_price?.toFixed(2) ?? '—'}</td>
                  <td className={`py-1.5 pr-3 text-right tabular-nums font-medium ${pnlColor}`}>
                    {t.pnl_usdt !== null ? `${t.pnl_usdt >= 0 ? '+' : ''}${t.pnl_usdt.toFixed(3)}` : '—'}
                  </td>
                  <td className="py-1.5 pr-3">
                    {t.exit_reason && (
                      <span className={`px-1.5 py-0.5 rounded text-xs ${reasonColor}`}>{t.exit_reason}</span>
                    )}
                  </td>
                  <td className="py-1.5 text-right text-slate-400 text-xs">{fmtTs(t.entry_ts)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
