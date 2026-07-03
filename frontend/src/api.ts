import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const api = axios.create({ baseURL: BASE })

export interface BotStatus {
  is_running: boolean
  is_training: boolean
  ready_for_live: boolean
  model_exists: boolean
  open_positions: number
  last_win_rate: number | null
  last_rr: number | null
  last_trained: number | null
  symbols: string[]
}

export interface Trade {
  id: number
  symbol: string
  side: string
  leverage: number
  entry_price: number
  exit_price: number | null
  quantity_usdt: number
  notional: number
  entry_ts: number
  exit_ts: number | null
  exit_reason: string | null
  pnl_usdt: number | null
  status: string
}

export interface BacktestSummary {
  starting_cap: number
  final_cap: number
  total_pnl: number
  trades: number
  wins: number
  losses: number
  win_rate: number
  rr: number
  max_drawdown: number
  sharpe: number
  sl_pct: number
  tp_pct: number
  leverage: number
  precision?: number
  f1?: number
  accuracy?: number
  daily_avg_pct?: number
  daily_worst_pct?: number
  daily_best_pct?: number
  daily_std_pct?: number
  test_days?: number
}

export const fetchStatus = () => api.get<BotStatus>('/status').then(r => r.data)
export const fetchPositions = () => api.get<Trade[]>('/positions').then(r => r.data)
export const fetchTrades = (limit = 100, offset = 0) =>
  api.get<Trade[]>(`/trades?limit=${limit}&offset=${offset}`).then(r => r.data)
export const fetchBacktest = () => api.get<BacktestSummary>('/backtest').then(r => r.data)
export const triggerTrain = () => api.post('/train').then(r => r.data)
export const startBot = (testnet = true) => api.post(`/bot/start?testnet=${testnet}`).then(r => r.data)
export const stopBot = () => api.post('/bot/stop').then(r => r.data)
