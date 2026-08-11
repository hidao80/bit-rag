import json
import os
import re
from contextlib import asynccontextmanager
from operator import itemgetter
from pathlib import Path

import ollama as _ollama
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from markdown_it import MarkdownIt
from pydantic import BaseModel

# --- Configuration ---
PERSIST_DIR = os.getenv("PERSIST_DIR", "./my_rag_db")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:1.5b")
RESPONSE_LANG = os.getenv("RESPONSE_LANG", "en_US")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "3200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "300"))
MIN_CHUNK_SIZE = int(os.getenv("MIN_CHUNK_SIZE", str(CHUNK_SIZE // 2)))

# Global variable declarations
vectorstore: Chroma | None = None
qa_chain = None

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_FRONTMATTER_DELIM_RE = re.compile(r"^-{3,}\s*$")


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
    vectorstore = Chroma(persist_directory=PERSIST_DIR, embedding_function=embeddings)

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
            "context": itemgetter("question") | retriever | _format_docs,
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


_md = MarkdownIt().enable("table")

_MARKDOWN_EXTENSIONS = {".md", ".markdown"}
_BULLET_LINE_RE = re.compile(r"^\s*[-$]\s+.+")


def _strip_frontmatter(text: str) -> str:
    """YAMLフロントマター（--- で囲まれたブロック）を除去して本文のみを返す。"""
    lines = text.splitlines()
    if not lines or not _FRONTMATTER_DELIM_RE.match(lines[0]):
        return text
    for i, line in enumerate(lines[1:], 1):
        if _FRONTMATTER_DELIM_RE.match(line):
            return "\n".join(lines[i + 1 :]).lstrip("\n")
    return text


def _make_breadcrumb(metadata: dict) -> str:
    """ヘッダー階層のメタデータ {"h1": ..., "h2": ..., "h3": ...} からパンくず文字列を生成する。"""
    parts = [metadata[k] for k in ("h1", "h2", "h3") if k in metadata]
    return " > ".join(parts)


def _table_tokens_to_jsonl(tokens: list, table_idx: int) -> list[str]:
    """Convert a table's token stream into JSON Lines strings.

    Reads th/td inline token content directly — no string splitting on '|' needed.
    Each data row becomes: {"header1": "value1", "header2": "value2", ...}
    """
    headers: list[str] = []
    current_row: list[str] = []
    result: list[str] = []
    in_tbody = False

    i = table_idx + 1  # skip table_open itself
    while i < len(tokens) and tokens[i].type != "table_close":
        t = tokens[i]
        if t.type == "thead_close":
            headers = current_row[:]
            current_row.clear()
        elif t.type == "tbody_open":
            in_tbody = True
        elif t.type == "tr_close" and in_tbody and current_row:
            result.append(json.dumps(dict(zip(headers, current_row)), ensure_ascii=False))
            current_row.clear()
        elif t.type == "inline":
            current_row.append(t.content.strip())
        i += 1

    return result


def _units_from_text(text: str) -> list[tuple[str, bool]]:
    """テキストを (内容, is_bullet) のユニットリストに変換する。

    - 箇条書き行（_BULLET_LINE_RE に一致）は is_bullet=True で 1 行ずつ独立。
    - それ以外は \\n\\n 区切りのブロック単位で is_bullet=False。
    """
    units: list[tuple[str, bool]] = []
    for block in re.split(r"\n\n+", text):
        block = block.strip()
        if not block:
            continue
        buf: list[str] = []
        for line in block.splitlines():
            if _BULLET_LINE_RE.match(line):
                if buf:
                    units.append(("\n".join(buf), False))
                    buf = []
                units.append((line.strip(), True))
            else:
                buf.append(line)
        if buf:
            units.append(("\n".join(buf), False))
    return units


def _pack_into_chunks(units: list[tuple[str, bool]], chunk_size: int, breadcrumb: str) -> list[str]:
    """テキストユニットを chunk_size 以内にまとめてチャンクにする。

    - 箇条書き行（is_bullet=True）は必ず 1 行 1 チャンクとして独立させる。
    - 本文ブロック（is_bullet=False）は chunk_size 以内で連結する。
    - 各チャンクの先頭にセクション名（パンくず）を付加する。
    """
    prefix = f"[{breadcrumb}]\n" if breadcrumb else ""
    available = chunk_size - len(prefix)
    result: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def _flush() -> None:
        nonlocal buf_len
        if buf:
            result.append(prefix + "\n\n".join(buf))
            buf.clear()
            buf_len = 0

    for content, is_bullet in units:
        if is_bullet:
            _flush()
            result.append(prefix + content)
        else:
            content_len = len(content)
            if content_len > available:
                _flush()
                fallback = RecursiveCharacterTextSplitter(
                    chunk_size=available,
                    chunk_overlap=0,
                    separators=["。", "．", ". ", "\n", " ", ""],
                )
                for sub in fallback.split_text(content):
                    result.append(prefix + sub)
            else:
                sep_len = 2 if buf else 0
                if buf and buf_len + sep_len + content_len > available:
                    _flush()
                    sep_len = 0
                buf.append(content)
                buf_len += sep_len + content_len

    _flush()
    return result


def _chunk_section(section_text: str, chunk_size: int, breadcrumb: str) -> list[str]:
    """セクションテキストをテーブルと本文で分離してチャンクに変換する。

    - テーブル → _table_tokens_to_jsonl で JSON 行に変換（独立チャンク）
    - 本文 → _paragraphs_from_text で段落に分解し _pack_into_chunks でまとめる
    文書内の出現順を保って結果を返す。
    """
    source_lines = section_text.splitlines()
    tokens = _md.parse(section_text)

    result: list[str] = []
    prev_end = 0

    for i, token in enumerate(tokens):
        if token.type == "table_open" and token.map is not None:
            start, end = token.map
            # テーブル前の本文を段落単位で処理
            if start > prev_end:
                segment = "\n".join(source_lines[prev_end:start]).strip()
                if segment:
                    result.extend(_pack_into_chunks(_units_from_text(segment), chunk_size, breadcrumb))
            # テーブル行を JSON に変換（セクション名は付加しない）
            result.extend(_table_tokens_to_jsonl(tokens, i))
            prev_end = end

    # 末尾の本文
    if prev_end < len(source_lines):
        segment = "\n".join(source_lines[prev_end:]).strip()
        if segment:
            result.extend(_pack_into_chunks(_units_from_text(segment), chunk_size, breadcrumb))

    return result


def _split_markdown(
    text: str,
    chunk_size: int = CHUNK_SIZE,
) -> list[str]:
    """Markdown テキストを検索に適したチャンクに分割する。

    1. YAMLフロントマターを除去
    2. MarkdownHeaderTextSplitter で H1/H2/H3 単位にセクション分割
    3. 各セクションをテーブル（JSON変換）と本文（段落単位）に分離してチャンク化
    4. 各チャンク先頭にセクション名パンくずを付加
    """
    body = _strip_frontmatter(text)

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
        strip_headers=True,
    )
    sections = header_splitter.split_text(body)

    result: list[str] = []
    for doc in sections:
        result.extend(_chunk_section(doc.page_content, chunk_size, _make_breadcrumb(doc.metadata)))

    return result


def _merge_short_chunks(chunks: list[str], min_size: int) -> list[str]:
    """Merge chunks shorter than min_size into the preceding chunk.

    Table JSON rows (starting with '{') are never merged — they are
    self-contained structured records that should stay independent.
    """
    if not chunks:
        return chunks
    merged: list[str] = []
    buf = chunks[0]
    for chunk in chunks[1:]:
        is_json_row = chunk.lstrip().startswith("{")
        buf_is_json = buf.lstrip().startswith("{")
        if len(buf) < min_size and not buf_is_json and not is_json_row:
            buf = buf + "\n\n" + chunk
        else:
            merged.append(buf)
            buf = chunk
    merged.append(buf)
    return merged


def _split_plain_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """プレーンテキストを段落・文境界を優先して分割する。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "．", ". ", " ", ""],
    )
    chunks = splitter.split_text(text.strip())
    return _merge_short_chunks(chunks, MIN_CHUNK_SIZE)


def _split_text(
    text: str,
    filename: str | None = None,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """ファイル種別に応じて適切な分割処理を選択するディスパッチャー。

    拡張子が .md / .markdown またはファイル名不明の場合は Markdown フローを使用する。
    それ以外のテキストファイルはプレーンテキスト分割を使用する。
    """
    ext = Path(filename).suffix.lower() if filename else ""
    if ext in _MARKDOWN_EXTENSIONS or not ext:
        return _split_markdown(text, chunk_size)
    return _split_plain_text(text, chunk_size, chunk_overlap)


# --- Background ingest processing ---
def process_ingest(text: str, filename: str | None = None):
    if vectorstore is None:
        print("Ingest skipped: vectorstore is not initialized.")
        return
    chunks = _split_text(text, filename)
    for i, chunk in enumerate(chunks):
        print(f"[chunk {i}] len={len(chunk)} | {chunk[:120].replace(chr(10), r'\n')}")
    docs = [Document(page_content=chunk) for chunk in chunks]
    # Add to the already-loaded instance
    vectorstore.add_documents(docs)
    print(f"Background Ingest: {len(docs)} chunks added.")


# --- Endpoints ---


@app.get("/debug/search")
async def debug_search(q: str, k: int = 5):
    """Return raw retrieved chunks for a query without invoking the LLM."""
    if vectorstore is None:
        raise HTTPException(status_code=503, detail="DB is not ready.")
    docs = vectorstore.similarity_search(q, k=k)
    return {"query": q, "chunks": [{"content": d.page_content, "metadata": d.metadata} for d in docs]}


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
    background_tasks.add_task(process_ingest, text, file.filename)
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
