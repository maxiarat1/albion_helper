export const normalizeOllamaModels = (models) => {
  if (!Array.isArray(models)) {
    return []
  }

  return models
    .map((entry) => {
      if (typeof entry === 'string') {
        const name = entry.trim()
        if (!name) return null
        return {
          name,
          thinking: {
            supported: null,
            mode_type: 'unknown',
            modes: [],
            source: 'unknown',
          },
        }
      }

      if (!entry || typeof entry !== 'object') {
        return null
      }

      const name = String(entry.name || '').trim()
      if (!name) {
        return null
      }

      const rawThinking = entry.thinking && typeof entry.thinking === 'object' ? entry.thinking : {}
      const modeType = typeof rawThinking.mode_type === 'string' ? rawThinking.mode_type : 'unknown'
      const modes = Array.isArray(rawThinking.modes)
        ? rawThinking.modes
          .filter((mode) => typeof mode === 'string' && mode.trim())
          .map((mode) => mode.trim().toLowerCase())
        : []

      return {
        ...entry,
        name,
        thinking: {
          supported: typeof rawThinking.supported === 'boolean' ? rawThinking.supported : null,
          mode_type: modeType,
          modes,
          source: typeof rawThinking.source === 'string' ? rawThinking.source : 'unknown',
        },
      }
    })
    .filter(Boolean)
}
