# AGENTS.md

## Project Overview

bit-rag is a RAG (Retrieval-Augmented Generation) API built with FastAPI, LangChain, ChromaDB, and Ollama. It ingests Markdown documents, splits and embeds them, stores vectors in a persistent Chroma DB, and answers questions by retrieving relevant chunks and passing them to a local Ollama LLM.

- Entry point: `src/main.py`
- Tests: `test/test_main.py` (pytest)
- Task runner: `taskipy` (see `pyproject.toml` for `dev`, `test`, `lint`, `fmt`, `audit`, `sync` tasks)
- Config via environment variables: `PERSIST_DIR`, `EMBED_MODEL`, `LLM_MODEL`, `RESPONSE_LANG`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MIN_CHUNK_SIZE`

## Workflow

- When performing code reviews, fix issues by severity (CRITICAL → HIGH → MEDIUM → LOW) and run tests after each fix before proceeding to the next. Do not batch large refactoring changes together.
