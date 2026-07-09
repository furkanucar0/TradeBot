import { useEffect, useRef } from 'react'
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'

import { apiHeaders, API_BASE } from '../apiConfig'

interface Props {
  symbol: 'BTC' | 'ETH'
  markers?: SeriesMarker<Time>[]
  latestCandle?: CandlestickData<Time> | null
  startTs?: number  // Unix saniye — bot başladığından itibaren mumları göster
}

export default function CandleChart({ symbol, markers = [], latestCandle, startTs = 0 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)
  const candleRef    = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volRef       = useRef<ISeriesApi<'Histogram'> | null>(null)
  // v5: markers plugin ayrı tutulur
  const markersPluginRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null)
  const lastTimeRef  = useRef<number>(0)

  // Chart kurulumu — symbol değişince yeniden oluşturulur
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: false,
      },
      width:  containerRef.current.clientWidth,
      height: 360,
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor:         '#22c55e',
      downColor:       '#ef4444',
      borderUpColor:   '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor:     '#22c55e',
      wickDownColor:   '#ef4444',
    })

    const volSeries = chart.addSeries(HistogramSeries, {
      color:        '#334155',
      priceFormat:  { type: 'volume' },
      priceScaleId: 'vol',
    })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } })

    // v5: marker plugin oluştur
    const markersPlugin = createSeriesMarkers(candleSeries, [])

    chartRef.current       = chart
    candleRef.current      = candleSeries
    volRef.current         = volSeries
    markersPluginRef.current = markersPlugin

    // İlk yükleme
    const loadCandles = (fit = false) => {
      const url = startTs > 0
        ? `${API_BASE}/candles/${symbol}?since=${startTs}&limit=500`
        : `${API_BASE}/candles/${symbol}?limit=120`
      fetch(url, { headers: apiHeaders() })
        .then(r => r.json())
        .then((data: any[]) => {
          if (!data.length) return
          const candles: CandlestickData<Time>[] = data.map(d => ({
            time:  d.time as Time,
            open:  d.open,
            high:  d.high,
            low:   d.low,
            close: d.close,
          }))
          const vols: HistogramData<Time>[] = data.map(d => ({
            time:  d.time as Time,
            value: d.volume,
            color: d.close >= d.open ? '#16a34a40' : '#dc262640',
          }))

          // Sadece yeni mumları güncelle (tam setData yerine)
          const newLast = data[data.length - 1]?.time ?? 0
          if (fit || newLast > lastTimeRef.current) {
            if (fit) {
              candleSeries.setData(candles)
              volSeries.setData(vols)
              chartRef.current?.timeScale().fitContent()
            } else {
              // Sadece sonuncusunu güncelle
              const last = candles[candles.length - 1]
              const lastVol = vols[vols.length - 1]
              candleSeries.update(last)
              volSeries.update(lastVol)
              chartRef.current?.timeScale().scrollToRealTime()
            }
            lastTimeRef.current = newLast
          }
        })
        .catch(() => null)
    }

    loadCandles(true)

    // 30 saniyede bir yeni mumları çek
    const pollId = setInterval(() => loadCandles(false), 30_000)

    // Responsive resize
    const ro = new ResizeObserver(() => {
      if (containerRef.current)
        chart.applyOptions({ width: containerRef.current.clientWidth })
    })
    ro.observe(containerRef.current)

    return () => {
      clearInterval(pollId)
      ro.disconnect()
      chart.remove()
      chartRef.current       = null
      candleRef.current      = null
      volRef.current         = null
      markersPluginRef.current = null
    }
  }, [symbol, startTs])

  // Marker güncelle (v5 API)
  useEffect(() => {
    markersPluginRef.current?.setMarkers(markers)
  }, [markers])

  // Canlı mum güncelle
  useEffect(() => {
    if (!latestCandle || !candleRef.current) return
    const t = latestCandle.time as number
    if (t < lastTimeRef.current) return
    candleRef.current.update(latestCandle)
    lastTimeRef.current = t
  }, [latestCandle])

  return (
    <div className="w-full">
      <div ref={containerRef} className="w-full rounded-xl overflow-hidden" />
    </div>
  )
}
