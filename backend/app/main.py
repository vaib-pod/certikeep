import json
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from .database import Base, engine, get_db
from .models import User, Document, DocumentChunk
from .schemas import RegisterRequest, LoginRequest, TokenResponse, UserOut, DocumentOut, SearchResult, ChatRequest, ChatResponse
from .auth import hash_password, verify_password, create_access_token, get_current_user
from .extraction import extract_segments, chunk_text
from .ai import (
    client as ai_client, CHAT_MODEL, embed_texts, search_documents,
    keyword_search_documents, answer_question
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CertiKeep API", version="0.1.0")
origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/auth/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if len(payload.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    exists = db.scalar(select(User).where(User.email == payload.email.lower()))
    if exists:
        raise HTTPException(409, "Email already registered")
    user = User(name=payload.name.strip(), email=payload.email.lower(), password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}

@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}

@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "name": user.name, "email": user.email}

@app.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.uploaded_at.desc())).all()

@app.post("/documents", response_model=DocumentOut)
async def upload_document(
    title: str = Form(...),
    category: str = Form("Other Docs"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, "Unsupported file type")
    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, "Maximum file size is 10 MB")

    user_dir = UPLOAD_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    path = user_dir / stored_name
    path.write_bytes(data)

    # Always save the uploaded file first. AI indexing is best-effort so a
    # quota/network/model failure never causes the user's document to vanish.
    extracted_text = ""
    chunk_records = []
    embeddings = []
    try:
        segments = extract_segments(path, client=ai_client, vision_model=CHAT_MODEL)
        if segments:
            extracted_text = "\n\n".join(segment_text for _, segment_text in segments)
            for source_label, segment_text in segments:
                for chunk in chunk_text(segment_text):
                    chunk_records.append((source_label, chunk))
            if chunk_records:
                embeddings = embed_texts([chunk for _, chunk in chunk_records])
    except Exception as exc:
        # Intentionally keep the file. The UI will show it as "AI indexing pending".
        print(f"Gemini indexing skipped for {file.filename}: {exc}")

    doc = Document(
        user_id=user.id,
        title=title.strip() or file.filename,
        category=category,
        original_name=file.filename or stored_name,
        stored_name=stored_name,
        mime_type=file.content_type or "application/octet-stream",
        extracted_text=extracted_text,
    )
    db.add(doc)
    db.flush()
    for idx, ((source_label, chunk), vector) in enumerate(zip(chunk_records, embeddings)):
        db.add(DocumentChunk(document_id=doc.id, chunk_index=idx, source_label=source_label, text=chunk, embedding_json=json.dumps(vector)))
    db.commit()
    db.refresh(doc)
    return doc

@app.post("/documents/{document_id}/reindex", response_model=DocumentOut)
def reindex_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(404, "Document not found")
    path = UPLOAD_DIR / str(user.id) / doc.stored_name
    if not path.exists():
        raise HTTPException(404, "Stored file missing")

    try:
        segments = extract_segments(path, client=ai_client, vision_model=CHAT_MODEL)
        if not segments:
            raise ValueError("No readable text could be extracted from this document.")
        chunk_records = []
        for source_label, segment_text in segments:
            for chunk in chunk_text(segment_text):
                chunk_records.append((source_label, chunk))
        if not chunk_records:
            raise ValueError("No readable text could be indexed from this document.")
        embeddings = embed_texts([chunk for _, chunk in chunk_records])
    except Exception as exc:
        raise HTTPException(503, f"Gemini indexing is currently unavailable: {exc}")

    for chunk in list(doc.chunks):
        db.delete(chunk)
    doc.extracted_text = "\n\n".join(segment_text for _, segment_text in segments)
    db.flush()
    for idx, ((source_label, chunk), vector) in enumerate(zip(chunk_records, embeddings)):
        db.add(DocumentChunk(document_id=doc.id, chunk_index=idx, source_label=source_label, text=chunk, embedding_json=json.dumps(vector)))
    db.commit()
    db.refresh(doc)
    return doc

@app.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(..., min_length=2),
    limit: int = Query(8, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        hits = search_documents(db, user.id, q, limit)
        return [
            {
                "id": doc.id,
                "title": doc.title,
                "category": doc.category,
                "original_name": doc.original_name,
                "mime_type": doc.mime_type,
                "uploaded_at": doc.uploaded_at,
                "ai_indexed": doc.ai_indexed,
                "score": round(score, 4),
                "snippet": chunk.text[:300],
            }
            for score, chunk, doc in hits
        ]
    except Exception as exc:
        # Safeguard: if Gemini is unavailable/rate-limited, fall back to local keyword search.
        print(f"Gemini search unavailable; using local fallback: {exc}")
        fallback = keyword_search_documents(db, user.id, q, limit)
        return [
            {
                "id": doc.id,
                "title": doc.title,
                "category": doc.category,
                "original_name": doc.original_name,
                "mime_type": doc.mime_type,
                "uploaded_at": doc.uploaded_at,
                "ai_indexed": doc.ai_indexed,
                "score": round(score, 4),
                "snippet": snippet,
            }
            for score, snippet, doc in fallback
        ]

@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        answer, sources = answer_question(db, user.id, payload.question)
        return {"answer": answer, "sources": sources}
    except Exception as exc:
        print(f"Ask CertiKeep error: {type(exc).__name__}: {exc}")

    return {
        "answer": (
            "Ask CertiKeep is temporarily unavailable, "
            "but your uploaded documents are still safely stored."
        ),
        "sources": [],
    }

@app.get("/documents/{document_id}/file")
def get_document_file(document_id: int, download: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(404, "Document not found")
    path = UPLOAD_DIR / str(user.id) / doc.stored_name
    if not path.exists():
        raise HTTPException(404, "Stored file missing")
    disposition = "attachment" if download else "inline"
    return FileResponse(path, media_type=doc.mime_type, filename=doc.original_name, content_disposition_type=disposition)

@app.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(404, "Document not found")
    path = UPLOAD_DIR / str(user.id) / doc.stored_name
    path.unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    return {"deleted": True}
