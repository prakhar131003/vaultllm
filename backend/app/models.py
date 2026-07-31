from pydantic import BaseModel
from typing import Optional


class DocumentOut(BaseModel):
    id: int
    title: str
    source: str | None = None
    created_at: str
    chunk_count: int = 0


class QueryIn(BaseModel):
    query: str
    top_k: int = 5
    conversation_id: int | None = None


class SourceItem(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    content: str
    score: float


class QueryOut(BaseModel):
    answer: str
    sources: list[SourceItem]
    processing_time_ms: int


class HealthOut(BaseModel):
    status: str
    llm_server: bool
    database: bool


# ── Conversations ─────────────────────────────────────────────

class ConversationOut(BaseModel):
    id: int
    title: str
    parent_conversation_id: int | None = None
    branch_point_message_id: int | None = None
    created_at: str
    updated_at: str
    child_count: int = 0


class ConversationCreate(BaseModel):
    title: str = "New Chat"
    parent_conversation_id: int | None = None
    branch_point_message_id: int | None = None


class ConversationUpdate(BaseModel):
    title: str


# ── Messages ──────────────────────────────────────────────────

class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    sources: str | None = None
    processing_time_ms: int = 0
    created_at: str
