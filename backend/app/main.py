import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .ai import answer_question, index_document, keyword_search_documents, search_documents
from .auth import CurrentUser, get_current_user
from .schemas import ChatRequest, ChatResponse, DocumentOut, SearchResult, UserOut
from .supabase_client import SUPABASE_STORAGE_BUCKET, require_supabase

app = FastAPI(title="CertiKeep API", version="0.2.0")

origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024


def _owned_document(document_id: str, user_id: str) -> dict:
    supabase = require_supabase()
    response = (
        supabase.table("documents")
        .select("*")
        .eq("id", document_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(404, "Document not found")
    return rows[0]


@app.get("/health")
def health():
    return {"status": "ok", "storage": "supabase"}


@app.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser = Depends(get_current_user)):
    return {"id": user.id, "name": user.name, "email": user.email}


@app.get("/documents", response_model=list[DocumentOut])
def list_documents(user: CurrentUser = Depends(get_current_user)):
    supabase = require_supabase()
    response = (
        supabase.table("documents")
        .select("id,title,category,original_name,mime_type,uploaded_at,ai_indexed")
        .eq("user_id", user.id)
        .order("uploaded_at", desc=True)
        .execute()
    )
    return response.data or []


@app.post("/documents", response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    category: str = Form("Other Docs"),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    supabase = require_supabase()

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, "Unsupported file type")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, "Maximum file size is 10 MB")

    document_id = str(uuid.uuid4())
    storage_path = f"{user.id}/{document_id}{suffix}"
    mime_type = file.content_type or "application/octet-stream"

    try:
        supabase.storage.from_(SUPABASE_STORAGE_BUCKET).upload(
            path=storage_path,
            file=data,
            file_options={
                "content-type": mime_type,
                "upsert": "false",
            },
        )
    except Exception as exc:
        print(f"Supabase storage upload failed: {type(exc).__name__}: {exc}")
        raise HTTPException(503, "Could not store the document in Supabase Storage")

    row = {
        "id": document_id,
        "user_id": user.id,
        "title": title.strip() or file.filename or "Untitled document",
        "category": category,
        "original_name": file.filename or f"document{suffix}",
        "mime_type": mime_type,
        "storage_path": storage_path,
        "extracted_text": "",
        "ai_indexed": False,
    }

    try:
        response = supabase.table("documents").insert(row).execute()
        inserted = (response.data or [row])[0]
    except Exception as exc:
        print(f"Supabase document insert failed: {type(exc).__name__}: {exc}")
        try:
            supabase.storage.from_(SUPABASE_STORAGE_BUCKET).remove([storage_path])
        except Exception:
            pass
        raise HTTPException(503, "Could not save document metadata")

    # Return immediately after durable storage. Gemini indexing continues after
    # the response so uploads do not feel blocked by AI latency/quota.
    background_tasks.add_task(index_document, document_id, user.id, False)
    return inserted


@app.post("/documents/{document_id}/reindex", response_model=DocumentOut)
def reindex_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    _owned_document(document_id, user.id)

    try:
        index_document(document_id, user.id, raise_errors=True)
    except Exception as exc:
        raise HTTPException(503, f"Gemini indexing is currently unavailable: {exc}")

    return _owned_document(document_id, user.id)


@app.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(..., min_length=2),
    limit: int = Query(8, ge=1, le=20),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        hits = search_documents(user.id, q, limit)
        return [
            {
                "id": str(doc["id"]),
                "title": doc["title"],
                "category": doc["category"],
                "original_name": doc["original_name"],
                "mime_type": doc.get("mime_type"),
                "uploaded_at": doc["uploaded_at"],
                "ai_indexed": bool(doc.get("ai_indexed")),
                "score": round(score, 4),
                "snippet": chunk["content"][:300],
            }
            for score, chunk, doc in hits
        ]
    except Exception as exc:
        print(f"Gemini/vector search unavailable; using keyword fallback: {exc}")
        fallback = keyword_search_documents(user.id, q, limit)
        return [
            {
                "id": str(doc["id"]),
                "title": doc["title"],
                "category": doc["category"],
                "original_name": doc["original_name"],
                "mime_type": doc.get("mime_type"),
                "uploaded_at": doc["uploaded_at"],
                "ai_indexed": bool(doc.get("ai_indexed")),
                "score": round(score, 4),
                "snippet": snippet,
            }
            for score, snippet, doc in fallback
        ]


@app.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
):
    try:
        answer, sources = answer_question(user.id, payload.question)
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
def get_document_file(
    document_id: str,
    download: bool = False,
    user: CurrentUser = Depends(get_current_user),
):
    supabase = require_supabase()
    doc = _owned_document(document_id, user.id)

    try:
        file_bytes = supabase.storage.from_(SUPABASE_STORAGE_BUCKET).download(doc["storage_path"])
    except Exception as exc:
        print(f"Supabase storage download failed: {type(exc).__name__}: {exc}")
        raise HTTPException(404, "Stored file missing")

    disposition = "attachment" if download else "inline"
    safe_name = (doc.get("original_name") or "document").replace('"', "")

    return Response(
        content=file_bytes,
        media_type=doc.get("mime_type") or "application/octet-stream",
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )


@app.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    supabase = require_supabase()
    doc = _owned_document(document_id, user.id)

    try:
        supabase.storage.from_(SUPABASE_STORAGE_BUCKET).remove([doc["storage_path"]])
    except Exception as exc:
        print(f"Supabase storage delete warning: {type(exc).__name__}: {exc}")

    (
        supabase.table("documents")
        .delete()
        .eq("id", document_id)
        .eq("user_id", user.id)
        .execute()
    )

    return {"deleted": True}
