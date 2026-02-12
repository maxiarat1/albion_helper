import ConversationPanel from './ConversationPanel'

export default function ChatWorkspace({
  provider,
  setProvider,
  model,
  handleModelChange,
  ollamaModels,
  loadingModels,
  apiKeys,
  handleApiKeyChange,
  message,
  setMessage,
  mcpEnabled,
  setMcpEnabled,
  mcpTools,
  mcpAllowed,
  setMcpAllowed,
  thinkingEnabled,
  setThinkingEnabled,
  ollamaThinkingModeType,
  ollamaThinkingModes,
  ollamaThinkMode,
  setOllamaThinkMode,
  ollamaThinkingSupported,
  sendMessage,
  busy,
  clearConversation,
  conversation,
  error,
  expandedTools,
  setExpandedTools,
  itemLabels,
  resolvedQueries,
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
    <>
      <div className="controls">
        <label>
          Provider
          <select id="provider" name="provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="ollama">ollama</option>
            <option value="openai">openai</option>
            <option value="anthropic">anthropic</option>
            <option value="gemini">gemini</option>
          </select>
        </label>
        <label>
          Model
          {provider === 'ollama' && ollamaModels.length > 0 ? (
            <select id="model" name="model" value={model} onChange={(e) => handleModelChange(e.target.value)}>
              {ollamaModels.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="model"
              name="model"
              type="text"
              value={model}
              onChange={(e) => handleModelChange(e.target.value)}
              placeholder={loadingModels ? 'Loading models...' : 'model name'}
              disabled={loadingModels}
            />
          )}
        </label>
      </div>

      {provider !== 'ollama' && (
        <label>
          API Key
          <input
            id={`${provider}-api-key`}
            name={`${provider}_api_key`}
            type="password"
            value={apiKeys[provider] || ''}
            onChange={(e) => handleApiKeyChange(e.target.value)}
            placeholder="Enter your API key"
          />
          <small style={{ color: '#999', fontSize: '0.8rem', marginTop: '0.25rem', display: 'block' }}>
            Stored locally in your browser
          </small>
        </label>
      )}

      <label className="message">
        Message
        <textarea
          id="message"
          name="message"
          rows="5"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ask a question..."
        />
      </label>

      <div className="mcp-controls">
        <label className="mcp-toggle">
          <input
            id="use-mcp-tools"
            name="use_mcp_tools"
            type="checkbox"
            checked={mcpEnabled}
            onChange={(e) => setMcpEnabled(e.target.checked)}
          />
          Use MCP tools for this message
        </label>

        {mcpEnabled && (
          <div className="mcp-panel">
            <div className="mcp-tool-list">
              <div className="mcp-title">Allowed tools</div>
              {mcpTools.length === 0 ? (
                <div className="mcp-empty">No tools loaded.</div>
              ) : (
                mcpTools.map((tool) => (
                  <label key={tool.name} className="mcp-checkbox">
                    <input
                      id={`mcp-tool-${toDomIdToken(tool.name)}`}
                      name={`mcp_tool_${tool.name}`}
                      type="checkbox"
                      checked={Boolean(mcpAllowed[tool.name])}
                      onChange={(e) =>
                        setMcpAllowed((prev) => ({
                          ...prev,
                          [tool.name]: e.target.checked,
                        }))
                      }
                    />
                    {tool.name}
                  </label>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      <div className="reasoning-controls">
        <label className="thinking-toggle">
          <input
            id="thinking-mode"
            name="thinking_mode"
            type="checkbox"
            checked={thinkingEnabled}
            onChange={(e) => setThinkingEnabled(e.target.checked)}
          />
          Thinking mode
        </label>
        <div className="thinking-note">
          Enables provider reasoning (OpenAI/Anthropic) and internal reflection after tool results.
        </div>
        {thinkingEnabled && provider === 'ollama' && ollamaThinkingModeType === 'levels' && (
          <label className="thinking-mode-select">
            Ollama thinking level
            <select
              id="ollama-thinking-level"
              name="ollama_thinking_level"
              value={ollamaThinkMode}
              onChange={(e) => setOllamaThinkMode(e.target.value)}
            >
              {ollamaThinkingModes.map((mode) => (
                <option key={mode} value={mode}>
                  {mode}
                </option>
              ))}
            </select>
          </label>
        )}
        {thinkingEnabled && provider === 'ollama' && ollamaThinkingSupported === false && (
          <div className="thinking-note">
            Selected model does not advertise native thinking; using automatic fallback.
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="send" onClick={sendMessage} disabled={busy}>
          {busy ? 'Sending…' : 'Send'}
        </button>
        {conversation.length > 0 && (
          <button className="clear" onClick={clearConversation} disabled={busy}>
            Clear
          </button>
        )}
      </div>

      {error && <div className="error">{error}</div>}

      <ConversationPanel
        conversation={conversation}
        expandedTools={expandedTools}
        setExpandedTools={setExpandedTools}
        itemLabels={itemLabels}
        resolvedQueries={resolvedQueries}
      />
    </>
  )
}
