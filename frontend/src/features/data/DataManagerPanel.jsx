export default function DataManagerPanel({
  dbStatus,
  dbLoading,
  dbUpdating,
  dbUpdateResult,
  dbUpdateProgress,
  dbResetting,
  dbResetResult,
  triggerDbUpdate,
  finishDbUpdateFlow,
  hardResetDatabase,
  formatNumber,
}) {
  const stageLabelMap = {
    starting: 'Starting update',
    fetching_index: 'Fetching dump index',
    planning: 'Planning imports',
    processing: 'Preparing dumps',
    dropping_indexes: 'Dropping indexes',
    downloading: 'Downloading dump',
    importing: 'Importing records',
    recreating_indexes: 'Recreating indexes',
    completed: 'Update completed',
    failed: 'Update failed',
    idle: 'Idle',
  }

  const formatDuration = (seconds) => {
    if (typeof seconds !== 'number' || Number.isNaN(seconds) || seconds < 0) {
      return '--'
    }
    const totalSeconds = Math.round(seconds)
    const mins = Math.floor(totalSeconds / 60)
    const secs = totalSeconds % 60
    return `${mins}m ${secs}s`
  }

  const progressPct = Math.max(0, Math.min(100, Number(dbUpdateProgress?.progress_pct || 0)))
  const progressStatus = dbUpdateProgress?.status
  const showProgress = ['running', 'completed', 'failed'].includes(progressStatus)
  const canFinishProgress = progressStatus === 'completed' || progressStatus === 'failed'
  const stageLabel = stageLabelMap[dbUpdateProgress?.stage] || 'Updating database'

  return (
    <section className="panel data-manager">
      <h2>Market Data Manager</h2>
      {dbLoading ? (
        <div className="db-empty-state">Loading database status...</div>
      ) : !dbStatus ? (
        <div className="db-empty-state">
          <p>Unable to load database status</p>
          <button className="send" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      ) : (
        <>
          <div className="db-status">
            <div className="db-stat">
              <div className="db-stat-label">Total Records</div>
              <div className="db-stat-value">{formatNumber(dbStatus.database?.total_records || 0)}</div>
            </div>
            <div className="db-stat">
              <div className="db-stat-label">Imported Dumps</div>
              <div className="db-stat-value">{dbStatus.database?.imported_dumps_count || 0}</div>
            </div>
          </div>

          <div className="download-section">
            <div className="download-header">
              <h3>Coverage</h3>
            </div>
            <p className="download-info">
              {dbStatus.database?.date_range?.earliest && dbStatus.database?.date_range?.latest
                ? `Data available from ${dbStatus.database.date_range.earliest} to ${dbStatus.database.date_range.latest}.`
                : 'No historical data imported yet.'}
            </p>
            <p className="download-info">
              Recommended strategy: newest daily full snapshot only.
            </p>
            {dbStatus.updates_available?.recommended?.[0]?.name && (
              <p className="download-info">
                Next recommended import: <code>{dbStatus.updates_available.recommended[0].name}</code>
              </p>
            )}
            {showProgress && (
              <div className={`db-progress db-progress-${dbUpdateProgress.status || 'running'}`}>
                <div className="db-progress-header">
                  <span className="db-progress-stage">{stageLabel}</span>
                  <span className="db-progress-percent">{Math.round(progressPct)}%</span>
                </div>
                <div className="db-progress-track">
                  <div className="db-progress-fill" style={{ width: `${progressPct}%` }} />
                </div>
                <div className="db-progress-message">{dbUpdateProgress.message || 'Working...'}</div>
                <div className="db-progress-meta">
                  <span>Elapsed: {formatDuration(dbUpdateProgress.elapsed_seconds)}</span>
                  <span>
                    ETA: {typeof dbUpdateProgress.eta_seconds === 'number' ? formatDuration(dbUpdateProgress.eta_seconds) : 'calculating...'}
                  </span>
                  <span>Dumps: {dbUpdateProgress.completed_dumps || 0}/{dbUpdateProgress.total_dumps || 0}</span>
                </div>
                {(dbUpdateProgress.records_parsed || dbUpdateProgress.records_imported) ? (
                  <div className="db-progress-meta">
                    <span>Parsed: {formatNumber(dbUpdateProgress.records_parsed || 0)}</span>
                    <span>Imported: {formatNumber(dbUpdateProgress.records_imported || 0)}</span>
                  </div>
                ) : null}
                {dbUpdateProgress.current_dump && (
                  <div className="db-progress-message">
                    Current dump: <code>{dbUpdateProgress.current_dump}</code>
                  </div>
                )}
                {canFinishProgress && (
                  <div className="db-progress-actions">
                    <button className="clear" onClick={finishDbUpdateFlow}>
                      Finish
                    </button>
                  </div>
                )}
              </div>
            )}
            <div className="download-action">
              <button
                className="send"
                onClick={triggerDbUpdate}
                disabled={dbUpdating}
              >
                {dbUpdating ? 'Importing...' : 'Import Recommended Update'}
              </button>
              <button
                className="clear"
                onClick={hardResetDatabase}
                disabled={dbResetting || dbUpdating}
              >
                {dbResetting ? 'Resetting...' : 'Hard Reset Database'}
              </button>
            </div>
            {dbUpdateResult && (
              <div className={`download-result ${dbUpdateResult.success ? 'success' : 'error'}`}>
                {dbUpdateResult.success
                  ? `Imported ${dbUpdateResult.total_records?.toLocaleString() || 0} records from ${dbUpdateResult.imported?.length || 0} file(s)`
                  : `Error: ${dbUpdateResult.errors?.[0] || 'Import failed'}`}
              </div>
            )}
            {dbResetResult && (
              <div className={`download-result ${dbResetResult.success ? 'success' : 'error'}`}>
                {dbResetResult.success
                  ? `Reset complete: removed ${dbResetResult.reset?.removed_records || 0} records and ${dbResetResult.reset?.removed_imports || 0} imports`
                  : `Reset error: ${dbResetResult.error || 'Reset failed'}`}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  )
}
