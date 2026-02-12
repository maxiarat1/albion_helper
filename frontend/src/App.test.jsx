import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

vi.mock('vega-embed', () => ({
  default: vi.fn(async () => ({
    view: {
      finalize: () => {},
    },
  })),
}))

const jsonResponse = (data) => ({
  ok: true,
  json: async () => data,
  text: async () => (typeof data === 'string' ? data : JSON.stringify(data)),
})

const defaultResponseForUrl = (url) => {
  if (url.includes('/market/gold')) {
    return jsonResponse({ latest_price: null, latest_timestamp: null, count: 0, data: [] })
  }
  if (url.includes('/mcp/tools/list')) {
    return jsonResponse({ tools: [] })
  }
  if (url.includes('/db/status')) {
    return jsonResponse({
      database: {
        total_records: 0,
        imported_dumps_count: 0,
        date_range: {},
      },
      coverage: { months: [] },
      updates_available: { recommended: [] },
    })
  }
  if (url.includes('/ollama/models')) {
    return jsonResponse({ models: [] })
  }
  if (url.includes('/items/labels?')) {
    return jsonResponse({ count: 0, items: [] })
  }
  if (url.includes('/mcp/tools/call')) {
    return jsonResponse({
      isError: false,
      content: [{ type: 'text', text: '{}' }],
      structuredContent: { matches: [] },
    })
  }
  return jsonResponse({})
}

const setupDefaultFetch = () => {
  globalThis.fetch = vi.fn(async (input) => defaultResponseForUrl(String(input)))
}

