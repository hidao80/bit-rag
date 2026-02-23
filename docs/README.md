# bit-rag

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)&emsp;
![Lint](https://github.com/hidao80/bit-rag/actions/workflows/lint.yml/badge.svg)&emsp;
![Format](https://github.com/hidao80/bit-rag/actions/workflows/format.yml/badge.svg)&emsp;
![Test](https://github.com/hidao80/bit-rag/actions/workflows/test.yml/badge.svg)&emsp;
![Audit](https://github.com/hidao80/bit-rag/actions/workflows/audit.yml/badge.svg)&emsp;
![Docker](https://github.com/hidao80/bit-rag/actions/workflows/docker.yml/badge.svg)&emsp;
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/hidao80/bit-rag)

# Overview

Build the simplest local RAG API server.

# Issues & Reasons

When spinning up a full database server or web server just to use RAG is overkill, this repository provides a simpler alternative.
By exposing it as a Web API server, it can be integrated with web applications and webhooks in existing systems.

## :rocket: Quick Start

### Run with Docker (Recommended)

```bash
# Start Ollama + app together
# Models (nomic-embed-text, qwen2.5:1.5b) are pulled automatically on first run
docker compose up
```

### Run locally

```bash
# Download Ollama Model
ollama pull nomic-embed-text:latest
ollama pull qwen2.5:1.5b

# Install dependencies
uv sync

# Make sure Ollama is running separately
uv run uvicorn src.main:app --reload
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/ingest` | POST | Register text into vector DB (background process) |
| `/ingest/file` | POST | Register a UTF-8 text file into vector DB (txt, md, log, yaml, json, etc.) |
| `/query` | POST | Answer questions using RAG |

`/query` returns a JSON object with three fields:

| Field | Type | Description |
|---|---|---|
| `question` | string | The original question |
| `answer` | string | The LLM answer |
| `thinking` | string \| null | Chain-of-thought reasoning (present when the model uses `<think>` tags) |

**Error responses:**

| Status | Cause |
|---|---|
| `404` | The configured LLM model does not exist in Ollama |
| `503` | Ollama is not reachable |

```bash
# Register text
curl -X POST "http://localhost:8000/ingest" \
  -H "Content-Type: application/json" \
  -d '{"text": "LangChain is a framework for building LLM applications"}'

# Register a plain text file
curl -X POST "http://localhost:8000/ingest/file" \
  -F "file=@/path/to/document.txt"

# Ask a question
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is LangChain?"}'

# Ask a question for Japanese
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is LangChain?","language":"ja_JP"}'
```

## Configuration

Configurable at the top of [src/main.py](../src/main.py):

| Variable | Default | Description |
|---|---|---|
| `PERSIST_DIR` | `./my_rag_db` | ChromaDB persistence directory |
| `EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `LLM_MODEL` | `qwen2.5:1.5b` | Ollama LLM model |
| `RESPONSE_LANG` | `en_US` | Default response language (locale code, e.g. `ja_JP`) |

## Clearing the Database

**Docker:**

```bash
# Stop the app and remove the rag_db volume
docker compose down
docker volume rm bit-rag_rag_db

# Or remove all volumes at once (including ollama_data)
docker compose down -v
```

**Local:**

```bash
rm -rf ./my_rag_db
```

After clearing, restart the app to recreate an empty database.

## Troubleshooting

### Port 11434 is already in use

If Ollama is running locally on the host, Docker will fail to bind port 11434:

```
Error: exposing port TCP 0.0.0.0:11434 -> 0: bind: Only one usage of each socket address
```

The `ollama` container does not need to expose port 11434 to the host — `app` communicates with it over the internal Docker network. Remove the `ports` section from the `ollama` service in `docker-compose.yml` if it exists.

### Bind-mount path error on Windows (Docker Desktop)

On Windows, the bind mount `- .:/app` can fail with:

```
error while creating mount source path '.../mnt/host/e/...': mkdir ...: file exists
```

The application code is already copied into the image at build time (`COPY . .` in the Dockerfile), so the bind mount is not required. Remove `- .:/app` from the `app` service volumes. Note that code changes require a rebuild:

```bash
docker compose build app && docker compose up
```

## :handshake: Contributing

Bug reports and pull requests are welcome.

## :page_facing_up: License

MIT
