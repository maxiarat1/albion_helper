import GoldPriceChart from '../../components/charts/GoldPriceChart'

export default function GoldPricePanel({
  goldData,
  goldBusy,
  goldError,
  goldRange,
  setGoldRange,
  fetchGoldPrices,
}) {
  return (
    <section className="panel">
      <h2>Gold Price</h2>
      {goldData && goldData.latest_price && (
        <div className="db-status">
          <div className="db-stat">
            <div className="db-stat-label">Current Rate</div>
            <div className="db-stat-value">{goldData.latest_price.toLocaleString()} silver</div>
          </div>
          <div className="db-stat">
            <div className="db-stat-label">Updated</div>
            <div className="db-stat-value">
              {goldData.latest_timestamp
                ? new Date(goldData.latest_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                : '—'}
            </div>
          </div>
          <div className="db-stat">
            <div className="db-stat-label">Data Points</div>
            <div className="db-stat-value">{goldData.count || 0}</div>
          </div>
        </div>
      )}
      <div className="gold-range-bar">
        {[['day', '24h'], ['week', '7d'], ['month', '30d']].map(([value, label]) => (
          <button
            key={value}
            className={`gold-range-btn${goldRange === value ? ' active' : ''}`}
            onClick={() => setGoldRange(value)}
            disabled={goldBusy}
          >
            {label}
          </button>
        ))}
        <button
          className="gold-range-btn refresh"
          onClick={() => fetchGoldPrices()}
          disabled={goldBusy}
        >
          {goldBusy ? 'Loading...' : 'Refresh'}
        </button>
      </div>
      <GoldPriceChart data={goldData?.data} />
      {goldError && <div className="error">{goldError}</div>}
    </section>
  )
}
