import type { BacktestSummary } from '../api'

interface Props {
  summary: BacktestSummary | null
  equityUrl: string | null
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-slate-800 rounded-xl p-4">
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      <div className={`text-xl font-bold tabular-nums ${color ?? 'text-white'}`}>{value}</div>
    </div>
  )
}

export default function ModelMetrics({ summary, equityUrl }: Props) {
  if (!summary) {
    return (
      <div className="flex items-center justify-center h-40 text-slate-500 text-sm">
        Henüz backtest sonucu yok — eğitimi başlatın
      </div>
    )
  }

  const pnlColor = summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'
  const wrColor = summary.win_rate >= 0.6 ? 'text-green-400' : 'text-yellow-400'
  const rrColor = summary.rr >= 2 ? 'text-green-400' : 'text-yellow-400'
  const ddColor = summary.max_drawdown > 0.2 ? 'text-red-400' : 'text-slate-200'

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Win Rate" value={`${(summary.win_rate * 100).toFixed(1)}%`} color={wrColor} />
        <Stat label="R:R" value={summary.rr.toFixed(2)} color={rrColor} />
        <Stat label="Net PnL" value={`${summary.total_pnl >= 0 ? '+' : ''}${summary.total_pnl.toFixed(2)} USDT`} color={pnlColor} />
        <Stat label="Max Drawdown" value={`${(summary.max_drawdown * 100).toFixed(1)}%`} color={ddColor} />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Toplam İşlem" value={String(summary.trades)} />
        <Stat label="Sharpe" value={summary.sharpe.toFixed(2)} />
        <Stat label="SL / TP" value={`${(summary.sl_pct * 100).toFixed(1)}% / ${(summary.tp_pct * 100).toFixed(1)}%`} />
        <Stat label="Kaldıraç" value={`${summary.leverage}x`} />
      </div>

      {(summary.precision !== undefined) && (
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Precision" value={(summary.precision ?? 0).toFixed(4)} />
          <Stat label="F1-Score" value={(summary.f1 ?? 0).toFixed(4)} />
          <Stat label="Accuracy" value={(summary.accuracy ?? 0).toFixed(4)} />
        </div>
      )}

      {equityUrl && (
        <div>
          <div className="text-xs text-slate-400 mb-2">Equity Curve</div>
          <img src={equityUrl} alt="equity curve" className="w-full rounded-xl border border-slate-700 object-contain" />
        </div>
      )}
    </div>
  )
}
