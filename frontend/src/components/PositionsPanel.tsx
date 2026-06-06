import { useEffect, useState } from 'react'
import { fetchPositions, type Trade } from '../api'

export default function PositionsPanel() {
  const [positions, setPositions] = useState<Trade[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = () =>
      fetchPositions()
        .then(setPositions)
        .catch(e => setError(e?.message ?? 'Hata'))

    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  if (error) return <div className="text-red-400 text-sm">{error}</div>
  if (!positions.length) {
    return <div className="text-slate-500 text-sm text-center py-8">Açık pozisyon yok</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-400 border-b border-slate-700">
            <th className="text-left py-2 pr-4">Sembol</th>
            <th className="text-left py-2 pr-4">Yön</th>
            <th className="text-right py-2 pr-4">Giriş</th>
            <th className="text-right py-2 pr-4">Miktar</th>
            <th className="text-right py-2 pr-4">Notional</th>
            <th className="text-right py-2">Durum</th>
          </tr>
        </thead>
        <tbody>
          {positions.map(p => (
            <tr key={p.id} className="border-b border-slate-800 hover:bg-slate-800/50">
              <td className="py-2 pr-4 font-medium text-white">{p.symbol}</td>
              <td className="py-2 pr-4">
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${p.side === 'LONG' ? 'bg-green-900/60 text-green-300' : 'bg-red-900/60 text-red-300'}`}>
                  {p.side}
                </span>
              </td>
              <td className="py-2 pr-4 text-right tabular-nums">{p.entry_price.toFixed(4)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{p.quantity_usdt} USDT</td>
              <td className="py-2 pr-4 text-right tabular-nums">{p.notional} USDT</td>
              <td className="py-2 text-right">
                <span className="px-2 py-0.5 rounded text-xs bg-blue-900/60 text-blue-300">{p.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
