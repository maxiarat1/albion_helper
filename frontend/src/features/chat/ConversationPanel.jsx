import { useState } from 'react'
import { HighlightedItemText, MarkdownMessageContent } from '../../components/items/ItemText'

const OUTCOME_LABELS = {
  tool_call: '🔧 tool call',
  final_answer: '💬 final answer',
  fallback: '⚡ fallback',
  fallback_error: '⚡ fallback error',
  unknown_tool: '❓ unknown tool',
  duplicate_blocked: '🔁 duplicate blocked',
  duplicate_halt: '🔁 duplicate halt',
  tool_error: '⚠️ tool error',
  api_error: '🔴 api error',
}

function RoundPanel({ round, isOpen, onToggle }) {
  const label = OUTCOME_LABELS[round.outcome] || round.outcome
  const hasError = round.outcome?.includes('error') || round.outcome === 'duplicate_halt'

  return (
    <div className={`debug-round ${hasError ? 'error' : ''}`}>
      <div className="debug-round-header" onClick={onToggle}>
        <span className="debug-round-label">
          Round {round.iteration}: {label}
        </span>
        {round.tool && (
          <span className="debug-round-tool">{round.tool}</span>
        )}
        <span className="debug-round-msg-count">
          {round.messages?.length || 0} msgs
        </span>
        <span className="debug-round-toggle">{isOpen ? '▾' : '▸'}</span>
      </div>
      {isOpen && (
        <div className="debug-round-body">
          <div className="debug-section">
            <div className="debug-section-title">Messages sent to LLM</div>
            <div className="debug-messages">
              {(round.messages || []).map((m, i) => (
                <div key={i} className={`debug-msg debug-msg-${m.role}`}>
                  <span className="debug-msg-role">{m.role}</span>
                  <pre className="debug-msg-content">{m.content}</pre>
                </div>
              ))}
            </div>
          </div>
          <div className="debug-section">
            <div className="debug-section-title">Model response</div>
            <pre className="debug-response">{round.response ?? '(no response)'}</pre>
          </div>
          {round.tool && (
            <div className="debug-section">
              <div className="debug-section-title">Parsed tool call</div>
              <pre className="debug-tool-info">
                {round.tool}({JSON.stringify(round.arguments, null, 2)})
              </pre>
            </div>
          )}
          {round.error && (
            <div className="debug-section">
              <div className="debug-section-title">Error</div>
              <pre className="debug-error">{round.error}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function ConversationPanel({
  conversation,
  expandedTools,
  setExpandedTools,
  itemLabels,
  resolvedQueries,
}) {
  const [expandedDebug, setExpandedDebug] = useState(new Set())
  const [openRounds, setOpenRounds] = useState(new Set())

  const toggleDebug = (idx) => {
    setExpandedDebug((prev) => {
      const next = new Set(prev)
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }

  const toggleRound = (msgIdx, roundIdx) => {
    const key = `${msgIdx}-${roundIdx}`
    setOpenRounds((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  return (
    <div className="conversation">
      {conversation.length === 0 ? (
        <div className="empty-state">No messages yet. Start a conversation!</div>
      ) : (
        conversation.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            <div className="message-role">
              {msg.role === 'user' ? 'You' : msg.model || 'Assistant'}
              {msg._meta?.tool_calls?.length > 0 && (
                <span
                  className={`tool-badge ${expandedTools.has(idx) ? 'active' : ''}`}
                  onClick={() => setExpandedTools((prev) => {
                    const next = new Set(prev)
                    next.has(idx) ? next.delete(idx) : next.add(idx)
                    return next
                  })}
                >
                  🔧 {msg._meta.tool_calls.length}
                </span>
              )}
              {msg._meta?.rounds?.length > 0 && (
                <span
                  className={`debug-badge ${expandedDebug.has(idx) ? 'active' : ''}`}
                  onClick={() => toggleDebug(idx)}
                >
                  🔍 {msg._meta.rounds.length}
                </span>
              )}
            </div>
            {expandedTools.has(idx) && msg._meta?.tool_calls?.length > 0 && (
              <div className="tool-details">
                {msg._meta.tool_calls.map((tc, i) => (
                  <div key={i} className={`tool-call-entry ${tc.success === false ? 'error' : ''}`}>
                    <div className="tool-call-header">
                      <span className="tool-call-name">{tc.tool}</span>
                      <span className="tool-call-args">
                        <HighlightedItemText
                          text={JSON.stringify(tc.arguments)}
                          itemLabels={itemLabels}
                          resolvedQueries={resolvedQueries}
                        />
                      </span>
                      {tc.success === false && <span className="tool-call-error">{tc.error}</span>}
                    </div>
                    {tc.result && (
                      <pre className="tool-call-result">
                        <HighlightedItemText
                          text={JSON.stringify(tc.result, null, 2)}
                          itemLabels={itemLabels}
                          resolvedQueries={resolvedQueries}
                        />
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
            {expandedDebug.has(idx) && msg._meta?.rounds?.length > 0 && (
              <div className="debug-panel">
                <div className="debug-panel-title">Tool Loop Debug Trace</div>
                {msg._meta.rounds.map((round, ri) => (
                  <RoundPanel
                    key={ri}
                    round={round}
                    isOpen={openRounds.has(`${idx}-${ri}`)}
                    onToggle={() => toggleRound(idx, ri)}
                  />
                ))}
              </div>
            )}
            <div className="message-content">
              {msg.role === 'assistant' ? (
                <MarkdownMessageContent
                  text={msg.content}
                  itemLabels={itemLabels}
                  resolvedQueries={resolvedQueries}
                />
              ) : (
                <span className="message-plain-text">
                  <HighlightedItemText
                    text={msg.content}
                    itemLabels={itemLabels}
                    resolvedQueries={resolvedQueries}
                  />
                </span>
              )}
            </div>
          </div>
        ))
      )}
    </div>
  )
}
