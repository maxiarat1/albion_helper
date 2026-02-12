import {
  ITEM_ID_PATTERN,
  ITEM_TIER_PATTERN,
  TIERED_ITEM_QUERY_PATTERN,
} from './constants'

export const getItemIconUrl = (itemId) =>
  `https://render.albiononline.com/v1/item/${encodeURIComponent(itemId)}.png`

export const extractItemIdsFromText = (text) => {
  if (!text || typeof text !== 'string') {
    return []
  }

  const matches = text.match(ITEM_ID_PATTERN)
  return matches ? Array.from(new Set(matches)) : []
}

export const extractTieredItemQueriesFromText = (text) => {
  if (!text || typeof text !== 'string') {
    return []
  }

  const matches = text.match(TIERED_ITEM_QUERY_PATTERN)
  return matches ? Array.from(new Set(matches.map((query) => query.trim()))) : []
}

export const normalizeItemQuery = (query) => query.trim().replace(/\s+/g, ' ').toLowerCase()

export const extractTierFromItemId = (itemId) => {
  if (!itemId || typeof itemId !== 'string') {
    return null
  }
  const match = itemId.match(ITEM_TIER_PATTERN)
  if (!match) {
    return null
  }
  const tier = Number(match[1])
  return Number.isFinite(tier) ? tier : null
}

export const extractEnchantmentFromItemId = (itemId) => {
  if (!itemId || typeof itemId !== 'string' || !itemId.includes('@')) {
    return 0
  }
  const parts = itemId.split('@')
  const enchantment = Number(parts[parts.length - 1])
  return Number.isFinite(enchantment) ? enchantment : 0
}

export const formatTierLabel = (tier, enchantment) => {
  if (!tier) {
    return ''
  }
  return `T${tier}${enchantment > 0 ? `.${enchantment}` : ''}`
}

export const collectItemIds = (value, targetSet) => {
  if (value == null) {
    return
  }

  if (typeof value === 'string') {
    extractItemIdsFromText(value).forEach((itemId) => targetSet.add(itemId))
    return
  }

  if (Array.isArray(value)) {
    value.forEach((entry) => collectItemIds(entry, targetSet))
    return
  }

  if (typeof value === 'object') {
    Object.values(value).forEach((entry) => collectItemIds(entry, targetSet))
  }
}

export const collectItemQueries = (value, targetSet) => {
  if (value == null) {
    return
  }

  if (typeof value === 'string') {
    extractTieredItemQueriesFromText(value).forEach((query) => targetSet.add(query))
    return
  }

  if (Array.isArray(value)) {
    value.forEach((entry) => collectItemQueries(entry, targetSet))
    return
  }

  if (typeof value === 'object') {
    Object.values(value).forEach((entry) => collectItemQueries(entry, targetSet))
  }
}
