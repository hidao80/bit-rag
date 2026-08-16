---
name: architecture-decision-record
description: Architecture Decision Record for bit-rag, derived from Git history.
type: adr
---

# bit-rag — Architecture Decision Record

**Project**: bit-rag — Local RAG API server (FastAPI + LangChain + ChromaDB + Ollama)
**Source**: `git log` (16 commits, `0da6f30` → `b300cb2`)
**Generated**: 2026-08-16

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| [ADR-0001](#adr-0001-fastapi--langchain--chromadb--ollama-stack) | FastAPI + LangChain + ChromaDB + Ollama stack | Accepted | 2026-02-23 |
| [ADR-0002](#adr-0002-multi-stage-dockerfile-with-non-root-runtime-user) | Multi-stage Dockerfile with non-root runtime user | Accepted | 2026-02-23 |
| [ADR-0003](#adr-0003-ruff-for-linting-and-formatting) | Ruff for linting and formatting | Accepted | 2026-02-23 |
| [ADR-0004](#adr-0004-docker-build-workflow-runner-image) | Docker build workflow runner image | Accepted | 2026-02-23 |
| [ADR-0005](#adr-0005-markdown-aware-chunking-and-a-debug-search-endpoint) | Markdown-aware chunking and a debug search endpoint | Accepted | 2026-08-11 |
| [ADR-0006](#adr-0006-on-demand-analysis-skills-replace-committed-analysis-docs) | On-demand analysis skills replace committed analysis docs | Accepted | 2026-08-13 |
| [ADR-0007](#adr-0007-windows-powershell-installer-as-an-alternative-onboarding-path) | Windows PowerShell installer as an alternative onboarding path | Accepted | 2026-08-13 |

---

## ADR-0001: FastAPI + LangChain + ChromaDB + Ollama stack

- **Status**: Accepted
- **Date**: 2026-02-23
- **Commit**: `0da6f30` (first commit)

### Context

The project needed a locally-hosted Retrieval-Augmented-Generation (RAG) API: ingest documents, embed and store them, and answer queries against them without depending on a hosted LLM provider.

### Decision

Build the API on:
- **FastAPI** + **uvicorn** for the HTTP layer (`src/main.py`).
- **LangChain** (`langchain`, `langchain-core`, `langchain-community`, `langchain-text-splitters`) to orchestrate ingestion/splitting/retrieval.
- **ChromaDB** via `langchain-chroma` as the local vector store, persisted to a `my_rag_db/` volume.
- **Ollama** via `langchain-ollama` as the local model runtime, using `nomic-embed-text` for embeddings and `qwen2.5:1.5b` for generation.
- **Pydantic** for request/response schemas.

### Consequences

- Fully local pipeline: no external API keys or network egress required to run.
- Adds an Ollama service dependency (`docker-compose.yml` `ollama` + `ollama-init` services) that must be healthy and have models pulled before the app starts.
- Ties embedding/generation quality to whichever small local models are pulled (`nomic-embed-text`, `qwen2.5:1.5b`); swapping models means updating environment variables (`EMBED_MODEL`, `LLM_MODEL`) and re-pulling.

---

## ADR-0002: Multi-stage Dockerfile with non-root runtime user

- **Status**: Accepted
- **Date**: 2026-02-23
- **Commit**: `0da6f30` (first commit)

### Context

The app needed a container image suitable for production use, minimizing image size and avoiding running application code as root.

### Decision

`Dockerfile` uses two stages: a `builder` stage (`python:3.12-slim`) that installs dependencies via `uv sync --frozen --no-dev`, and a `runner` stage that copies only the built `.venv` and app code, creates a dedicated `python` user/group (uid/gid 1001), and runs `uvicorn` as that non-root user.

### Consequences

- Final image excludes build tooling (`uv` install layer) and dev dependencies, reducing attack surface and size.
- Application process does not run as root in the intended (`runner`) target.
- `docker-compose.yml` sets `build.target: builder`, i.e. local/compose runs use the *builder* stage (which still runs as root and includes `uv`), not the hardened `runner` stage — a known gap between the documented Dockerfile design and how compose invokes it.

---

## ADR-0003: Ruff for linting and formatting

- **Status**: Accepted
- **Date**: 2026-02-23
- **Commits**: `0da6f30` (first commit), `32ceb08` (fix linter error), `01a5780` (ruff format fixed)

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
- **Commit**: `2e21f0e` (Change ubuntu image for Docker build GitHub Action)

### Context

`.github/workflows/docker.yml` originally pinned the Docker-build job to `runs-on: ubuntu-slim`, which is not a valid GitHub-hosted runner label.

### Decision

Change the runner label from `ubuntu-slim` to `ubuntu-latest`.

### Consequences

- CI Docker build job runs on a valid, maintained GitHub-hosted runner.
- No image-size optimization is applied at the *runner* level (that concern is instead handled inside the Dockerfile itself, see ADR-0002).
- Other CI jobs (`audit`, `format`, `lint`, `test`) intentionally kept `runs-on: ubuntu-slim` since they only shell out to `uv`/`ruff`/`pytest` and don't invoke Docker.

---

## ADR-0005: Markdown-aware chunking and a debug search endpoint

- **Status**: Accepted
- **Date**: 2026-08-11
- **Commit**: `c123779` (Add markdown-it-py dependency for enhanced Markdown processing)

### Context

The original ingest pipeline used a plain `CharacterTextSplitter` for all input, which splits Markdown documents blindly — breaking tables mid-row and losing section context (heading hierarchy) for retrieved chunks.

### Decision

- Add **markdown-it-py** to parse Markdown and detect table boundaries.
- Split Markdown input with LangChain's `MarkdownHeaderTextSplitter` (H1/H2/H3) before chunking, and prefix each resulting chunk with a breadcrumb of its section headings.
- Convert Markdown tables into independent JSON-line chunks (one JSON object per row) instead of splitting them as prose, keeping each row a self-contained retrievable unit.
- Merge chunks shorter than `MIN_CHUNK_SIZE` into the previous chunk (except JSON table rows, which stay independent) to avoid low-signal fragments in the vector store.
- Introduce three new environment variables to tune this behavior: `CHUNK_SIZE` (default `3200`), `CHUNK_OVERLAP` (default `300`), `MIN_CHUNK_SIZE` (default `CHUNK_SIZE // 2`).
- Add a `GET /debug/search` endpoint that runs `vectorstore.similarity_search` directly and returns raw chunks + metadata, bypassing the LLM — for inspecting what ingest actually produced.

### Consequences

- Retrieval quality improves for Markdown-heavy sources (the project's primary ingest format) at the cost of a more complex splitting pipeline (`_split_markdown`, `_chunk_section`, `_table_tokens_to_jsonl`, `_pack_into_chunks`, `_merge_short_chunks` in `src/main.py`).
- Plain-text files (no Markdown extension) still use `RecursiveCharacterTextSplitter`, so two distinct chunking code paths must be kept in sync when tuning retrieval behavior.
- `/debug/search` exposes stored chunk content and metadata with no auth — acceptable for a local-only dev tool, but it must not be exposed publicly without adding access control.

---

## ADR-0006: On-demand analysis skills replace committed analysis docs

- **Status**: Accepted
- **Date**: 2026-08-13
- **Commits**: `371969e` (add analysis docs for db/index/infra/logic/security/ui), `879daca` (remove those files; add `code-analyze`, `make-lp`, `update-adr` command docs; add `docs/ADR.md`)

### Context

`371969e` committed a one-off snapshot of static analysis output (`docs/analyzed/{db,index,infra,logic,security,ui}.md`) directly into the repository. Static, committed analysis drifts from the code as soon as the next change lands, and there was no repeatable process to regenerate it.

### Decision

Replace the committed analysis snapshot with repeatable, on-demand Claude Code skills (`.claude/commands/code-analyze.md`, `make-lp.md`, `update-adr.md`) that regenerate analysis/documentation artifacts from the current code and Git history whenever invoked, rather than keeping stale output in version control. `docs/ADR.md` (this document's sibling, tracking history through commit `a147ef4`) was introduced as the first artifact produced by this workflow.

### Consequences

- Analysis documents are no longer committed as static snapshots; they are regenerated on demand and can go stale between invocations, but won't silently drift without anyone noticing since regeneration is a deliberate action.
- Contributors need the Claude Code skill definitions (`.claude/commands/*.md`) to reproduce analysis output locally; there's no plain-Markdown fallback checked into `docs/`.
- `docs/analyzed/security.md`'s prompt-injection finding about the unescaped `language` field in `QueryRequest` (documented, then lightly edited in `87a0be0`) was deleted along with the rest of `docs/analyzed/`; that finding is no longer tracked anywhere and should be re-verified against the current `src/main.py` if security posture is revisited.

---

## ADR-0007: Windows PowerShell installer as an alternative onboarding path

- **Status**: Accepted
- **Date**: 2026-08-13
- **Commit**: `05a3357` (add `src/install.ps1`)

### Context

The documented setup paths (`docker compose up`, or manual `ollama pull` + `uv sync` + `uvicorn`) assume the user already has Docker or Ollama/uv installed and is comfortable with a terminal. There was no guided, single-command path for a Windows user starting from a bare machine.

### Decision

Add `src/install.ps1`, a standalone PowerShell script that:
- Detects the system UI language and greets/logs in Japanese, English, or Chinese (`-Lang` overrides auto-detection).
- Checks for and installs Python and Ollama via `winget` when missing, falling back to printing manual download links if `winget` is unavailable.
- Pulls the configured Ollama model (`-Model`, default matches `LLM_MODEL`'s default) and waits for the Ollama service to become ready before finishing.
- Is entirely independent of the Docker/uv workflow — it is not invoked by `docker-compose.yml`, `pyproject.toml` tasks, or CI, and is not referenced from `docs/README.md`.

### Consequences

- Provides a lower-friction entry point for Windows users without Docker or a pre-existing Python toolchain.
- Introduces a third, PowerShell-based setup path (alongside Docker Compose and manual local setup) that must be kept in sync by hand — it re-implements model-name and language defaults that already exist as environment variables/config in `src/main.py`, with no shared source of truth.
- `winget`-based installation only works on Windows 10/11 with App Installer present; the script prints a manual fallback but does not automate installation on older Windows versions.

---

## Non-architectural changes (excluded)

The following commits were documentation-only, cosmetic, or asset-only changes and were not treated as architecture decisions:

- `d140080` — README badge formatting.
- `3a3908e` — README description wording clarification.
- `a147ef4` — added license/CI badges to README.
- `c382b80` — added initial `docs/index.html` and `docs/llms.txt` landing-page/LLM-summary content.
- `87a0be0` — minor prose edit inside the (since-deleted) `docs/analyzed/security.md`.
- `a1e74d4` — swapped the OGP/social-preview image referenced by the landing page.
- `6c5b6f9` — added `graphify-out/` to `.dockerignore`/`.gitignore`.
- `6d29c26` — added `AGENTS.md` project-overview documentation.
- `b300cb2` — clarified the favicon-asset description in `make-lp` skill documentation.

<!-- commit: b300cb24081914204a2e3836c729adccd1d020ba -->
