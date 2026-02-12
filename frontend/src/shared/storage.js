import { STORAGE_KEYS } from './constants'

const loadJSON = (key, fallback) => {
  try {
    const stored = localStorage.getItem(key)
    return stored ? JSON.parse(stored) : fallback
  } catch {
    return fallback
  }
}

const saveJSON = (key, value, label) => {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch (err) {
    console.error(`Failed to save ${label}:`, err)
  }
}

export const loadApiKeys = () => loadJSON(STORAGE_KEYS.apiKeys, {})

export const saveApiKeys = (keys) => {
  saveJSON(STORAGE_KEYS.apiKeys, keys, 'API keys')
}

export const loadConversation = () => loadJSON(STORAGE_KEYS.conversation, [])

export const saveConversation = (messages) => {
  saveJSON(STORAGE_KEYS.conversation, messages, 'conversation')
}

export const loadProvider = () => {
  try {
    return localStorage.getItem(STORAGE_KEYS.provider) || 'ollama'
  } catch {
    return 'ollama'
  }
}

export const saveProvider = (provider) => {
  try {
    localStorage.setItem(STORAGE_KEYS.provider, provider)
  } catch (err) {
    console.error('Failed to save provider:', err)
  }
}

export const loadModels = () => loadJSON(STORAGE_KEYS.models, { ollama: 'llama3' })

export const saveModels = (models) => {
  saveJSON(STORAGE_KEYS.models, models, 'models')
}
