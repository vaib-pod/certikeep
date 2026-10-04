from datetime import datetime
from pydantic import BaseModel


class UserOut(BaseModel):
    id: str
    name: str
    email: str


class DocumentOut(BaseModel):
    id: str
    title: str
    category: str
    original_name: str
    mime_type: str | None = None
    uploaded_at: datetime
    ai_indexed: bool = False


class SearchResult(DocumentOut):
    score: float
    snippet: str


class ChatRequest(BaseModel):
    question: str


class ChatSource(BaseModel):
    document_id: str
    title: str
    filename: str
    source_label: str
    snippet: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