describe('App', () => {
  beforeEach(() => {
    localStorage.clear()
    setupDefaultFetch()
  })

  it('renders the main heading', () => {
    render(<App />)
    expect(screen.getByText('Albion Helper')).toBeInTheDocument()
  })

  it('renders provider selector with default value', () => {
    render(<App />)
    const select = screen.getByLabelText(/provider/i)
    expect(select).toHaveValue('ollama')
  })

  it('renders model input with default value', () => {
    render(<App />)
    const input = screen.getByLabelText(/model/i)
    expect(input).toHaveValue('llama3')
  })

  it('disables send button when busy', async () => {
    const user = userEvent.setup()
    const never = new Promise(() => {})

    globalThis.fetch.mockImplementation(async (input) => {
      const url = String(input)
      if (!url.includes('/chat')) {
        return defaultResponseForUrl(url)
      }

      return {
        ok: true,
        text: async () => '',
        body: {
          getReader: () => ({
            read: vi.fn()
              .mockResolvedValueOnce({
                value: new TextEncoder().encode('data: {"type":"delta","text":"Hi"}\n\n'),
                done: false,
              })
              .mockReturnValue(never),
          }),
        },
      }
    })

    render(<App />)
    const textarea = screen.getByPlaceholderText(/ask a question/i)
    const button = screen.getByRole('button', { name: /^send$/i })

    await user.type(textarea, 'test message')
    await user.click(button)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sending/i })).toBeDisabled()
    })
  })

  it('updates provider when selection changes', async () => {
    const user = userEvent.setup()
    render(<App />)

    const select = screen.getByLabelText(/provider/i)
    await user.selectOptions(select, 'openai')

    expect(select).toHaveValue('openai')
  })

  it('updates model input when user types', async () => {
    const user = userEvent.setup()
    render(<App />)

    const providerSelect = screen.getByLabelText(/provider/i)
    await user.selectOptions(providerSelect, 'openai')

    const input = screen.getByLabelText(/model/i)
    await user.type(input, '{selectall}{backspace}gpt-4')

    expect(input).toHaveValue('gpt-4')
  })

  it('shows error message on failed request', async () => {
    const user = userEvent.setup()
    globalThis.fetch.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/chat')) {
        return {
          ok: false,
          text: async () => 'Server error',
        }
      }
      return defaultResponseForUrl(url)
    })

    render(<App />)
    const textarea = screen.getByPlaceholderText(/ask a question/i)
    const button = screen.getByRole('button', { name: /send/i })

    await user.type(textarea, 'test')
    await user.click(button)

    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument()
    })
  })

  it('renders assistant messages as markdown', async () => {
    localStorage.setItem(
      'llm_conversation',
      JSON.stringify([{ role: 'assistant', content: '**Profit Tip**\n\n- Buy low\n- Sell high\n\n`T4_BAG`' }])
    )

    render(<App />)

    const strongText = await screen.findByText('Profit Tip')
    expect(strongText.tagName).toBe('STRONG')
    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getByText('Buy low')).toBeInTheDocument()
    expect(screen.getByText('Sell high')).toBeInTheDocument()
    expect(screen.getByText('T4_BAG').tagName).toBe('CODE')
  })

  it('replaces item IDs in messages with highlighted labels', async () => {
    localStorage.setItem(
      'llm_conversation',
      JSON.stringify([{ role: 'assistant', content: 'Best pick is T4_BAG right now.' }])
    )

    globalThis.fetch.mockImplementation(async (input) => {
      const value = String(input)
      if (value.includes('/items/labels?')) {
        return {
          ok: true,
          json: async () => ({
            items: [
              {
                id: 'T4_BAG',
                found: true,
                display_name: "Adept's Bag",
                tier: 4,
                enchantment: 0,
                icon_url: 'https://render.albiononline.com/v1/item/T4_BAG.png',
              },
            ],
          }),
        }
      }
      return defaultResponseForUrl(value)
    })

    render(<App />)

    expect(await screen.findByText("Adept's Bag")).toBeInTheDocument()
    expect(screen.getByText('(T4)')).toBeInTheDocument()
    expect(screen.queryByText('T4_BAG')).not.toBeInTheDocument()
  })

  it('resolves tiered item names in assistant messages and labels them', async () => {
    localStorage.setItem(
      'llm_conversation',
      JSON.stringify([{ role: 'assistant', content: 'Best value is currently T4 Bag in Martlock.' }])
    )

    globalThis.fetch.mockImplementation(async (input, init) => {
      const value = String(input)

      if (value.includes('/mcp/tools/call')) {
        const payload = init?.body ? JSON.parse(init.body) : {}
        if (payload?.name === 'resolve_item' && payload?.arguments?.query === 'T4 Bag') {
          return {
            ok: true,
            json: async () => ({
              isError: false,
              content: [{ type: 'text', text: '{}' }],
              structuredContent: {
                matches: [{ unique_name: 'T4_BAG', display_name: "Adept's Bag" }],
              },
            }),
          }
        }
      }

      if (value.includes('/items/labels?')) {
        return {
          ok: true,
          json: async () => ({
            items: [
              {
                id: 'T4_BAG',
                found: true,
                display_name: "Adept's Bag",
                tier: 4,
                enchantment: 0,
                icon_url: 'https://render.albiononline.com/v1/item/T4_BAG.png',
              },
            ],
          }),
        }
      }

      return defaultResponseForUrl(value)
    })

    render(<App />)

    expect(await screen.findByText("Adept's Bag")).toBeInTheDocument()
    expect(screen.getByText('(T4)')).toBeInTheDocument()
    expect(screen.queryByText('T4 Bag')).not.toBeInTheDocument()
  })

  it('sends reasoning options when thinking mode is enabled', async () => {
    const user = userEvent.setup()
    const chatPayloads = []

    globalThis.fetch.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.includes('/chat')) {
        const payload = init?.body ? JSON.parse(init.body) : {}
        chatPayloads.push(payload)
        return {
          ok: true,
          text: async () => '',
          body: {
            getReader: () => ({
              read: vi.fn()
                .mockResolvedValueOnce({
                  value: new TextEncoder().encode('data: {"type":"done","text":"ok"}\n\n'),
                  done: false,
                })
                .mockResolvedValueOnce({ value: undefined, done: true }),
            }),
          },
        }
      }
      return defaultResponseForUrl(url)
    })

    render(<App />)

    await user.click(screen.getByRole('checkbox', { name: /thinking mode/i }))
    await user.type(screen.getByPlaceholderText(/ask a question/i), 'test thinking mode')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      expect(chatPayloads.length).toBeGreaterThan(0)
    })

    const firstCall = chatPayloads[0]
    expect(firstCall.options.reasoning.enabled).toBe(true)
    expect(firstCall.options.reasoning.provider_native).toBe(true)
    expect(firstCall.options.reasoning.reflect_after_tool).toBe(true)
    expect(firstCall.options.reasoning.effort).toBe('medium')
  })

  it('sends ollama_think when selected model exposes thinking levels', async () => {
    const user = userEvent.setup()
    const chatPayloads = []

    globalThis.fetch.mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.includes('/ollama/models')) {
        return jsonResponse({
          models: [
            {
              name: 'gpt-oss:20b',
              thinking: {
                supported: true,
                mode_type: 'levels',
                modes: ['low', 'medium', 'high'],
                source: 'show_capabilities',
              },
            },
          ],
        })
      }
      if (url.includes('/chat')) {
        const payload = init?.body ? JSON.parse(init.body) : {}
        chatPayloads.push(payload)
        return {
          ok: true,
          text: async () => '',
          body: {
            getReader: () => ({
              read: vi.fn()
                .mockResolvedValueOnce({
                  value: new TextEncoder().encode('data: {"type":"done","text":"ok"}\n\n'),
                  done: false,
                })
                .mockResolvedValueOnce({ value: undefined, done: true }),
            }),
          },
        }
      }
      return defaultResponseForUrl(url)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByLabelText(/model/i)).toHaveValue('gpt-oss:20b')
    })

    await user.click(screen.getByRole('checkbox', { name: /thinking mode/i }))
    await user.selectOptions(screen.getByLabelText(/ollama thinking level/i), 'high')
    await user.type(screen.getByPlaceholderText(/ask a question/i), 'test ollama thinking')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      expect(chatPayloads.length).toBeGreaterThan(0)
    })

    const firstCall = chatPayloads[0]
    expect(firstCall.options.reasoning.enabled).toBe(true)
    expect(firstCall.options.reasoning.ollama_think).toBe('high')
  })
})
