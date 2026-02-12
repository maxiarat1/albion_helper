# Albion Helper

Self-hosted Albion Online market assistant with chat, live prices, and historical charts.

## Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Node.js 20+
- Optional: [Ollama](https://ollama.com/) for local LLM usage

## Runtime Quick Start (Prebuilt Docker Images)

1. Create local env file:

```bash
cp .env.example .env
```

2. Set published image tags in `.env`:

```bash
ALBION_HELPER_BACKEND_IMAGE=ghcr.io/your-org/albion-helper-backend:latest
ALBION_HELPER_FRONTEND_IMAGE=ghcr.io/your-org/albion-helper-frontend:latest
ALBIONDATA_CLIENT_IMAGE=ghcr.io/your-org/albion-helper-albiondata-client:latest
```

3. Pick an LLM setup:
- Local model (default): install Ollama, then run `ollama pull llama3`
- Cloud model: set one of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY` in `.env`

4. Start the app from images only:

```bash
docker compose -f docker-compose.runtime.yml up -d
```

5. Open:
- UI: http://localhost:5173
- API docs: http://localhost:8000/docs

### Optional: Enable Langfuse Tracing

Add these vars to `.env` (or keep defaults in `.env.example`):

```bash
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=local
LANGFUSE_RELEASE=
```

Use `LANGFUSE_ENABLED=true|false` to force behavior. Leave it empty for auto mode (enabled only when keys exist).

## Development Setup (Source Code)

Use this only if you want to work on the codebase locally.

### Docker-based development

```bash
cp .env.example .env
docker compose up --build
```

### Local run without Docker

### 1) Backend

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
set -a && source .env && set +a
uvicorn app.web.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2) Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open http://localhost:5173.

## First Use

- In the UI, select provider + model.
- `ollama` + `llama3` for local models
- `openai` / `anthropic` / `gemini` for cloud models (enter API key in the UI if needed)
- Optional: populate local historical data from the UI Data Manager (`Update DB` button)

## Useful Commands

```bash
# stop containers
docker compose down

# stop runtime stack (image-only)
docker compose -f docker-compose.runtime.yml down

# backend tests
pytest

# frontend tests
cd frontend && npm test
```
