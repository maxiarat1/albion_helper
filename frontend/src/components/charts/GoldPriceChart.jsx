import { useEffect, useRef } from 'react'
import vegaEmbed from 'vega-embed'

export default function GoldPriceChart({ data }) {
  const containerRef = useRef(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || !data || data.length === 0) {
      if (container) container.innerHTML = ''
      return
    }

    const chartData = data
      .filter((d) => d.price != null && d.timestamp)
      .map((d) => ({ timestamp: d.timestamp, price: d.price }))
      .reverse()

    if (chartData.length === 0) {
      container.innerHTML = ''
      return
    }

    const prices = chartData.map((d) => d.price)
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const avg = prices.reduce((s, v) => s + v, 0) / prices.length
    const spread = Math.max(max - avg, avg - min)
    const yDomain = [avg - spread, avg + spread]

    const spec = {
      $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
      width: 'container',
      height: 300,
      data: { values: chartData },
      encoding: {
        x: {
          field: 'timestamp',
          type: 'temporal',
          title: 'Time',
          axis: { labelAngle: -45, format: '%b %d %H:%M' },
        },
        y: {
          field: 'price',
          type: 'quantitative',
          title: 'Silver per Gold',
          scale: { domain: yDomain },
        },
      },
      layer: [
        { mark: { type: 'area', color: '#e8f5e9', opacity: 0.6 }, encoding: { y2: { datum: yDomain[0] } } },
        { mark: { type: 'line', color: 'darkgreen', strokeWidth: 1.5 } },
        {
          mark: { type: 'point', filled: true, color: 'darkgreen', size: 0, opacity: 0 },
          encoding: {
            tooltip: [
              { field: 'price', type: 'quantitative', title: 'Price', format: ',.0f' },
              { field: 'timestamp', type: 'temporal', title: 'Time', format: '%Y-%m-%d %H:%M' },
            ],
          },
          params: [{ name: 'hover', select: { type: 'point', on: 'pointerover', nearest: true } }],
        },
      ],
      config: { background: 'transparent', view: { stroke: null } },
    }

    let active = true
    let currentView = null

    vegaEmbed(container, spec, { actions: false })
      .then((result) => {
        if (!active) {
          result.view.finalize()
          return
        }
        currentView = result.view
      })
      .catch((err) => console.error('Gold chart error:', err))

    return () => {
      active = false
      if (currentView) currentView.finalize()
      container.innerHTML = ''
    }
  }, [data])

  if (!data || data.length === 0) {
    return <div className="chart-empty">No gold price data</div>
  }

  return <div className="market-chart" ref={containerRef}></div>
}
