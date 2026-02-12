# Development Guide

This guide is for contributors who run Albion Helper from source.

## Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Node.js 20+

## Dev Run (Docker, Recommended)

```bash
cp .env.example .env
docker compose up --build
```

Endpoints:
- Frontend: http://localhost:5173
- Backend docs: http://localhost:8000/docs

Notes:
- Backend runs with `--reload` in dev compose.
- Optional packet capture service is behind the `capture` profile:

```bash
docker compose --profile capture up --build
```

## Dev Run (Without Docker)

### Backend

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
set -a && source .env && set +a
uvicorn app.web.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Tests

```bash
pytest
cd frontend && npm test
```

## Image Publishing

Workflow:
- `.github/workflows/publish-images.yml`

Triggers:
- Push to `master`
- Git tags matching `v*`
- Manual dispatch (`workflow_dispatch`)

Manual trigger:

```bash
export GITHUB_TOKEN=YOUR_TOKEN_WITH_ACTIONS_WRITE
scripts/trigger-image-build.sh --wait
```

Useful options:
- `--repo OWNER/REPO`
- `--ref master`
- `--workflow publish-images.yml`
- `--wait`
- `--timeout 1800`

## Runtime Installer

Normal users should use the runtime installer (no repo checkout required):

```bash
curl -fsSL https://raw.githubusercontent.com/maxiarat1/albion_helper/master/scripts/install-runtime.sh | bash
```
