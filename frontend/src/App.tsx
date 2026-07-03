import LiveDashboard from './components/LiveDashboard'

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6 rounded-3xl border border-slate-800 bg-slate-900/80 p-6">
          <h1 className="text-2xl font-semibold text-white">Futures Scalping Bot</h1>
          <p className="mt-1 text-slate-400 text-sm">BTC/USDT · ETH/USDT · USDT-M Futures · Dinamik Kaldıraç 3–10x</p>
        </div>
        <LiveDashboard />
      </div>
    </div>
  )
}
