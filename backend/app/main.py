import time
import json
import logging
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import database as db
from . import models

logger = logging.getLogger(__name__)

LLAMA_URL = "http://127.0.0.1:8080"
EMBEDDING_DIM = 2048
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

app = FastAPI(title="RAG Knowledge Base")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_llm_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup():
    db.init_db(EMBEDDING_DIM)
    global _llm_client
    _llm_client = httpx.AsyncClient(base_url=LLAMA_URL, timeout=120.0)
    Path("data/uploads").mkdir(parents=True, exist_ok=True)


@app.on_event("shutdown")
async def shutdown():
    if _llm_client:
        await _llm_client.aclose()


async def embed(texts: list[str]) -> list[list[float]]:
    resp = await _llm_client.post("/v1/embeddings", json={"input": texts, "model": "default"})
    resp.raise_for_status()
    data = resp.json()
    return [item["embedding"] for item in data["data"]]


async def generate(system: str, user: str) -> str:
    resp = await _llm_client.post("/v1/chat/completions", json={
        "model": "default",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": 0.2,
        "max_tokens": 1024
    })
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def chunk_markdown(text: str) -> list[str]:
    HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    MAX_WORDS = CHUNK_SIZE
    OVERLAP_WORDS = CHUNK_OVERLAP

    def word_count(s: str) -> int:
        return len(s.split())

    def split_by_words(s: str, max_w: int = MAX_WORDS, overlap_w: int = OVERLAP_WORDS) -> list[str]:
        words = s.split()
        if len(words) <= max_w:
            return [s]
        parts = []
        start = 0
        while start < len(words):
            end = start + max_w
            parts.append(" ".join(words[start:end]))
            start += max_w - overlap_w
            if start >= len(words):
                break
        return parts

    headings = list(HEADING_RE.finditer(text))
    if not headings:
        parts = re.split(r'\n\s*\n', text.strip())
        result = []
        buffer = []
        buf_words = 0
        for p in parts:
            pw = word_count(p)
            if buf_words + pw <= MAX_WORDS:
                buffer.append(p)
                buf_words += pw
            else:
                if buffer:
                    result.append("\n\n".join(buffer))
                buffer = [p]
                buf_words = pw
        if buffer:
            result.append("\n\n".join(buffer))
        flat = []
        for r in result:
            flat.extend(split_by_words(r))
        return flat if flat else [text.strip()]

    sections = []
    for i, m in enumerate(headings):
        start = m.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section = text[start:end].strip()
        sections.append(section)

    merged = []
    for s in sections:
        if merged and word_count(merged[-1]) + word_count(s) <= MAX_WORDS:
            merged[-1] = merged[-1] + "\n\n" + s
        else:
            merged.append(s)

    result = []
    for s in merged:
        if word_count(s) <= MAX_WORDS:
            result.append(s)
        else:
            result.extend(split_by_words(s))

    return result if result else [text.strip()]


def chunk_text(text: str) -> list[str]:
    return chunk_markdown(text)


@app.get("/api/health", response_model=models.HealthOut)
async def health():
    llm_ok = False
    try:
        r = await _llm_client.get("/v1/models")
        llm_ok = r.status_code == 200
    except Exception:
        pass
    db_ok = True
    try:
        conn = db.get_db()
        conn.execute("SELECT 1")
        conn.close()
    except Exception:
        db_ok = False
    return models.HealthOut(
        status="ok" if (llm_ok and db_ok) else "error",
        llm_server=llm_ok,
        database=db_ok
    )


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    raw = await file.read()
    title = Path(file.filename).stem
    ext = Path(file.filename).suffix.lower()

    save_path = f"data/uploads/{file.filename}"
    Path(save_path).write_bytes(raw)

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(raw))
            content = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise HTTPException(400, "PDF parsing requires pypdf: pip install pypdf")
    else:
        content = raw.decode("utf-8", errors="replace")

    chunks = chunk_text(content)

    try:
        embeddings = await embed(chunks)
    except Exception as e:
        raise HTTPException(502, f"Embedding failed: {e}")

    conn = db.get_db()
    try:
        doc_id = db.insert_doc(conn, title, file.filename)
        db.insert_chunks(conn, doc_id, chunks, embeddings)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB error: {e}")
    finally:
        conn.close()

    return {"id": doc_id, "title": title, "chunks": len(chunks)}


