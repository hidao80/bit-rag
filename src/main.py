import os
import re
from contextlib import asynccontextmanager
from operator import itemgetter

import ollama as _ollama
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_text_splitters import CharacterTextSplitter
from pydantic import BaseModel

# --- Configuration ---
PERSIST_DIR   = os.getenv("PERSIST_DIR",   "./my_rag_db")
EMBED_MODEL   = os.getenv("EMBED_MODEL",   "nomic-embed-text")
LLM_MODEL     = os.getenv("LLM_MODEL",     "qwen2.5:1.5b")
RESPONSE_LANG = os.getenv("RESPONSE_LANG", "en_US")

# Global variable declarations
vectorstore: Chroma | None = None
qa_chain = None

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _format_docs(docs: list[Document]) -> str:
    return "\n\n".join(doc.page_content for doc in docs)


def _split_thinking(raw: str) -> tuple[str, str | None]:
    """Extract <think>...</think> blocks from the raw LLM output.

    Returns (answer, thinking). `thinking` is None when no tags are present.
    """
    parts = _THINK_RE.findall(raw)
    if not parts:
        return raw.strip(), None
    thinking = "\n\n".join(p.strip() for p in parts)
    answer = _THINK_RE.sub("", raw).strip()
    return answer, thinking


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load DB and models once on app startup."""
    global vectorstore, qa_chain
    embeddings = OllamaEmbeddings(model=EMBED_MODEL)

    # Load existing DB (auto-created if directory does not exist)
    vectorstore = Chroma(
        persist_directory=PERSIST_DIR,
        embedding_function=embeddings
    )

    llm = OllamaLLM(model=LLM_MODEL)
    prompt = PromptTemplate.from_template(
        "Use the following context to answer the question. "
        "Respond in the language specified by locale '{language}'.\n\n"
        "Context:\n{context}\n\n"
        "Question: {question}\n\n"
        "If you need to reason through the answer, wrap your thinking in "
        "<think>...</think> tags, then provide the answer directly and briefly."
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
    qa_chain = (
        {
            "context":  itemgetter("question") | retriever | _format_docs,
            "question": itemgetter("question"),
            "language": itemgetter("language"),
        }
        | prompt
        | llm
        | StrOutputParser()
    )
    print("VectorDB & QA Chain loaded.")
    yield
    # Add shutdown logic here if needed


app = FastAPI(lifespan=lifespan)


class IngestRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    question: str
    language: str = RESPONSE_LANG


class QueryResponse(BaseModel):
    question: str
    answer: str
    thinking: str | None = None


# --- Background ingest processing ---
def process_ingest(text: str):
    if vectorstore is None:
        print("Ingest skipped: vectorstore is not initialized.")
        return
    text_splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = [Document(page_content=x) for x in text_splitter.split_text(text)]
    # Add to the already-loaded instance
    vectorstore.add_documents(docs)
    print(f"Background Ingest: {len(docs)} chunks added.")


# --- Endpoints ---

@app.post("/ingest")
async def ingest_data(request: IngestRequest, background_tasks: BackgroundTasks):
    """Dispatch ingest task to background and return immediately."""
    background_tasks.add_task(process_ingest, request.text)
    return {"status": "accepted", "message": "Ingest started in background."}


@app.post("/ingest/file")
async def ingest_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Ingest a text-based file into the vector database (txt, md, log, yaml, json, etc.)."""
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded text.")
    background_tasks.add_task(process_ingest, text)
    return {"status": "accepted", "message": f"Ingest of '{file.filename}' started in background."}


@app.post("/query", response_model=QueryResponse)
async def query_rag(request: QueryRequest) -> QueryResponse:
    """Answer using the global qa_chain."""
    if qa_chain is None:
        raise HTTPException(status_code=503, detail="DB is not ready.")

    try:
        raw = await qa_chain.ainvoke({"question": request.question, "language": request.language})
    except _ollama.ResponseError as e:
        status = 404 if e.status_code == 404 else 502
        raise HTTPException(status_code=status, detail=str(e.error))
    except ConnectionError:
        raise HTTPException(status_code=503, detail="Cannot connect to Ollama. Make sure it is running.")
    answer, thinking = _split_thinking(raw)
    return QueryResponse(question=request.question, answer=answer, thinking=thinking)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
