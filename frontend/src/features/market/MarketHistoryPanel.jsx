import MarketPriceChart from '../../components/charts/MarketPriceChart'
import { ItemReference } from '../../components/items/ItemText'
import { DEFAULT_MARKET_CITIES } from '../../shared/constants'

export default function MarketHistoryPanel({
  marketItem,
  setMarketItem,
  marketQuality,
  setMarketQuality,
  marketStartDate,
  setMarketStartDate,
  marketEndDate,
  setMarketEndDate,
  marketCities,
  setMarketCities,
  marketIncludeLatestApi,
  setMarketIncludeLatestApi,
  marketBusy,
  marketError,
  marketResult,
  fetchMarketPrices,
  itemLabels,
}) {
  const toDomIdToken = (value) => {
    const token = String(value ?? '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, '-')
      .replace(/^-+|-+$/g, '')
    return token || 'value'
  }

  return (
    <section className="panel">
      <h2>Market Price History</h2>
      <div className="market-form">
        <label>
          Item
          <input
            id="market-item"
            name="market_item"
            type="text"
            value={marketItem}
            onChange={(e) => setMarketItem(e.target.value)}
            placeholder="T4 Bag"
          />
        </label>
        <label>
          Quality (optional)
          <select
            id="market-quality"
            name="market_quality"
            value={marketQuality}
            onChange={(e) => setMarketQuality(e.target.value)}
          >
            <option value="">All Qualities</option>
            <option value="1">Quality 1</option>
            <option value="2">Quality 2</option>
            <option value="3">Quality 3</option>
            <option value="4">Quality 4</option>
            <option value="5">Quality 5</option>
          </select>
        </label>
        <label>
          Start Date (optional)
          <input
            id="market-start-date"
            name="market_start_date"
            type="date"
            value={marketStartDate}
            onChange={(e) => setMarketStartDate(e.target.value)}
          />
        </label>
        <label>
          End Date (optional)
          <input
            id="market-end-date"
            name="market_end_date"
            type="date"
            value={marketEndDate}
            onChange={(e) => setMarketEndDate(e.target.value)}
          />
        </label>
        <div className="city-filters">
          <div className="city-filters-label">Cities (optional - select to filter)</div>
          <div className="city-checkboxes">
            {DEFAULT_MARKET_CITIES.map((city) => (
              <label key={city} className="city-checkbox">
                <input
                  id={`market-city-${toDomIdToken(city)}`}
                  name={`market_city_${city}`}
                  type="checkbox"
                  checked={marketCities.has(city)}
                  onChange={(e) => {
                    const newCities = new Set(marketCities)
                    if (e.target.checked) {
                      newCities.add(city)
                    } else {
                      newCities.delete(city)
                    }
                    setMarketCities(newCities)
                  }}
                />
                {city}
              </label>
            ))}
          </div>
        </div>
        <label className="latest-api-toggle">
          <input
            id="market-include-latest-api"
            name="market_include_latest_api"
            type="checkbox"
            checked={marketIncludeLatestApi}
            onChange={(e) => setMarketIncludeLatestApi(e.target.checked)}
          />
          Include latest live API prices
        </label>
        <button className="send" onClick={fetchMarketPrices} disabled={marketBusy}>
          {marketBusy ? 'Loading…' : 'Fetch History'}
        </button>
      </div>

      {marketError && <div className="error">{marketError}</div>}

      {marketResult && (
        <div className="market-result">
          <div className="market-meta">
            Item:{' '}
            <ItemReference
              itemId={marketResult.item?.id}
              itemLabels={itemLabels}
              fallbackName={marketResult.item?.display_name}
            />{' '}
            ·
            Records: {marketResult.record_count} ·
            Source: {marketResult.source}
            {marketResult.latest_market && !marketResult.latest_market.error && ' · Latest API overlay enabled'}
            {marketResult.latest_market?.error && ' · Latest API overlay failed'}
          </div>
          <MarketPriceChart data={marketResult.data} latestMarket={marketResult.latest_market} />
        </div>
      )}
    </section>
  )
}