@app.get("/api/documents")
async def list_documents():
    conn = db.get_db()
    try:
        docs = db.list_docs(conn)
        return {"documents": docs}
    finally:
        conn.close()


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: int):
    conn = db.get_db()
    try:
        chunks = db.get_chunks(conn, doc_id)
        return {"chunks": chunks}
    finally:
        conn.close()


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: int):
    conn = db.get_db()
    try:
        db.delete_doc(conn, doc_id)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()
    return {"ok": True}


# ── Conversations ────────────────────────────────────────────


@app.get("/api/conversations")
async def list_conversations():
    conn = db.get_db()
    try:
        convs = db.list_conversations(conn)
        return {"conversations": convs}
    finally:
        conn.close()


@app.post("/api/conversations")
async def create_conversation(body: models.ConversationCreate):
    conn = db.get_db()
    try:
        if body.parent_conversation_id is not None and body.branch_point_message_id is not None:
            parent_msgs = db.get_messages(conn, body.parent_conversation_id)
            branch_idx = None
            for i, m in enumerate(parent_msgs):
                if m["id"] == body.branch_point_message_id:
                    branch_idx = i
                    break
            if branch_idx is None:
                raise HTTPException(404, "Branch point message not found in parent conversation")

        conv_id = db.create_conversation(
            conn, title=body.title,
            parent_id=body.parent_conversation_id,
            branch_msg_id=body.branch_point_message_id
        )

        if body.parent_conversation_id is not None and body.branch_point_message_id is not None:
            parent_msgs = db.get_messages(conn, body.parent_conversation_id)
            for m in parent_msgs:
                if m["id"] == body.branch_point_message_id:
                    db.insert_message(conn, conv_id, m["role"], m["content"], m["sources"], m["processing_time_ms"])
                    break
                db.insert_message(conn, conv_id, m["role"], m["content"], m["sources"], m["processing_time_ms"])

        conn.commit()
        conv = db.get_conversation(conn, conv_id)
        return conv
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: int):
    conn = db.get_db()
    try:
        conv = db.get_conversation(conn, conv_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        return conv
    finally:
        conn.close()


@app.patch("/api/conversations/{conv_id}")
async def update_conversation(conv_id: int, body: models.ConversationUpdate):
    conn = db.get_db()
    try:
        conv = db.get_conversation(conn, conv_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        db.update_conversation_title(conn, conv_id, body.title)
        conn.commit()
        conv = db.get_conversation(conn, conv_id)
        return conv
    finally:
        conn.close()


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: int):
    conn = db.get_db()
    try:
        conv = db.get_conversation(conn, conv_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        db.delete_conversation(conn, conv_id)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ── Messages ─────────────────────────────────────────────────


@app.get("/api/conversations/{conv_id}/messages")
async def list_messages(conv_id: int):
    conn = db.get_db()
    try:
        conv = db.get_conversation(conn, conv_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        msgs = db.get_messages(conn, conv_id)
        return {"messages": msgs}
    finally:
        conn.close()


@app.post("/api/query/stream")
async def query_stream(q: models.QueryIn):
    t0 = time.time()

    # Persist user message if conversation_id is given
    user_msg_id = None
    if q.conversation_id is not None:
        conn_msg = db.get_db()
        try:
            conv = db.get_conversation(conn_msg, q.conversation_id)
            if conv is None:
                raise HTTPException(404, "Conversation not found")
            user_msg_id = db.insert_message(conn_msg, q.conversation_id, "user", q.query)
            if conv["title"] == "New Chat":
                new_title = q.query[:60] + ("..." if len(q.query) > 60 else "")
                db.update_conversation_title(conn_msg, q.conversation_id, new_title)
            conn_msg.commit()
        except HTTPException:
            conn_msg.close()
            raise
        except Exception as e:
            conn_msg.rollback()
            conn_msg.close()
            raise HTTPException(500, str(e))
        conn_msg.close()

    try:
        [query_vec] = await embed([q.query])
    except Exception as e:
        raise HTTPException(502, f"Query embedding failed: {e}")

    conn = db.get_db()
    try:
        results = db.search_similar(conn, query_vec, q.top_k)
    finally:
        conn.close()

    if not results:
        async def no_results():
            answer = "No relevant documents found."
            yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"
            elapsed = int((time.time() - t0) * 1000)
            yield f"data: {json.dumps({'type': 'done', 'sources': [], 'processing_time_ms': elapsed})}\n\n"
            if q.conversation_id is not None:
                conn2 = db.get_db()
                try:
                    db.insert_message(conn2, q.conversation_id, "assistant", answer,
                                      sources=None, processing_time_ms=elapsed)
                    conn2.commit()
                finally:
                    conn2.close()
        return StreamingResponse(no_results(), media_type="text/event-stream")

    context = "\n\n".join(f"Source {i+1}: {r['content']}" for i, r in enumerate(results))
    system_prompt = "You are a helpful assistant. Answer the question using only the provided context. If the answer isn't in the context, say so."
    user_prompt = f"Context:\n{context}\n\nQuestion: {q.query}"

    async def stream():
        full_answer = ""
        async with httpx.AsyncClient(base_url=LLAMA_URL, timeout=120.0) as client:
            async with client.stream("POST", "/v1/chat/completions", json={
                "model": "default",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": True
            }) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(payload)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_answer += content
                                yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
                        except json.JSONDecodeError:
                            continue

        elapsed = int((time.time() - t0) * 1000)
        sources_data = [{'chunk_id': r['chunk_id'], 'document_id': r['document_id'], 'document_title': r['document_title'], 'content': r['content'][:300], 'score': r['score']} for r in results]
        yield f"data: {json.dumps({'type': 'done', 'sources': sources_data, 'processing_time_ms': elapsed})}\n\n"

        if q.conversation_id is not None:
            conn2 = db.get_db()
            try:
                db.insert_message(conn2, q.conversation_id, "assistant", full_answer,
                                  sources=json.dumps(sources_data), processing_time_ms=elapsed)
                conn2.commit()
            finally:
                conn2.close()

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/query", response_model=models.QueryOut)
async def query_documents(q: models.QueryIn):
    t0 = time.time()

    try:
        [query_vec] = await embed([q.query])
    except Exception as e:
        raise HTTPException(502, f"Query embedding failed: {e}")

    conn = db.get_db()
    try:
        results = db.search_similar(conn, query_vec, q.top_k)
    finally:
        conn.close()

    if not results:
        return models.QueryOut(
            answer="No relevant documents found.",
            sources=[],
            processing_time_ms=int((time.time() - t0) * 1000)
        )

    context = "\n\n".join(f"Source {i+1}: {r['content']}" for i, r in enumerate(results))
    system_prompt = "You are a helpful assistant. Answer the question using only the provided context. If the answer isn't in the context, say so."
    user_prompt = f"Context:\n{context}\n\nQuestion: {q.query}"

    try:
        answer = await generate(system_prompt, user_prompt)
    except Exception as e:
        raise HTTPException(502, f"LLM generation failed: {e}")

    return models.QueryOut(
        answer=answer.strip(),
        sources=[models.SourceItem(**r) for r in results],
        processing_time_ms=int((time.time() - t0) * 1000)
    )
