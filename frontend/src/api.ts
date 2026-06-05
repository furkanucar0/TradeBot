import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export interface BotStatus {
  is_running: boolean
  open_positions: number
  closed_positions: number
  last_cycle?: number
  model_loaded: boolean
  symbol_watchlist: string[]
}

export interface TradeRecord {
  id: number
  symbol: string
  side: string
  entry_price: number
  exit_price?: number
  quantity: number
  entry_timestamp: number
  exit_timestamp?: number
  profit_loss?: number
  status: string
  stop_loss?: number
  take_profit?: number
}

export const fetchBotStatus = () => axios.get<BotStatus>(`${API_BASE}/bot/status`).then(res => res.data)
export const fetchPositions = () => axios.get(`${API_BASE}/positions`).then(res => res.data)
export const fetchTrades = () => axios.get<TradeRecord[]>(`${API_BASE}/trades`).then(res => res.data)
export const startBot = () => axios.post(`${API_BASE}/bot/start`)
export const stopBot = () => axios.post(`${API_BASE}/bot/stop`)
