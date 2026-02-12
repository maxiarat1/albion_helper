import { API_BASE } from './constants'

const jsonHeaders = { 'Content-Type': 'application/json' }

const readErrorText = async (response, fallback) => {
  try {
    const text = await response.text()
    return text || fallback
  } catch {
    return fallback
  }
}

export const fetchJson = async (url, options = {}) => {
  const response = await fetch(url, options)
  if (!response.ok) {
    throw new Error(await readErrorText(response, 'Request failed'))
  }
  return response.json()
}

export const listMcpTools = async () => {
  return fetchJson(`${API_BASE}/mcp/tools/list`, { method: 'POST' })
}

export const listOllamaModels = async () => {
  return fetchJson(`${API_BASE}/ollama/models`)
}

export const fetchGoldPrices = async (count) => {
  return fetchJson(`${API_BASE}/market/gold?count=${count}`)
}

export const fetchMarketHistory = async (params) => {
  return fetchJson(`${API_BASE}/db/history?${params.toString()}`)
}

export const fetchDbStatus = async () => {
  return fetchJson(`${API_BASE}/db/status?check_updates=true`)
}

export const updateDatabase = async (maxDumps = 1) => {
  return fetchJson(`${API_BASE}/db/update`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ max_dumps: maxDumps }),
  })
}

export const startDatabaseUpdate = async (maxDumps = 1) => {
  return fetchJson(`${API_BASE}/db/update/start`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ max_dumps: maxDumps }),
  })
}

export const fetchDbUpdateProgress = async () => {
  return fetchJson(`${API_BASE}/db/update/progress`)
}

export const clearDbUpdateProgress = async () => {
  return fetchJson(`${API_BASE}/db/update/progress/clear`, { method: 'POST' })
}

export const resetDatabase = async (cleanupDumps = true) => {
  return fetchJson(`${API_BASE}/db/reset`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ cleanup_dumps: cleanupDumps }),
  })
}

export const callMcpTool = async (name, argumentsPayload) => {
  return fetchJson(`${API_BASE}/mcp/tools/call`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ name, arguments: argumentsPayload }),
  })
}

export const fetchItemLabels = async (ids) => {
  const params = new URLSearchParams({ ids: ids.join(',') })
  return fetchJson(`${API_BASE}/items/labels?${params.toString()}`)
}

export const postChat = async (payload, streaming = true) => {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: {
      ...jsonHeaders,
      ...(streaming ? { Accept: 'text/event-stream' } : {}),
    },
    body: JSON.stringify(payload),
  })
  return response
}
