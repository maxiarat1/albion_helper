# E2E Scenario Tests

A test suite for running end-to-end scenarios against Albion Helper with real LLM providers.

## Web UI

The easiest way to run and visualize scenarios:

```bash
cd tests/scenarios
python webui.py
```

Then open **http://localhost:8765** in your browser.

### Features
- Select provider (Ollama, Anthropic) and model
- Run predefined scenarios with one click
- View conversation turns with timing
- Inspect full system prompts

## CLI Tests

Run scenarios via pytest:

```bash
# All Ollama scenarios
pytest tests/scenarios/ -v -s -m "ollama"

# Quick tests only
pytest tests/scenarios/ -v -s -m "not slow"

# With Anthropic
ANTHROPIC_API_KEY=sk-... pytest tests/scenarios/ -m "anthropic"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `E2E_OLLAMA_MODEL` | `qwen2.5:7b-instruct-q5_K_M` | Ollama model |
| `E2E_ANTHROPIC_MODEL` | `claude-3-haiku-20240307` | Anthropic model |
| `ANTHROPIC_API_KEY` | - | Required for Anthropic tests |

## Scenarios

| Category | Tests |
|----------|-------|
| Market | Price queries, city comparison, trading tips |
| Multi-Turn | Follow-up questions, clarifications |
| General | Greetings, game knowledge, off-topic |
| Edge Cases | Typos, long input |
