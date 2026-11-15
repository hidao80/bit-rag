---
name: architecture-decision-record
description: Architecture Decision Record for bit-rag, derived from Git history.
type: adr
---

# bit-rag — Architecture Decision Record

**Project**: bit-rag — Local RAG API server (FastAPI + LangChain + ChromaDB + Ollama)
**Source**: `git log` (`0da6f30` → `a147ef4`; ADR-0005/0006 from `163fcc3` → `8b3afbd`)
**Generated**: 2026-07-12 (updated 2026-11-15)

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| [ADR-0001](#adr-0001-fastapi--langchain--chromadb--ollama-stack) | FastAPI + LangChain + ChromaDB + Ollama stack | Accepted (vector store layer superseded by ADR-0005) | 2026-02-23 |
| [ADR-0002](#adr-0002-multi-stage-dockerfile-with-non-root-runtime-user) | Multi-stage Dockerfile with non-root runtime user | Accepted | 2026-02-23 |
| [ADR-0003](#adr-0003-ruff-for-linting-and-formatting) | Ruff for linting and formatting | Accepted | 2026-02-23 |
| [ADR-0004](#adr-0004-docker-build-workflow-runner-image) | Docker build workflow runner image | Accepted | 2026-02-23 |
| [ADR-0005](#adr-0005-use-chromadb-directly-instead-of-langchain-chroma) | Use chromadb directly instead of langchain-chroma | Accepted | 2026-11-15 |
| [ADR-0006](#adr-0006-separate-ollama-client-url-from-server-bind-address) | Separate Ollama client URL from server bind address | Accepted | 2026-11-15 |

---

## ADR-0001: FastAPI + LangChain + ChromaDB + Ollama stack

- **Status**: Accepted (the `langchain-chroma` vector store layer is superseded by [ADR-0005](#adr-0005-use-chromadb-directly-instead-of-langchain-chroma))
- **Date**: 2026-02-23
- **Commit**: `0da6f30` (first commit! 🎉)

### Context

The project needed a locally-hosted Retrieval-Augmented-Generation (RAG) API: ingest documents, embed and store them, and answer queries against them without depending on a hosted LLM provider.

### Decision

Build the API on:
- **FastAPI** + **uvicorn** for the HTTP layer (`src/main.py`).
- **LangChain** (`langchain`, `langchain-core`, `langchain-community`, `langchain-text-splitters`) to orchestrate ingestion/splitting/retrieval.
- **ChromaDB** via `langchain-chroma` as the local vector store, persisted to a `my_rag_db/` volume.
- **Ollama** via `langchain-ollama` as the local model runtime, using `nomic-embed-text` for embeddings and `qwen2.5:1.5b` for generation.
- **Pydantic** for request/response schemas, **markdown-it-py** for document parsing.

### Consequences

- Fully local pipeline: no external API keys or network egress required to run.
- Adds an Ollama service dependency (`docker-compose.yml` `ollama` + `ollama-init` services) that must be healthy and have models pulled before the app starts.
- Ties embedding/generation quality to whichever small local models are pulled (`nomic-embed-text`, `qwen2.5:1.5b`); swapping models means updating environment variables (`EMBED_MODEL`, `LLM_MODEL`) and re-pulling.

---

## ADR-0002: Multi-stage Dockerfile with non-root runtime user

- **Status**: Accepted
- **Date**: 2026-02-23
- **Commit**: `0da6f30` (first commit! 🎉)

### Context

The app needed a container image suitable for production use, minimizing image size and avoiding running application code as root.

### Decision

`Dockerfile` uses two stages: a `builder` stage (`python:3.12-slim`) that installs dependencies via `uv sync --frozen --no-dev`, and a `runner` stage that copies only the built `.venv` and app code, creates a dedicated `python` user/group (uid/gid 1001), and runs `uvicorn` as that non-root user.

### Consequences

- Final image excludes build tooling (`uv` install layer) and dev dependencies, reducing attack surface and size.
- Application process does not run as root in the intended (`runner`) target.
- `docker-compose.yml` currently sets `build.target: builder`, i.e. local/compose runs use the *builder* stage (which still runs as root and includes `uv`), not the hardened `runner` stage — this is a known gap between the documented Dockerfile design and how compose invokes it.

---

## ADR-0003: Ruff for linting and formatting

- **Status**: Accepted
- **Date**: 2026-02-23
- **Commits**: `0da6f30` (first commit), `32ceb08` (:recycle: fix linter error), `01a5780` (:recycle: ruff format fixed)

### Context

The project needed a single fast tool for both linting and code formatting in CI (`.github/workflows/lint.yml`, `format.yml`) and locally (`taskipy` tasks).

### Decision

Adopt **ruff** as the sole lint/format tool, configured in `pyproject.toml`:
- `line-length = 120`, `target-version = "py312"`
- Lint rule sets `E`, `F`, `I`, `UP` enabled; `E501` (line too long) ignored since line length is already capped at 120.
- Exposed via `taskipy` tasks `lint` (`ruff check .`) and `fmt` (`ruff format .`).

Two follow-up commits (`32ceb08`, `01a5780`) fixed `src/main.py` and `test/test_main.py` to satisfy ruff's lint and format rules after the initial commit.

### Consequences

- Single dependency covers both linting and formatting, replacing the need for separate tools (e.g. flake8 + black + isort).
- CI enforces style consistency; contributors must run `ruff format`/`ruff check` before merging or CI fails.

---

## ADR-0004: Docker build workflow runner image

- **Status**: Accepted
- **Date**: 2026-02-23
- **Commit**: `2e21f0e` (:bug: Change ubuntu image for Docker build GitHub Action.)

### Context

`.github/workflows/docker.yml` originally pinned the Docker-build job to `runs-on: ubuntu-slim`, which is not a valid GitHub-hosted runner label.

### Decision

Change the runner label from `ubuntu-slim` to `ubuntu-latest`.

### Consequences

- CI Docker build job runs on a valid, maintained GitHub-hosted runner.
- No image-size optimization is applied at the *runner* level (that concern is instead handled inside the Dockerfile itself, see ADR-0002).

---

## ADR-0005: Use chromadb directly instead of langchain-chroma

- **Status**: Accepted
- **Date**: 2026-11-15
- **Commits**: `163fcc3` (:recycle: use chromadb directly), `8b3afbd` (:bug: harden BitRagChromaStore)
- **Supersedes**: the vector store layer of ADR-0001

### Context

The app used only three operations of `langchain_chroma.Chroma` (`add_documents`, `similarity_search`, `as_retriever`), while the `langchain-chroma` 1.1.0 package added an extra dependency layer on top of `chromadb` (1.5.1). Existing databases created through `langchain-chroma` had to remain readable.

### Decision

- Remove `langchain-chroma` and depend on `chromadb>=1.5.1` directly.
- Implement `BitRagChromaStore` in `src/main.py`, a minimal wrapper over `chromadb.PersistentClient`, named to make clear it is not `langchain_chroma.Chroma`. `as_retriever()` returns `BitRagChromaRetriever`, a LangChain `BaseRetriever`, so the LCEL chain is unchanged.
- Keep the collection name `langchain` (the `langchain-chroma` default; configurable via `COLLECTION_NAME`) for compatibility with existing databases.
- Store empty metadata as `None` (chromadb 1.x rejects `{}`) and split `add_documents` into batches by `get_max_batch_size()`.

### Consequences

- One fewer dependency; the vector store behavior is fully owned and tested in this repository (tests run against a real chromadb instance).
- Reading an existing `langchain-chroma` database was confirmed manually by the maintainer on 2026-11-15.
- Only the three operations above exist; other `langchain-chroma` APIs (e.g. `delete`, `similarity_search_with_score`) must be added explicitly if needed.
- Changing `EMBED_MODEL` changes the embedding dimension, so an existing collection becomes unusable; recreate the database or use a different `COLLECTION_NAME`.

---

## ADR-0006: Separate Ollama client URL from server bind address

- **Status**: Accepted
- **Date**: 2026-11-15
- **Commits**: `163fcc3`, `4126efc` (introduce `OLLAMA_BASE_URL`), `8b3afbd` (`OLLAMA_HOST` fallback, error mapping)

### Context

`langchain-ollama` / `ollama` read `OLLAMA_HOST` as the client destination. The same variable is commonly set to `0.0.0.0:11434` to make the Ollama *server* listen on all interfaces, and connecting to `0.0.0.0` fails on Windows, so the app could not reach a running Ollama.

### Decision

- Add `OLLAMA_BASE_URL` for the client destination and pass it explicitly as `base_url` to `OllamaEmbeddings` and `OllamaLLM`; `docker-compose.yml` sets `OLLAMA_BASE_URL=http://ollama:11434`.
- When `OLLAMA_BASE_URL` is unset, fall back to `OLLAMA_HOST` for backward compatibility, replacing wildcard bind addresses (`0.0.0.0`, `::`) with `127.0.0.1`; the final default is `http://127.0.0.1:11434`.
- Translate Ollama errors in one helper (`_ollama_errors()`) shared by `/query` and `/debug/search`: model not found → `404`, other Ollama errors → `502`, connection failures and HTTP client timeouts → `503`.
- Do not add a configurable client timeout; the Ollama client default (no timeout) is kept as the existing specification.

### Consequences

- The app works when the host environment sets `OLLAMA_HOST=0.0.0.0:11434` for the Ollama server.
- Deployments that used `OLLAMA_HOST` to point at a remote Ollama keep working without changes.
- Without a timeout, a slow or stuck Ollama request waits indefinitely instead of returning `503`; introducing a timeout would be a new decision.

---

## Non-architectural changes (excluded)

The following commits were documentation-only wording/formatting changes to `docs/README.md` and were not treated as architecture decisions: `d140080` (badge formatting), `3a3908e` (description clarification), `a147ef4` (license/CI badges).

<!-- commit: a147ef43bd34036c225a6a513a907e0ff6bd99e7 -->
