import sqlite3
import struct
import sqlite_vec
from pathlib import Path

DB_PATH = "data/knowledge.db"


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db(embedding_dim: int = 2048):
    db = get_db()
    db.executescript(f"""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            content TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            id INTEGER PRIMARY KEY,
            embedding float[{embedding_dim}]
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New Chat',
            parent_conversation_id INTEGER,
            branch_point_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            sources TEXT,
            processing_time_ms INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    db.commit()
    db.close()


def serialize(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def insert_doc(db: sqlite3.Connection, title: str, source: str) -> int:
    cur = db.execute("INSERT INTO documents (title, source) VALUES (?, ?)", (title, source))
    return cur.lastrowid


def insert_chunks(db: sqlite3.Connection, doc_id: int, chunks: list[str], embeddings: list[list[float]]):
    for i, (content, vec) in enumerate(zip(chunks, embeddings)):
        cur = db.execute("INSERT INTO chunks (document_id, content) VALUES (?, ?)", (doc_id, content))
        chunk_id = cur.lastrowid
        db.execute("INSERT INTO vec_chunks (id, embedding) VALUES (?, ?)", (chunk_id, serialize(vec)))


def search_similar(db: sqlite3.Connection, query_vec: list[float], top_k: int = 5) -> list[dict]:
    rows = db.execute("""
        SELECT v.id, v.distance, c.content, c.document_id, d.title
        FROM (
            SELECT id, distance FROM vec_chunks WHERE embedding MATCH ? AND k = ?
        ) v
        JOIN chunks c ON c.id = v.id
        JOIN documents d ON d.id = c.document_id
        ORDER BY v.distance
    """, (serialize(query_vec), top_k)).fetchall()
    return [
        {"chunk_id": r[0], "score": r[1], "content": r[2], "document_id": r[3], "document_title": r[4]}
        for r in rows
    ]


def list_docs(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute("""
        SELECT d.id, d.title, d.source, d.created_at, COUNT(c.id) as chunk_count
        FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        GROUP BY d.id
        ORDER BY d.created_at DESC
    """).fetchall()
    return [{"id": r[0], "title": r[1], "source": r[2], "created_at": r[3], "chunk_count": r[4]} for r in rows]


def get_chunks(db: sqlite3.Connection, doc_id: int) -> list[dict]:
    rows = db.execute("""
        SELECT c.id, c.content, c.document_id
        FROM chunks c
        WHERE c.document_id = ?
        ORDER BY c.id
    """, (doc_id,)).fetchall()
    return [{"id": r[0], "content": r[1], "document_id": r[2]} for r in rows]


def delete_doc(db: sqlite3.Connection, doc_id: int):
    db.execute("DELETE FROM vec_chunks WHERE id IN (SELECT id FROM chunks WHERE document_id=?)", (doc_id,))
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))


# ── Conversations ─────────────────────────────────────────────

def create_conversation(db: sqlite3.Connection, title: str = "New Chat",
                        parent_id: int | None = None,
                        branch_msg_id: int | None = None) -> int:
    cur = db.execute(
        "INSERT INTO conversations (title, parent_conversation_id, branch_point_message_id) VALUES (?, ?, ?)",
        (title, parent_id, branch_msg_id)
    )
    return cur.lastrowid


def list_conversations(db: sqlite3.Connection) -> list[dict]:
    children = db.execute("""
        SELECT parent_conversation_id, COUNT(*) as cnt
        FROM conversations
        WHERE parent_conversation_id IS NOT NULL
        GROUP BY parent_conversation_id
    """).fetchall()
    child_counts = {r[0]: r[1] for r in children}

    rows = db.execute("""
        SELECT id, title, parent_conversation_id, branch_point_message_id, created_at, updated_at
        FROM conversations
        ORDER BY updated_at DESC
    """).fetchall()
    result = []
    for r in rows:
        item = {
            "id": r[0], "title": r[1], "parent_conversation_id": r[2],
            "branch_point_message_id": r[3], "created_at": r[4], "updated_at": r[5],
            "child_count": child_counts.get(r[0], 0)
        }
        result.append(item)
    return result


def get_conversation(db: sqlite3.Connection, conv_id: int) -> dict | None:
    row = db.execute(
        "SELECT id, title, parent_conversation_id, branch_point_message_id, created_at, updated_at FROM conversations WHERE id=?",
        (conv_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "title": row[1], "parent_conversation_id": row[2],
        "branch_point_message_id": row[3], "created_at": row[4], "updated_at": row[5]
    }


def update_conversation_title(db: sqlite3.Connection, conv_id: int, title: str):
    db.execute(
        "UPDATE conversations SET title=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (title, conv_id)
    )


def delete_conversation(db: sqlite3.Connection, conv_id: int):
    db.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
    db.execute("DELETE FROM conversations WHERE id=?", (conv_id,))


# ── Messages ──────────────────────────────────────────────────

def insert_message(db: sqlite3.Connection, conversation_id: int, role: str,
                   content: str, sources: str | None = None,
                   processing_time_ms: int = 0) -> int:
    cur = db.execute(
        "INSERT INTO messages (conversation_id, role, content, sources, processing_time_ms) VALUES (?, ?, ?, ?, ?)",
        (conversation_id, role, content, sources, processing_time_ms)
    )
    return cur.lastrowid


def get_messages(db: sqlite3.Connection, conversation_id: int) -> list[dict]:
    rows = db.execute("""
        SELECT id, role, content, sources, processing_time_ms, created_at
        FROM messages
        WHERE conversation_id=?
        ORDER BY id
    """, (conversation_id,)).fetchall()
    return [
        {
            "id": r[0], "role": r[1], "content": r[2], "sources": r[3],
            "processing_time_ms": r[4], "created_at": r[5]
        }
        for r in rows
    ]
