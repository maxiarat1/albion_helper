import { Children, cloneElement, isValidElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import {
  MARKDOWN_TEXT_TAGS,
  ITEM_ID_PATTERN,
  TIERED_ITEM_QUERY_PATTERN,
} from '../../shared/constants'
import {
  extractEnchantmentFromItemId,
  extractTierFromItemId,
  formatTierLabel,
  getItemIconUrl,
  normalizeItemQuery,
} from '../../shared/itemText'

function ItemReference({ itemId, itemLabels, fallbackName = '' }) {
  if (!itemId) {
    return fallbackName || 'Unknown item'
  }

  const info = itemLabels[itemId]
  const displayName = info?.found === false
    ? fallbackName || itemId
    : info?.display_name || fallbackName || itemId
  const tier = info?.tier ?? extractTierFromItemId(itemId)
  const enchantment = info?.enchantment ?? extractEnchantmentFromItemId(itemId)
  const tierLabel = formatTierLabel(tier, enchantment)

  return (
    <span className={`item-ref${info?.found === false ? ' unresolved' : ''}`} title={itemId}>
      <img
        src={info?.icon_url || getItemIconUrl(itemId)}
        alt=""
        className="item-ref-icon"
        loading="lazy"
        onError={(e) => {
          e.currentTarget.style.display = 'none'
        }}
      />
      <span className="item-ref-name">{displayName}</span>
      {tierLabel && <span className="item-ref-tier">({tierLabel})</span>}
    </span>
  )
}

const renderHighlightedItemText = (text, itemLabels, resolvedQueries = {}) => {
  if (text == null) {
    return null
  }

  const value = String(text)
  if (!value) {
    return ''
  }

  const idMatches = [...value.matchAll(new RegExp(ITEM_ID_PATTERN.source, 'g'))].map((match) => ({
    start: match.index ?? 0,
    end: (match.index ?? 0) + match[0].length,
    source: match[0],
    itemId: match[0],
  }))
  const queryMatches = [...value.matchAll(new RegExp(TIERED_ITEM_QUERY_PATTERN.source, 'g'))]
    .map((match) => {
      const source = match[0]
      const normalized = normalizeItemQuery(source)
      const itemId = resolvedQueries[normalized]
      if (!itemId) {
        return null
      }
      const start = match.index ?? 0
      return {
        start,
        end: start + source.length,
        source,
        itemId,
      }
    })
    .filter(Boolean)
  const combinedMatches = [...idMatches, ...queryMatches]
    .sort((a, b) => {
      if (a.start !== b.start) {
        return a.start - b.start
      }
      return (b.end - b.start) - (a.end - a.start)
    })

  const nonOverlappingMatches = []
  let lastEnd = -1
  combinedMatches.forEach((match) => {
    if (match.start < lastEnd) {
      return
    }
    nonOverlappingMatches.push(match)
    lastEnd = match.end
  })

  if (nonOverlappingMatches.length === 0) {
    return value
  }

  const nodes = []
  let cursor = 0

  nonOverlappingMatches.forEach((match, index) => {
    const { itemId, start, end, source } = match

    if (start > cursor) {
      nodes.push(value.slice(cursor, start))
    }

    nodes.push(
      <ItemReference
        key={`${itemId}-${start}-${index}-${source}`}
        itemId={itemId}
        itemLabels={itemLabels}
        fallbackName={source}
      />
    )
    cursor = end
  })

  if (cursor < value.length) {
    nodes.push(value.slice(cursor))
  }

  return nodes
}

export function HighlightedItemText({ text, itemLabels, resolvedQueries = {} }) {
  return renderHighlightedItemText(text, itemLabels, resolvedQueries)
}

const renderMarkdownChildren = (children, itemLabels, resolvedQueries = {}) =>
  Children.map(children, (child) => {
    if (typeof child === 'string') {
      return renderHighlightedItemText(child, itemLabels, resolvedQueries)
    }

    if (!isValidElement(child)) {
      return child
    }

    const elementType = typeof child.type === 'string' ? child.type : ''
    if (elementType === 'pre' || elementType === 'code') {
      return child
    }

    if (child.props?.children == null) {
      return child
    }

    return cloneElement(
      child,
      undefined,
      renderMarkdownChildren(child.props.children, itemLabels, resolvedQueries)
    )
  })

export function MarkdownMessageContent({ text, itemLabels, resolvedQueries = {} }) {
  if (text == null) {
    return null
  }

  const value = String(text)
  if (!value) {
    return ''
  }

  const markdownComponents = {}
  MARKDOWN_TEXT_TAGS.forEach((tag) => {
    markdownComponents[tag] = (props) => {
      const { node, children, ...elementProps } = props
      void node
      const Tag = tag
      return (
        <Tag {...elementProps}>
          {renderMarkdownChildren(children, itemLabels, resolvedQueries)}
        </Tag>
      )
    }
  })

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {value}
    </ReactMarkdown>
  )
}

export { ItemReference }
