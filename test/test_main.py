from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

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
        patch("src.main.Chroma", return_value=mock_vs),
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
