from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.retrievers import BaseRetriever

import src.main as main_module
from src.main import _format_docs

# --- Unit: _format_docs ---


def test_format_docs_empty():
    assert _format_docs([]) == ""


def test_format_docs_single():
    assert _format_docs([Document(page_content="hello")]) == "hello"


def test_format_docs_multiple():
    docs = [Document(page_content="foo"), Document(page_content="bar")]
    assert _format_docs(docs) == "foo\n\nbar"


# --- Unit: _resolve_ollama_base_url ---


@pytest.mark.parametrize(
    ("base_url", "host", "expected"),
    [
        (None, None, "http://127.0.0.1:11434"),
        ("http://ollama:11434", "0.0.0.0:11434", "http://ollama:11434"),
        (None, "http://gpu-box:11434", "http://gpu-box:11434"),
        (None, "gpu-box", "http://gpu-box:11434"),
        (None, "0.0.0.0:11434", "http://127.0.0.1:11434"),
        (None, "0.0.0.0", "http://127.0.0.1:11434"),
        (None, ":11434", "http://127.0.0.1:11434"),
        (None, "[::]:11434", "http://127.0.0.1:11434"),
        (None, "[::1]:11434", "http://[::1]:11434"),
        (None, "https://user:pw@example.com/ollama/", "https://user:pw@example.com/ollama"),
    ],
)
def test_resolve_ollama_base_url(monkeypatch, base_url, host, expected):
    for name, value in (("OLLAMA_BASE_URL", base_url), ("OLLAMA_HOST", host)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert main_module._resolve_ollama_base_url() == expected


# --- Unit: BitRagChromaStore (real chromadb, fake embeddings) ---


@pytest.fixture
def store(tmp_path):
    return main_module.BitRagChromaStore(
        persist_directory=str(tmp_path), embedding_function=DeterministicFakeEmbedding(size=8)
    )


def test_store_add_documents_empty(store):
    assert store.add_documents([]) == []
    assert store._collection.count() == 0


def test_store_add_documents_returns_unique_ids(store):
    ids = store.add_documents([Document(page_content="a"), Document(page_content="b")])
    assert len(ids) == len(set(ids)) == 2
    assert store._collection.count() == 2


def test_store_metadata_empty_and_non_empty(store):
    # chromadb rejects {} metadata, so empty metadata must be stored as None and read back as {}
    store.add_documents([Document(page_content="plain"), Document(page_content="tagged", metadata={"x": 1})])
    by_content = {d.page_content: d.metadata for d in store.similarity_search("plain", k=2)}
    assert by_content == {"plain": {}, "tagged": {"x": 1}}


def test_store_similarity_search_formats_results(store):
    store.add_documents([Document(page_content=t) for t in ("alpha", "beta", "gamma")])
    docs = store.similarity_search("beta", k=2)
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)
    assert docs[0].page_content == "beta"


def test_store_similarity_search_empty_collection(store):
    assert store.similarity_search("anything", k=3) == []


def test_store_add_documents_splits_by_max_batch_size(store, monkeypatch):
    monkeypatch.setattr(store._client, "get_max_batch_size", lambda: 2)
    add_spy = MagicMock(wraps=store._collection.add)
    monkeypatch.setattr(store._collection, "add", add_spy)
    ids = store.add_documents([Document(page_content=str(i)) for i in range(5)])
    assert [len(call.kwargs["ids"]) for call in add_spy.call_args_list] == [2, 2, 1]
    assert len(ids) == 5
    assert store._collection.count() == 5


def test_store_as_retriever_respects_k(store):
    store.add_documents([Document(page_content=t) for t in ("alpha", "beta", "gamma")])
    retriever = store.as_retriever(search_kwargs={"k": 1})
    assert isinstance(retriever, BaseRetriever)
    docs = retriever.invoke("gamma")
    assert [d.page_content for d in docs] == ["gamma"]


async def test_store_as_retriever_async(store):
    store.add_documents([Document(page_content=t) for t in ("alpha", "beta")])
    docs = await store.as_retriever(search_kwargs={"k": 2}).ainvoke("alpha")
    assert len(docs) == 2
    assert docs[0].page_content == "alpha"


def test_store_as_retriever_default_k(store):
    assert store.as_retriever().k == 4


# --- Unit: process_ingest ---


def test_process_ingest_skips_when_no_vectorstore(capsys):
    original = main_module.vectorstore
    main_module.vectorstore = None
    try:
        main_module.process_ingest("some text")
        assert "skipped" in capsys.readouterr().out
    finally:
        main_module.vectorstore = original


