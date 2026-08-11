---
name: analyzed-ui
description: UI/routing/state analysis for bit-rag — API-only project with no frontend.
type: analysis
---

# UI Analysis — Routing & State

## Status: No UI

bit-rag is a **headless API server**. There is no frontend, browser-rendered UI, or client-side routing. All interaction is via HTTP.

## API Surface (as Client Interface)

The following summarises the public interface from a consumer's perspective.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingest` | Ingest raw text |
| `POST` | `/ingest/file` | Upload a UTF-8 file |
| `POST` | `/query` | RAG query |
| `GET` | `/debug/search` | Raw vector search (debug tool) |
| `GET` | `/docs` | FastAPI auto-generated Swagger UI |
| `GET` | `/redoc` | FastAPI auto-generated ReDoc UI |
| `GET` | `/openapi.json` | FastAPI auto-generated OpenAPI schema |

> Note: `/docs`, `/redoc`, and `/openapi.json` are provided automatically by FastAPI and are not defined in `docs/openapi.yml`. They serve as the de facto UI for manual exploration.

## State Management

All application state is server-side and global:

| State | Variable | Scope | Lifecycle |
|---|---|---|---|
| Vector store | `vectorstore` | Module-global | Loaded on startup, never reset |
| QA chain | `qa_chain` | Module-global | Built on startup, never reset |

There is no session state, user state, or request-scoped state.

## Integration Suggestions (Speculative)

If a UI were to be added, the following approaches are recommended:

| Option | Description | Recommendation (1–5) |
|---|---|---|
| Static HTML + fetch | Plain HTML/JS calling the API directly | 3 — Simple, zero build tooling |
| Gradio | Python-native chat UI for LLM apps | 4 — Fast to integrate, fits LLM use case |
| Streamlit | Python-native dashboard UI | 3 — Good for demos, not production |
| Next.js | Full React frontend | 2 — Overkill for a local RAG tool |

<!-- commit: a147ef43bd34036c225a6a513a907e0ff6bd99e7 -->
