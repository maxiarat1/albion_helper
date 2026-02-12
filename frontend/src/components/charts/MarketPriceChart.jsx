import { useEffect, useRef } from 'react'
import vegaEmbed from 'vega-embed'

const OUTLIER_CEILING = 995999

export default function MarketPriceChart({ data, latestMarket }) {
  const containerRef = useRef(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const isValidTimestamp = (value) => {
      if (value == null || value === '') return false
      const parsed = Date.parse(value)
      return Number.isFinite(parsed)
    }

    const toFiniteNumber = (value) => {
      const parsed = Number(value)
      return Number.isFinite(parsed) ? parsed : null
    }

    const chartData = []
    ;(data || []).forEach((row) => {
      const city = row.location || 'Unknown'
      const quality = row.quality || 1
      const timestamp = row.period
      const historySellPrice = toFiniteNumber(row.avg_sell_min)

      if (historySellPrice != null && historySellPrice <= OUTLIER_CEILING && isValidTimestamp(timestamp)) {
        chartData.push({
          timestamp,
          price: historySellPrice,
          city,
          quality: `Quality ${quality}`,
          source: 'history',
          source_label: 'Historical',
        })
      }
    })

    const latestData = latestMarket?.data || []
    const latestFallbackTimestamp = latestMarket?.fetched_at || null

    latestData.forEach((row) => {
      const city = row.location || 'Unknown'
      const quality = row.quality || 1
      const timestamp = row.sell_price_min_date || row.buy_price_min_date || latestFallbackTimestamp
      const quantityRaw = Number(row.item_count || 1)
      const quantity = Number.isFinite(quantityRaw) && quantityRaw > 0 ? quantityRaw : 1
      let latestSellPrice = null
      if (row.sell_price_min_per_item != null) {
        latestSellPrice = toFiniteNumber(row.sell_price_min_per_item)
      } else if (row.sell_price_min != null) {
        const sellPrice = toFiniteNumber(row.sell_price_min)
        latestSellPrice = sellPrice != null ? sellPrice / quantity : null
      }

      if (latestSellPrice != null && latestSellPrice <= OUTLIER_CEILING && isValidTimestamp(timestamp)) {
        chartData.push({
          timestamp,
          price: latestSellPrice,
          city,
          quality: `Quality ${quality}`,
          source: 'latest',
          source_label: 'Latest API',
        })
      }
    })

    if (chartData.length === 0) {
      container.innerHTML = ''
      return
    }

    const spec = {
      $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
      width: 'container',
      height: 400,
      data: { values: chartData },
      mark: 'area',
      encoding: {
        x: {
          field: 'timestamp',
          type: 'temporal',
          title: 'Date',
          axis: {
            labelAngle: -45,
            format: '%Y-%m-%d',
          },
        },
        y: {
          field: 'price',
          type: 'quantitative',
          title: 'Price Share',
          stack: 'normalize',
          axis: { format: '%' },
        },
        color: {
          field: 'city',
          type: 'nominal',
          title: 'City',
          scale: {
            scheme: 'category10',
          },
        },
        tooltip: [
          { field: 'source_label', type: 'nominal', title: 'Source' },
          { field: 'city', type: 'nominal', title: 'City' },
          { field: 'quality', type: 'nominal', title: 'Quality' },
          { field: 'price', type: 'quantitative', title: 'Price', format: ',.0f' },
          { field: 'timestamp', type: 'temporal', title: 'Date', format: '%Y-%m-%d' },
        ],
      },
      config: {
        background: 'transparent',
        view: { stroke: null },
      },
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
      .catch((error) => console.error('Error rendering chart:', error))

    return () => {
      active = false
      if (currentView) {
        currentView.finalize()
      }
      container.innerHTML = ''
    }
  }, [data, latestMarket])

  const hasHistory = (data || []).length > 0
  const hasLatest = Array.isArray(latestMarket?.data) && latestMarket.data.length > 0

  if (!hasHistory && !hasLatest) {
    return <div className="chart-empty">No data to display</div>
  }

  return <div className="market-chart" ref={containerRef}></div>
}
