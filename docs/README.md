# bit-rag

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)&emsp;
![Lint](https://github.com/hidao80/bit-rag/actions/workflows/lint.yml/badge.svg)&emsp;
![Format](https://github.com/hidao80/bit-rag/actions/workflows/format.yml/badge.svg)&emsp;
![Test](https://github.com/hidao80/bit-rag/actions/workflows/test.yml/badge.svg)&emsp;
![Audit](https://github.com/hidao80/bit-rag/actions/workflows/audit.yml/badge.svg)&emsp;
![Docker](https://github.com/hidao80/bit-rag/actions/workflows/docker.yml/badge.svg)&emsp;
[![Ask DeepWiki](https://img.shields.io/badge/Ask_DeepWiki-007ec6?logo=data%3Aimage%2Fpng%3Bbase64%2CiVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAACXBIWXMAAAPoAAAD6AG1e1JrAAACIUlEQVRYw%2B2XP2gUQRTGv7d3JhYWQawkIBaCVWzETos0gmAnVoKNTSoLK0E7EQQrC20sBVFBtLPQRgTBtBaKjYgIQUSxiJq7fT%2BLvCGPJZdNLt4dQj5Y3u7sznzfzLw%2Fs9IO%2FicANiniCujEfWdsQgBLxAbsbraPZcmBfcAt4DNwKQsZNfEUsAB8YRV12LfA6ZHuedg7AO7ed%2Fc%2BUBcbQhbiu%2B6wXIM6EnZWkszMJe2Ke0n6I2la0v51hFeSMLN6OwIK6jJwEBdUYb2MAxRSz6sY4geiahFgLe1Hwq6YWe3us8AN4FQQU4QM64SPY69Xyr43fADgNjAPXHb3peSsD4FDQ0VLEjAHvIhBPS6AHvA1bBO9JPAXcHFbIRtJ5yzwIQZ9CZwAusDJENIkLqsG8DpNyIZJwSUk9wLHgakcesC1JCCjiHm1kYDNOEjptCxpSVK%2F8f73OFLxPLAYM3oCzEX7MXf%2FlJbc%2F8kWpA4HgQdpYI9IWAbeh83whi84cHXL%2B58EPBoQhnmm94EzwE3gZ2p%2FDhzdbhg%2BTaRr01x7ftb4%2FjBwFzjXrCvDpmLW9crVLNeR9CaapoGemb2TdCERW1tNaBNQ8jktwmozqwtpqRNtdWAjARYk39IS12ZWRX7vmJmA71nQZgi36gN7gCvAj5xc3P0jcH7kx7Ik5IC73wsh14GZsZySow5002l4Jr0b6%2Bm4eSyvpAn8lEzsx2QHo8RfUrlN%2BuPq4ksAAAAASUVORK5CYII%3D&labelColor=010101)](https://deepwiki.com/hidao80/bit-rag)

# Overview

Build the simplest local RAG API server.

:link: [Landing page](https://hidao80.github.io/bit-rag/) &nbsp;|&nbsp; :robot: [llms.txt](llms.txt) for LLM-friendly project summary

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
| `/debug/search` | GET | Return raw retrieved chunks for a query without invoking the LLM (debug only) |

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
| `502` | Ollama returned an error other than model-not-found |
| `503` | Ollama is not reachable, or the vector DB is not ready |

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
| `CHUNK_SIZE` | `3200` | Max characters per ingest chunk |
| `CHUNK_OVERLAP` | `300` | Character overlap between plain-text chunks |
| `MIN_CHUNK_SIZE` | `CHUNK_SIZE // 2` | Chunks shorter than this are merged with the preceding chunk |

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
