---
name: analyzed-security
description: Security posture, access controls, and vulnerability analysis for bit-rag.
type: analysis
---

# Security Analysis — Posture & Access Controls

## Authentication & Authorization

| Control | Status |
|---|---|
| API authentication | **None** — all endpoints are publicly accessible |
| API key / token | Not implemented |
| Rate limiting | **None** |
| CORS | Not configured (FastAPI default: no CORS middleware) |
| HTTPS | Not configured (uvicorn runs plain HTTP) |

> **Risk**: This is a local-only tool by design. All security risks below are relevant only if the server is exposed to a network.

## Input Validation

| Endpoint | Validation | Risk |
|---|---|---|
| `POST /ingest` | Pydantic validates `text: str` — no length limit | Large payloads accepted without limit |
| `POST /ingest/file` | UTF-8 decode check only; no file type or size limit | Large file upload DoS risk |
| `POST /query` | Pydantic validates `question: str`, `language: str` — no length limit | Prompt injection via `question` or `language` fields |
| `GET /debug/search` | `q: str`, `k: int` — no limits; k is passed directly to ChromaDB | `k` is unbounded; very large k may degrade performance |

## Prompt Injection Risk

The `language` field from `QueryRequest` is injected directly into the LLM prompt:

```python
# src/main.py:58-65
prompt = PromptTemplate.from_template(
    "...Respond in the language specified by locale '{language}'.\n\n..."
)
```

A malicious `language` value such as `"en_US. Ignore all previous instructions and..."` would be passed verbatim to the LLM. This is a **prompt injection** vector.

**Severity**: Medium (local tool, no auth).

## Secret Management

| Item | Status |
|---|---|
| Hardcoded secrets | **None found** |
| `.env` usage | `.env` is in `.gitignore`; no `python-dotenv` dependency |
| API keys | Not required (Ollama is local) |
| Environment variable defaults | All defaults are safe non-secret values |

## Dependency Security

| Tool | Configuration |
|---|---|
| `pip-audit` | Runs in CI (`audit.yml`) on every push/PR |
| `ruff` | Static analysis for code quality (not security-focused) |
| `bandit` | **Not configured** |

> `bandit` (Python security static analysis) is not in `pyproject.toml` dev dependencies and is not run in CI.

## Docker Security

| Control | Status |
|---|---|
| Non-root user in Dockerfile | Yes — `python:python` (uid/gid 1001) in runner stage |
| Non-root user in Compose | **No** — Compose uses `target: builder` (root) |
| Image pinning | `ollama/ollama:latest` — unpinned, mutable tag |
| `PYTHONDONTWRITEBYTECODE` | Set (reduces attack surface slightly) |
| Read-only filesystem | Not configured |
| Resource limits | Not configured in Compose |

## `/debug/search` Exposure

The `GET /debug/search` endpoint exposes raw vector database content including all stored chunk text and metadata. It is:
- Not authenticated
- Documented in `openapi.yml`
- Accessible to anyone who can reach the server

**Severity**: Low for local use; High if exposed to a network.

## Summary

| Finding | Severity | Applicable When |
|---|---|---|
| No authentication on any endpoint | High | Network-exposed |
| No rate limiting | Medium | Network-exposed |
| Prompt injection via `language` field | Medium | Always |
| No input size limits (text/file) | Medium | Network-exposed |
| `/debug/search` public and unauthenticated (now documented) | Low (local) / High (network) | Network-exposed |
| Compose runs as root (builder stage) | Medium | Container deployment |
| `bandit` not in CI | Low | Development |
| `ollama/ollama:latest` unpinned | Low | Container deployment |

<!-- commit: a147ef43bd34036c225a6a513a907e0ff6bd99e7 -->
