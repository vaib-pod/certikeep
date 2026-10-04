from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: int
    name: str
    email: str

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    original_name: str
    mime_type: str
    uploaded_at: datetime
    ai_indexed: bool

class SearchResult(DocumentOut):
    score: float
    snippet: str

class ChatRequest(BaseModel):
    question: str

class ChatSource(BaseModel):
    document_id: int
    title: str
    filename: str
    source_label: str
    snippet: str
    score: float

class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
