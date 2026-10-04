import json
import math
import os
import re
import time
from collections import defaultdict

from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from .models import Document, DocumentChunk

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
FALLBACK_CHAT_MODEL = os.getenv("GEMINI_FALLBACK_CHAT_MODEL", "gemini-3.5-flash-lite")
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def require_client():
    if not client:
        raise RuntimeError("GEMINI_API_KEY is not configured in backend/.env")
    return client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Create one embedding per input string using Gemini."""
    if not texts:
        return []
    c = require_client()
    vectors: list[list[float]] = []
    for text in texts:
        response = c.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        vectors.append(list(response.embeddings[0].values))
    return vectors


def embed_query(text: str) -> list[float]:
    c = require_client()
    response = c.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return list(response.embeddings[0].values)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search_chunks(db: Session, user_id: int, query: str, limit: int = 8):
    query_vec = embed_query(query)
    rows = (
        db.query(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(Document.user_id == user_id)
        .all()
    )
    scored = []
    for chunk, doc in rows:
        vector = json.loads(chunk.embedding_json)
        score = cosine_similarity(query_vec, vector)
        scored.append((score, chunk, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:limit]


def search_documents(db: Session, user_id: int, query: str, limit: int = 8):
    chunk_hits = search_chunks(db, user_id, query, limit=max(limit * 4, 20))
    by_doc = defaultdict(list)
    for score, chunk, doc in chunk_hits:
        by_doc[doc.id].append((score, chunk, doc))
    results = []
    for entries in by_doc.values():
        entries.sort(key=lambda x: x[0], reverse=True)
        score, chunk, doc = entries[0]
        results.append((score, chunk, doc))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:limit]


def keyword_search_documents(db: Session, user_id: int, query: str, limit: int = 8):
    """Quota-safe fallback search that needs no external AI service."""
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]
    docs = db.query(Document).filter(Document.user_id == user_id).all()
    results = []
    for doc in docs:
        haystack = f"{doc.title} {doc.category} {doc.original_name} {doc.extracted_text or ''}".lower()
        if not terms:
            score = 0.0
        else:
            matched = sum(1 for term in terms if term in haystack)
            score = matched / len(terms)
        if score > 0:
            snippet = (doc.extracted_text or doc.title or doc.original_name)[:300]
            results.append((score, snippet, doc))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:limit]


def _is_transient_gemini_error(exc: Exception) -> bool:
    text = str(exc).upper()
    transient_markers = (
        "503",
        "UNAVAILABLE",
        "HIGH DEMAND",
        "429",
        "RESOURCE_EXHAUSTED",
        "RATE LIMIT",
        "TIMEOUT",
        "DEADLINE_EXCEEDED",
    )
    return any(marker in text for marker in transient_markers)


def generate_with_fallback(prompt: str) -> str:
    """Try the primary Gemini model, retry transient failures, then use a fallback model."""
    c = require_client()

    models = []
    for model in (CHAT_MODEL, FALLBACK_CHAT_MODEL):
        if model and model not in models:
            models.append(model)

    last_error: Exception | None = None

    for model in models:
        for attempt in range(2):
            try:
                print(f"Trying Gemini model: {model} (attempt {attempt + 1}/2)")
                response = c.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                answer = (response.text or "").strip()
                if answer:
                    print(f"Gemini success: {model}")
                    return answer
                last_error = RuntimeError(f"Gemini model {model} returned an empty response")
            except Exception as exc:
                last_error = exc
                print(f"Gemini model {model} failed: {type(exc).__name__}: {exc}")

                if _is_transient_gemini_error(exc) and attempt == 0:
                    time.sleep(1.5)
                    continue
                break

    raise last_error or RuntimeError("All Gemini chat models failed")


def answer_question(db: Session, user_id: int, question: str):
    hits = search_chunks(db, user_id, question, limit=6)
    if not hits or hits[0][0] < 0.12:
        return "I couldn't find enough relevant information in your uploaded documents to answer confidently.", []

    # Keep the strongest context, but allow multiple documents when a question genuinely needs them.
    # The displayed source list is filtered later to only documents actually cited in the answer.
    top_score = hits[0][0]
    relevance_floor = max(0.12, top_score * 0.72)
    relevant_hits = [hit for hit in hits if hit[0] >= relevance_floor][:6]
    if not relevant_hits:
        relevant_hits = hits[:1]

    context_parts = []
    source_lookup = {}

    for i, (score, chunk, doc) in enumerate(relevant_hits, start=1):
        label = f"Source {i}"
        context_parts.append(
            f"[{label}] Document: {doc.title} | File: {doc.original_name} | "
            f"Location: {chunk.source_label}\n{chunk.text}"
        )
        source_lookup[i] = {
            "document_id": doc.id,
            "title": doc.title,
            "filename": doc.original_name,
            "source_label": chunk.source_label,
            "snippet": chunk.text[:280],
            "score": round(score, 4),
        }

    prompt = f"""
You are CertiKeep, an assistant that answers questions ONLY from the user's uploaded documents.
Use the sources below. Do not invent facts.
If the sources disagree, explicitly say there is a conflict and state what each source says.
If the evidence is incomplete or unclear, say that you are uncertain.
Cite supporting evidence inline using [Source 1], [Source 2], etc.
IMPORTANT: Cite only the source or sources that directly support the answer. Do not cite unrelated documents merely because they were retrieved.
Keep the answer concise and practical.

QUESTION:
{question}

SOURCES:
{chr(10).join(context_parts)}
"""

    answer = generate_with_fallback(prompt)
    if not answer:
        answer = "I couldn't produce a reliable answer from the available document evidence."

    # Only expose documents that Gemini actually cited in its answer.
    cited_numbers = []
    for match in re.finditer(r"\[Source\s+(\d+)\]", answer, flags=re.IGNORECASE):
        number = int(match.group(1))
        if number in source_lookup and number not in cited_numbers:
            cited_numbers.append(number)

    # If a valid answer somehow contains no citation, use only the strongest retrieved document.
    if not cited_numbers:
        cited_numbers = [1]

    sources = []
    seen_documents = set()
    for number in cited_numbers:
        source = source_lookup[number]
        document_id = source["document_id"]
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        sources.append(source)

    return answer, sources