def test_process_ingest_adds_documents():
    mock_vs = MagicMock()
    original = main_module.vectorstore
    main_module.vectorstore = mock_vs
    try:
        main_module.process_ingest("LangChain is a framework for building LLM applications.")
        mock_vs.add_documents.assert_called_once()
    finally:
        main_module.vectorstore = original


# --- Fixture ---


@pytest.fixture
def client():
    mock_vs = MagicMock()
    mock_qa = MagicMock()
    mock_qa.ainvoke = AsyncMock(return_value="LangChain is a framework.")

    with (
        patch("src.main.OllamaEmbeddings"),
        patch("src.main.OllamaLLM"),
        patch("src.main.BitRagChromaStore", return_value=mock_vs),
        patch("src.main.PromptTemplate"),
        patch("src.main.StrOutputParser"),
    ):
        with TestClient(main_module.app) as c:
            main_module.qa_chain = mock_qa
            main_module.vectorstore = mock_vs
            yield c, mock_vs, mock_qa


# --- API: POST /ingest ---


def test_ingest_returns_accepted(client):
    c, _, _ = client
    response = c.post("/ingest", json={"text": "LangChain is a framework"})
    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "message": "Ingest started in background.",
    }


def test_ingest_triggers_add_documents(client):
    c, mock_vs, _ = client
    c.post("/ingest", json={"text": "LangChain is a framework for building LLM applications"})
    mock_vs.add_documents.assert_called_once()


# --- API: POST /query ---


def test_query_returns_answer(client):
    c, _, _ = client
    response = c.post("/query", json={"question": "What is LangChain?"})
    assert response.status_code == 200
    data = response.json()
    assert data["question"] == "What is LangChain?"
    assert data["answer"] == "LangChain is a framework."


def test_query_passes_question_to_chain(client):
    c, _, mock_qa = client
    c.post("/query", json={"question": "What is LangChain?"})
    mock_qa.ainvoke.assert_called_once_with({"question": "What is LangChain?", "language": main_module.RESPONSE_LANG})


def test_debug_search_returns_503_when_ollama_unreachable(client):
    c, mock_vs, _ = client
    mock_vs.similarity_search.side_effect = ConnectionError
    response = c.get("/debug/search", params={"q": "test"})
    assert response.status_code == 503


@pytest.mark.parametrize(("ollama_status", "expected"), [(404, 404), (500, 502)])
def test_debug_search_maps_ollama_response_error(client, ollama_status, expected):
    c, mock_vs, _ = client
    mock_vs.similarity_search.side_effect = main_module._ollama.ResponseError("model not found", ollama_status)
    response = c.get("/debug/search", params={"q": "test"})
    assert response.status_code == expected
    assert response.json()["detail"] == "model not found"


@pytest.mark.parametrize(("ollama_status", "expected"), [(404, 404), (500, 502)])
def test_query_maps_ollama_response_error(client, ollama_status, expected):
    c, _, mock_qa = client
    mock_qa.ainvoke.side_effect = main_module._ollama.ResponseError("model not found", ollama_status)
    response = c.post("/query", json={"question": "test"})
    assert response.status_code == expected


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (httpx.ReadTimeout("timed out"), "Ollama did not respond in time."),
        (httpx.ConnectTimeout("timed out"), "Ollama did not respond in time."),
        (httpx.RemoteProtocolError("disconnected"), "Cannot connect to Ollama. Make sure it is running."),
    ],
)
def test_ollama_httpx_errors_return_503(client, error, detail):
    c, mock_vs, mock_qa = client
    mock_vs.similarity_search.side_effect = error
    mock_qa.ainvoke.side_effect = error
    for response in (c.get("/debug/search", params={"q": "test"}), c.post("/query", json={"question": "test"})):
        assert response.status_code == 503
        assert response.json()["detail"] == detail


def test_query_returns_503_when_ollama_unreachable(client):
    c, _, mock_qa = client
    mock_qa.ainvoke.side_effect = ConnectionError
    response = c.post("/query", json={"question": "test"})
    assert response.status_code == 503


def test_query_returns_503_when_not_ready(client):
    c, _, _ = client
    original_qa = main_module.qa_chain
    main_module.qa_chain = None
    try:
        response = c.post("/query", json={"question": "test"})
        assert response.status_code == 503
        assert response.json()["detail"] == "DB is not ready."
    finally:
        main_module.qa_chain = original_qa
