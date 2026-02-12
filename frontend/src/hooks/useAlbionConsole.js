import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  callMcpTool,
  clearDbUpdateProgress,
  fetchDbUpdateProgress,
  fetchDbStatus,
  fetchGoldPrices as fetchGoldPricesApi,
  fetchItemLabels,
  fetchMarketHistory,
  listMcpTools,
  listOllamaModels,
  postChat,
  resetDatabase,
  startDatabaseUpdate,
} from '../shared/api'
import { GOLD_RANGE_COUNTS } from '../shared/constants'
import {
  collectItemIds,
  collectItemQueries,
  extractEnchantmentFromItemId,
  extractTierFromItemId,
  getItemIconUrl,
  normalizeItemQuery,
} from '../shared/itemText'
import { normalizeOllamaModels } from '../shared/models'
import {
  loadApiKeys,
  loadConversation,
  loadModels,
  loadProvider,
  saveApiKeys,
  saveConversation,
  saveModels,
  saveProvider,
} from '../shared/storage'

export default function useAlbionConsole() {
  const [provider, setProviderState] = useState(() => loadProvider())
  const [models, setModels] = useState(() => loadModels())
  const [message, setMessage] = useState('')
  const [conversation, setConversation] = useState(() => loadConversation())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ollamaModels, setOllamaModels] = useState([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [apiKeys, setApiKeys] = useState(() => loadApiKeys())
  const [marketItem, setMarketItem] = useState('T4 Bag')
  const [marketQuality, setMarketQuality] = useState('1')
  const [marketStartDate, setMarketStartDate] = useState('')
  const [marketEndDate, setMarketEndDate] = useState('')
  const [marketCities, setMarketCities] = useState(new Set())
  const [marketIncludeLatestApi, setMarketIncludeLatestApi] = useState(false)
  const [marketResult, setMarketResult] = useState(null)
  const [marketBusy, setMarketBusy] = useState(false)
  const [marketError, setMarketError] = useState('')
  const [mcpEnabled, setMcpEnabled] = useState(true)
  const [thinkingEnabled, setThinkingEnabled] = useState(false)
  const [ollamaThinkMode, setOllamaThinkMode] = useState('')
  const [expandedTools, setExpandedTools] = useState(new Set())
  const [mcpTools, setMcpTools] = useState([])
  const [mcpAllowed, setMcpAllowed] = useState({})
  const [itemLabels, setItemLabels] = useState({})
  const [resolvedQueries, setResolvedQueries] = useState({})
  const [goldData, setGoldData] = useState(null)
  const [goldBusy, setGoldBusy] = useState(false)
  const [goldError, setGoldError] = useState('')
  const [goldRange, setGoldRange] = useState('week')
  const [dbStatus, setDbStatus] = useState(null)
  const [dbLoading, setDbLoading] = useState(false)
  const [dbUpdating, setDbUpdating] = useState(false)
  const [dbUpdateResult, setDbUpdateResult] = useState(null)
  const [dbUpdateProgress, setDbUpdateProgress] = useState(null)
  const [dbResetting, setDbResetting] = useState(false)
  const [dbResetResult, setDbResetResult] = useState(null)
  const pendingItemLabelFetches = useRef(new Set())
  const pendingQueryResolutions = useRef(new Set())
  const dbProgressPoller = useRef(null)

  const model = models[provider] || ''
  const selectedOllamaModel = provider === 'ollama'
    ? ollamaModels.find((entry) => entry.name === model) || null
    : null
  const ollamaThinking = selectedOllamaModel?.thinking || {}
  const ollamaThinkingModeType = ollamaThinking.mode_type || 'unknown'
  const ollamaThinkingModes = useMemo(
    () => (Array.isArray(ollamaThinking.modes) ? ollamaThinking.modes : []),
    [ollamaThinking.modes]
  )
  const ollamaThinkingSupported = ollamaThinking.supported

  const setProvider = (newProvider) => {
    setProviderState(newProvider)
    saveProvider(newProvider)
  }

  const handleApiKeyChange = (key) => {
    const updated = { ...apiKeys, [provider]: key }
    setApiKeys(updated)
    saveApiKeys(updated)
  }

  const handleModelChange = (newModel) => {
    const updated = { ...models, [provider]: newModel }
    setModels(updated)
    saveModels(updated)
  }

  const clearConversation = () => {
    setConversation([])
    saveConversation([])
    setError('')
  }

  const fetchMarketPrices = async () => {
    const item = marketItem.trim()

    if (!item) {
      setMarketError('Item is required')
      return
    }

    const params = new URLSearchParams({
      item,
      granularity: 'daily',
    })

    if (marketQuality) {
      params.set('quality', marketQuality)
    }

    if (marketStartDate) {
      params.set('start_date', marketStartDate)
    }

    if (marketEndDate) {
      params.set('end_date', marketEndDate)
    }

    if (marketCities.size > 0) {
      params.set('cities', Array.from(marketCities).join(','))
    }

    if (marketIncludeLatestApi) {
      params.set('include_latest_api', 'true')
    }

    setMarketBusy(true)
    setMarketError('')

    try {
      const data = await fetchMarketHistory(params)
      setMarketResult(data)
    } catch (err) {
      setMarketError(err?.message || 'Failed to fetch historical data')
      setMarketResult(null)
    } finally {
      setMarketBusy(false)
    }
  }

  const fetchGoldPrices = useCallback(async (range) => {
    const r = range || goldRange
    const count = GOLD_RANGE_COUNTS[r] || GOLD_RANGE_COUNTS.week

    setGoldBusy(true)
    setGoldError('')
    try {
      const data = await fetchGoldPricesApi(count)
      setGoldData(data)
    } catch (err) {
      setGoldError(err?.message || 'Failed to fetch gold prices')
      setGoldData(null)
    } finally {
      setGoldBusy(false)
    }
  }, [goldRange])

  useEffect(() => {
    fetchGoldPrices(goldRange)
  }, [goldRange, fetchGoldPrices])

  useEffect(() => {
    if (provider !== 'ollama') return

    const fetchModels = async () => {
      setLoadingModels(true)
      try {
        const data = await listOllamaModels()
        const normalized = normalizeOllamaModels(data.models || [])
        setOllamaModels(normalized)
        if (normalized.length > 0) {
          const hasSelected = normalized.some((entry) => entry.name === model)
          if (!hasSelected) {
            const nextModel = normalized[0].name
            setModels((prev) => {
              const updated = { ...prev, ollama: nextModel }
              saveModels(updated)
              return updated
            })
          }
        }
      } catch (err) {
        console.error('Failed to fetch Ollama models:', err)
      } finally {
        setLoadingModels(false)
      }
    }

    fetchModels()
  }, [provider, model])

  useEffect(() => {
    if (provider !== 'ollama') {
      if (ollamaThinkMode !== '') {
        setOllamaThinkMode('')
      }
      return
    }

    if (ollamaThinkingModeType !== 'levels') {
      if (ollamaThinkMode !== '') {
        setOllamaThinkMode('')
      }
      return
    }

    const options = ollamaThinkingModes.length > 0 ? ollamaThinkingModes : ['medium']
    if (!options.includes(ollamaThinkMode)) {
      setOllamaThinkMode(options.includes('medium') ? 'medium' : options[0])
    }
  }, [provider, ollamaThinkingModeType, ollamaThinkingModes, ollamaThinkMode])

  useEffect(() => {
    const fetchTools = async () => {
      try {
        const data = await listMcpTools()
        const tools = data.tools || []
        setMcpTools(tools)
        const initialAllowed = {}
        tools.forEach((tool) => {
          initialAllowed[tool.name] = true
        })
        setMcpAllowed(initialAllowed)
      } catch (err) {
        console.error('Failed to fetch MCP tools:', err)
      }
    }

    fetchTools()
  }, [])

  useEffect(() => {
    const refreshDbStatus = async () => {
      setDbLoading(true)
      try {
        const data = await fetchDbStatus()
        setDbStatus(data)
      } catch (err) {
        console.error('Failed to fetch database status:', err)
      } finally {
        setDbLoading(false)
      }
    }

    refreshDbStatus()
  }, [])

  useEffect(() => {
    const queries = new Set()
    collectItemQueries(conversation, queries)
    collectItemQueries(marketResult, queries)
    const unresolvedQueries = Array.from(queries).filter((query) => {
      const key = normalizeItemQuery(query)
      return !resolvedQueries[key] && !pendingQueryResolutions.current.has(key)
    })

    if (unresolvedQueries.length === 0) {
      return
    }

    unresolvedQueries.forEach((query) => pendingQueryResolutions.current.add(normalizeItemQuery(query)))

    const resolveQueries = async () => {
      try {
        const resolutions = await Promise.all(
          unresolvedQueries.map(async (query) => {
            try {
              const data = await callMcpTool('resolve_item', { query, limit: 1 })
              if (data?.isError) {
                return null
              }
              const match = data?.structuredContent?.matches?.[0]
              if (!match?.unique_name) {
                return null
              }
              return {
                queryKey: normalizeItemQuery(query),
                itemId: match.unique_name,
              }
            } catch {
              return null
            }
          })
        )

        const resolved = resolutions.filter(Boolean)
        if (resolved.length > 0) {
          setResolvedQueries((prev) => {
            const next = { ...prev }
            resolved.forEach((entry) => {
              next[entry.queryKey] = entry.itemId
            })
            return next
          })
        }
      } finally {
        unresolvedQueries.forEach((query) => pendingQueryResolutions.current.delete(normalizeItemQuery(query)))
      }
    }

    resolveQueries()
  }, [conversation, marketResult, resolvedQueries])

  useEffect(() => {
    const ids = new Set()
    collectItemIds(conversation, ids)
    collectItemIds(marketResult, ids)
    Object.values(resolvedQueries).forEach((itemId) => ids.add(itemId))
    const unresolved = Array.from(ids).filter(
      (itemId) => !itemLabels[itemId] && !pendingItemLabelFetches.current.has(itemId)
    )

    if (unresolved.length === 0) {
      return
    }

    unresolved.forEach((itemId) => pendingItemLabelFetches.current.add(itemId))

    const loadLabels = async () => {
      const chunkSize = 100
      const fetchedLabels = []

      try {
        for (let i = 0; i < unresolved.length; i += chunkSize) {
          const chunk = unresolved.slice(i, i + chunkSize)
          try {
            const data = await fetchItemLabels(chunk)
            if (Array.isArray(data.items)) {
              fetchedLabels.push(...data.items)
            }
          } catch {
            continue
          }
        }

        setItemLabels((prev) => {
          const next = { ...prev }
          unresolved.forEach((itemId) => {
            next[itemId] = {
              id: itemId,
              found: false,
              display_name: itemId,
              tier: extractTierFromItemId(itemId),
              enchantment: extractEnchantmentFromItemId(itemId),
              icon_url: getItemIconUrl(itemId),
            }
          })
          fetchedLabels.forEach((entry) => {
            if (entry?.id) {
              next[entry.id] = entry
            }
          })
          return next
        })
      } catch (err) {
        console.error('Failed to fetch item labels:', err)
      } finally {
        unresolved.forEach((itemId) => pendingItemLabelFetches.current.delete(itemId))
      }
    }

    loadLabels()
  }, [conversation, marketResult, itemLabels, resolvedQueries])

  const refreshDbStatus = useCallback(async () => {
    try {
      const statusData = await fetchDbStatus()
      setDbStatus(statusData)
    } catch {
      // no-op: UI retains previous status
    }
  }, [])

  const stopDbUpdatePolling = useCallback(() => {
    if (!dbProgressPoller.current) {
      return
    }
    clearInterval(dbProgressPoller.current)
    dbProgressPoller.current = null
  }, [])

  const finishDbUpdateFlow = useCallback(async () => {
    stopDbUpdatePolling()
    try {
      await clearDbUpdateProgress()
    } catch {
      // no-op: local cleanup still prevents stale UI in current session
    }
    setDbUpdating(false)
    setDbUpdateProgress(null)
    setDbUpdateResult(null)
  }, [stopDbUpdatePolling])

  const applyDbUpdateProgress = useCallback(async (progress) => {
    setDbUpdateProgress(progress)

    if (!progress || progress.status === 'idle') {
      setDbUpdating(false)
      stopDbUpdatePolling()
      return
    }

    if (progress.status === 'running') {
      setDbUpdating(true)
      return
    }

    setDbUpdating(false)
    stopDbUpdatePolling()

    if (progress.status === 'completed') {
      if (progress.result) {
        setDbUpdateResult(progress.result)
      }
      await refreshDbStatus()
      return
    }

    if (progress.status === 'failed') {
      const progressErrors = Array.isArray(progress.errors) && progress.errors.length > 0
        ? progress.errors
        : [progress.message || 'Import failed']
      setDbUpdateResult({ success: false, errors: progressErrors })
      await refreshDbStatus()
    }
  }, [refreshDbStatus, stopDbUpdatePolling])

  const pollDbUpdateProgress = useCallback(async () => {
    try {
      const progress = await fetchDbUpdateProgress()
      await applyDbUpdateProgress(progress)
    } catch {
      // no-op: keep existing progress state
    }
  }, [applyDbUpdateProgress])

  const startDbUpdatePolling = useCallback(() => {
    if (dbProgressPoller.current) {
      return
    }
    dbProgressPoller.current = setInterval(() => {
      pollDbUpdateProgress()
    }, 1000)
  }, [pollDbUpdateProgress])

  useEffect(() => {
    return () => {
      stopDbUpdatePolling()
    }
  }, [stopDbUpdatePolling])

  useEffect(() => {
    const initializeDbUpdateProgress = async () => {
      try {
        const progress = await fetchDbUpdateProgress()
        setDbUpdateProgress(progress)
        if (progress?.status === 'running') {
          setDbUpdating(true)
          startDbUpdatePolling()
        }
      } catch {
        // no-op: progress endpoint may be unavailable
      }
    }

    initializeDbUpdateProgress()
  }, [startDbUpdatePolling])

  const triggerDbUpdate = async () => {
    setDbUpdateResult(null)
    try {
      const result = await startDatabaseUpdate(1)
      if (result?.progress) {
        setDbUpdateProgress(result.progress)
      }

      if (result?.started || result?.progress?.status === 'running') {
        setDbUpdating(true)
        startDbUpdatePolling()
        await pollDbUpdateProgress()
        return
      }

      if (result?.progress) {
        await applyDbUpdateProgress(result.progress)
        return
      }

      setDbUpdating(false)
      setDbUpdateResult({ success: false, errors: ['Unable to start database update'] })
    } catch (err) {
      setDbUpdating(false)
      setDbUpdateResult({ success: false, errors: [err.message] })
    }
  }

  const hardResetDatabase = async () => {
    const confirmed = window.confirm(
      'This will permanently delete local market history and imported dump metadata. Continue?'
    )
    if (!confirmed) return

    setDbResetting(true)
    setDbResetResult(null)
    try {
      const result = await resetDatabase(true)
      setDbResetResult(result)
      await refreshDbStatus()
    } catch (err) {
      setDbResetResult({ success: false, error: err.message })
    } finally {
      setDbResetting(false)
    }
  }

  const formatNumber = (num) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
    return num?.toString() || '0'
  }

  const fetchNonStream = async (payload, updatedConversation) => {
    let response
    try {
      response = await postChat({ ...payload, stream: false }, false)
    } catch (err) {
      setError(err?.message || 'failed to fetch')
      return
    }

    if (!response.ok) {
      try {
        const text = await response.text()
        setError(text || 'request failed')
      } catch {
        setError('request failed')
      }
      return
    }

    const data = await response.json()
    const assistantMessage = data?.text || JSON.stringify(data)
    const toolMeta = data?._meta || null
    const finalConv = [...updatedConversation, {
      role: 'assistant',
      content: assistantMessage,
      model: payload.model,
      provider: payload.provider,
      _meta: toolMeta,
    }]
    setConversation(finalConv)
    saveConversation(finalConv)
  }

  const sendMessage = async () => {
    const trimmed = message.trim()
    if (!trimmed || busy) return

    if (!model.trim()) {
      setError('Model name is required')
      return
    }

    const userMessage = { role: 'user', content: trimmed }
    const updatedConversation = [...conversation, userMessage]

    setConversation(updatedConversation)
    saveConversation(updatedConversation)
    setMessage('')
    setBusy(true)
    setError('')

    const payload = {
      provider,
      model: model || null,
      stream: true,
      messages: updatedConversation,
    }

    if (mcpEnabled) {
      const allowedTools = Object.entries(mcpAllowed)
        .filter(([, enabled]) => enabled)
        .map(([name]) => name)

      const mcpOptions = {
        enabled: true,
      }

      if (allowedTools.length > 0) {
        mcpOptions.allowed_tools = allowedTools
      }

      payload.options = { ...(payload.options || {}), mcp: mcpOptions }
    }

    if (thinkingEnabled) {
      const reasoningOptions = {
        enabled: true,
        provider_native: true,
        reflect_after_tool: true,
        effort: 'medium',
      }

      if (provider === 'ollama' && ollamaThinkingModeType === 'levels' && ollamaThinkMode) {
        reasoningOptions.ollama_think = ollamaThinkMode
      }

      payload.options = {
        ...(payload.options || {}),
        reasoning: reasoningOptions,
      }
    }

    if (provider !== 'ollama' && apiKeys[provider]) {
      payload.api_key = apiKeys[provider]
    }

    let response
    try {
      response = await postChat(payload, true)
    } catch (err) {
      setError(err?.message || 'failed to fetch')
      setBusy(false)
      return
    }

    if (!response.ok) {
      try {
        const text = await response.text()
        setError(text || 'request failed')
      } catch {
        setError('request failed')
      }
      setBusy(false)
      return
    }

    if (!response.body || !response.body.getReader) {
      await fetchNonStream(payload, updatedConversation)
      setBusy(false)
      return
    }

    let reader
    try {
      reader = response.body.getReader()
    } catch {
      await fetchNonStream(payload, updatedConversation)
      setBusy(false)
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''
    let assistantMessage = ''

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() || ''

        for (const chunk of chunks) {
          const line = chunk.trim()
          if (!line.startsWith('data:')) continue
          const jsonText = line.slice(5).trim()
          if (!jsonText) continue
          const evt = JSON.parse(jsonText)
          if (evt.type === 'delta') {
            assistantMessage += evt.text || ''
            const newConv = [...updatedConversation, { role: 'assistant', content: assistantMessage, model, provider }]
            setConversation(newConv)
          } else if (evt.type === 'done') {
            const toolMeta = evt._meta || null
            const finalConv = [...updatedConversation, { role: 'assistant', content: assistantMessage, model, provider, _meta: toolMeta }]
            setConversation(finalConv)
            saveConversation(finalConv)
            setBusy(false)
          } else if (evt.type === 'error') {
            setError(evt.message || 'error')
            setBusy(false)
          }
        }
      }
    } catch {
      await fetchNonStream(payload, updatedConversation)
    } finally {
      setBusy(false)
    }
  }

  return {
    provider,
    setProvider,
    model,
    handleModelChange,
    message,
    setMessage,
    conversation,
    busy,
    error,
    ollamaModels,
    loadingModels,
    apiKeys,
    handleApiKeyChange,
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
    marketResult,
    marketBusy,
    marketError,
    mcpEnabled,
    setMcpEnabled,
    thinkingEnabled,
    setThinkingEnabled,
    ollamaThinkMode,
    setOllamaThinkMode,
    expandedTools,
    setExpandedTools,
    mcpTools,
    mcpAllowed,
    setMcpAllowed,
    itemLabels,
    resolvedQueries,
    goldData,
    goldBusy,
    goldError,
    goldRange,
    setGoldRange,
    dbStatus,
    dbLoading,
    dbUpdating,
    dbUpdateResult,
    dbUpdateProgress,
    dbResetting,
    dbResetResult,
    ollamaThinkingModeType,
    ollamaThinkingModes,
    ollamaThinkingSupported,
    fetchMarketPrices,
    fetchGoldPrices,
    triggerDbUpdate,
    finishDbUpdateFlow,
    hardResetDatabase,
    formatNumber,
    sendMessage,
    clearConversation,
  }
}
