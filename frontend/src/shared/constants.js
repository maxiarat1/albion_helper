export const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export const STORAGE_KEYS = {
  apiKeys: 'llm_api_keys',
  conversation: 'llm_conversation',
  provider: 'llm_provider',
  models: 'llm_models',
}

export const ITEM_ID_PATTERN = /\bT[1-8](?:_[A-Z0-9]+)+(?:@\d+)?\b/g
export const TIERED_ITEM_QUERY_PATTERN = /\bT[1-8](?:\.[0-4])?\s+[A-Z][A-Za-z']*(?:\s+[A-Z][A-Za-z']*){0,2}\b/g
export const ITEM_TIER_PATTERN = /^T([1-8])/

export const MARKDOWN_TEXT_TAGS = [
  'p',
  'li',
  'blockquote',
  'strong',
  'em',
  'del',
  'a',
  'td',
  'th',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
]

export const DEFAULT_MARKET_CITIES = [
  'Caerleon',
  'Thetford',
  'Bridgewatch',
  'Martlock',
  'Fort Sterling',
  'Lymhurst',
  'Black Market',
  'Brecilien',
]

export const GOLD_RANGE_COUNTS = {
  day: 24,
  week: 168,
  month: 720,
}
