# Albion Helper

Self-hosted Albion Online assistant with chat, live market data, and historical price tools.

## One-Command Install (No Repo Needed)

Requirements:
- Docker with `docker compose`
- Ollama only if you want local Ollama models (optional)

Run:

```bash
curl -fsSL https://raw.githubusercontent.com/maxiarat1/albion_helper/master/scripts/install-runtime.sh | bash
```

Then open:
- UI: http://localhost:5173
- API docs: http://localhost:8000/docs

This installs runtime files into `~/.albion-helper` and starts prebuilt images from GHCR.

## Runtime Management

```bash
# logs
docker compose --env-file ~/.albion-helper/.env -f ~/.albion-helper/docker-compose.yml logs -f

# stop
docker compose --env-file ~/.albion-helper/.env -f ~/.albion-helper/docker-compose.yml down

# start again
docker compose --env-file ~/.albion-helper/.env -f ~/.albion-helper/docker-compose.yml up -d

# update to latest images
curl -fsSL https://raw.githubusercontent.com/maxiarat1/albion_helper/master/scripts/install-runtime.sh | bash

# delete everything (containers, volumes, ~/.albion-helper)
curl -fsSL https://raw.githubusercontent.com/maxiarat1/albion_helper/master/scripts/uninstall-runtime.sh | bash
```

Optional packet capture service:

```bash
docker compose --env-file ~/.albion-helper/.env -f ~/.albion-helper/docker-compose.yml --profile capture up -d
```

Runtime config file: `~/.albion-helper/.env`
Template: `.env.runtime.example`

## Developer Setup (From Source)

For contributors and debugging from this repository:

```bash
cp .env.example .env
docker compose up --build
```

Developer guide: `DEVELOPMENT.md`

## Runtime Images

- `ghcr.io/maxiarat1/albion-helper-backend`
- `ghcr.io/maxiarat1/albion-helper-frontend`
- `ghcr.io/maxiarat1/albion-helper-albiondata-client`
