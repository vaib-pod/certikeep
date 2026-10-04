import math
import os
import re
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from google import genai
from google.genai import types

from .extraction import chunk_text, extract_segments
from .supabase_client import SUPABASE_STORAGE_BUCKET, require_supabase

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
FALLBACK_CHAT_MODEL = os.getenv("GEMINI_FALLBACK_CHAT_MODEL", "gemini-3.5-flash-lite")
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIMENSIONS = 768

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def require_client():
    if not client:
        raise RuntimeError("GEMINI_API_KEY is not configured in backend/.env")
    return client


def _normalize(vector: list[float]) -> list[float]:
    """Normalize truncated Gemini embeddings for stable cosine search."""
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return vector
    return [value / magnitude for value in vector]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Create one 768-dimensional embedding per document chunk."""
    if not texts:
        return []

    c = require_client()
    vectors: list[list[float]] = []
    for text in texts:
        response = c.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=EMBEDDING_DIMENSIONS,
            ),
        )
        vector = list(response.embeddings[0].values)
        vectors.append(_normalize(vector))
    return vectors


def embed_query(text: str) -> list[float]:
    c = require_client()
    response = c.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBEDDING_DIMENSIONS,
        ),
    )
    return _normalize(list(response.embeddings[0].values))


def _fetch_documents(user_id: str, document_ids: list[str] | None = None) -> list[dict]:
    supabase = require_supabase()
    query = supabase.table("documents").select("*").eq("user_id", user_id)
    if document_ids:
        query = query.in_("id", document_ids)
    response = query.execute()
    return response.data or []


def search_chunks(user_id: str, query: str, limit: int = 8):
    """Search Supabase pgvector chunks for one authenticated user."""
    supabase = require_supabase()
    query_vec = embed_query(query)

    rpc_response = supabase.rpc(
        "match_document_chunks",
        {
            "query_embedding": query_vec,
            "match_user_id": user_id,
            "match_count": limit,
        },
    ).execute()

    rows = rpc_response.data or []
    if not rows:
        return []

    document_ids = list(dict.fromkeys(str(row["document_id"]) for row in rows))
    documents = _fetch_documents(user_id, document_ids)
    doc_lookup = {str(doc["id"]): doc for doc in documents}

    hits = []
    for row in rows:
        document_id = str(row["document_id"])
        doc = doc_lookup.get(document_id)
        if not doc:
            continue
        chunk = {
            "id": row.get("id"),
            "document_id": document_id,
            "content": row.get("content") or "",
            "source_label": row.get("source_label") or "Document",
        }
        hits.append((float(row.get("similarity") or 0.0), chunk, doc))

    return hits


def search_documents(user_id: str, query: str, limit: int = 8):
    chunk_hits = search_chunks(user_id, query, limit=max(limit * 4, 20))
    by_doc = defaultdict(list)

    for score, chunk, doc in chunk_hits:
        by_doc[str(doc["id"])].append((score, chunk, doc))

    results = []
    for entries in by_doc.values():
        entries.sort(key=lambda item: item[0], reverse=True)
        results.append(entries[0])

    results.sort(key=lambda item: item[0], reverse=True)
    return results[:limit]


def keyword_search_documents(user_id: str, query: str, limit: int = 8):
    """Quota-safe fallback that searches Supabase document metadata/text."""
    terms = [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 1]
    docs = _fetch_documents(user_id)
    results = []

    for doc in docs:
        haystack = (
            f"{doc.get('title', '')} {doc.get('category', '')} "
            f"{doc.get('original_name', '')} {doc.get('extracted_text') or ''}"
        ).lower()

        matched = sum(1 for term in terms if term in haystack) if terms else 0
        score = matched / len(terms) if terms else 0.0
        if score > 0:
            snippet = (
                doc.get("extracted_text")
                or doc.get("title")
                or doc.get("original_name")
                or ""
            )[:300]
            results.append((score, snippet, doc))

    results.sort(key=lambda item: item[0], reverse=True)
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
                response = c.models.generate_content(model=model, contents=prompt)
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


def index_document(document_id: str, user_id: str, raise_errors: bool = False) -> bool:
    """Download a private Supabase file, extract text, embed chunks, and save them."""
    supabase = require_supabase()
    temp_path: Path | None = None

    try:
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
            raise ValueError("Document not found")

        doc = rows[0]
        storage_path = doc["storage_path"]
        file_bytes = supabase.storage.from_(SUPABASE_STORAGE_BUCKET).download(storage_path)

        suffix = Path(doc.get("original_name") or storage_path).suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(file_bytes)
            temp_path = Path(temp_file.name)

        segments = extract_segments(temp_path, client=client, vision_model=CHAT_MODEL)
        if not segments:
            raise ValueError("No readable text could be extracted from this document.")

        chunk_records: list[tuple[str, str]] = []
        for source_label, segment_text in segments:
            for chunk in chunk_text(segment_text):
                chunk_records.append((source_label, chunk))

        if not chunk_records:
            raise ValueError("No readable text could be indexed from this document.")

        embeddings = embed_texts([chunk for _, chunk in chunk_records])
        extracted_text = "\n\n".join(segment_text for _, segment_text in segments)

        # Only replace the previous index after the new embeddings are ready.
        (
            supabase.table("document_chunks")
            .delete()
            .eq("document_id", document_id)
            .eq("user_id", user_id)
            .execute()
        )

        chunk_rows = [
            {
                "document_id": document_id,
                "user_id": user_id,
                "chunk_index": index,
                "source_label": source_label,
                "content": content,
                "embedding": vector,
            }
            for index, ((source_label, content), vector) in enumerate(
                zip(chunk_records, embeddings)
            )
        ]

        if chunk_rows:
            supabase.table("document_chunks").insert(chunk_rows).execute()

        (
            supabase.table("documents")
            .update({"extracted_text": extracted_text, "ai_indexed": True})
            .eq("id", document_id)
            .eq("user_id", user_id)
            .execute()
        )

        print(f"AI indexing completed for document {document_id}")
        return True

    except Exception as exc:
        print(f"AI indexing failed for document {document_id}: {type(exc).__name__}: {exc}")
        try:
            (
                supabase.table("documents")
                .update({"ai_indexed": False})
                .eq("id", document_id)
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as update_exc:
            print(f"Could not update indexing status: {update_exc}")

        if raise_errors:
            raise
        return False

    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def answer_question(user_id: str, question: str):
    hits = search_chunks(user_id, question, limit=6)
    if not hits or hits[0][0] < 0.12:
        return (
            "I couldn't find enough relevant information in your uploaded documents to answer confidently.",
            [],
        )

    top_score = hits[0][0]
    relevance_floor = max(0.12, top_score * 0.72)
    relevant_hits = [hit for hit in hits if hit[0] >= relevance_floor][:6]
    if not relevant_hits:
        relevant_hits = hits[:1]

    context_parts = []
    source_lookup = {}

    for index, (score, chunk, doc) in enumerate(relevant_hits, start=1):
        label = f"Source {index}"
        context_parts.append(
            f"[{label}] Document: {doc['title']} | File: {doc['original_name']} | "
            f"Location: {chunk['source_label']}\n{chunk['content']}"
        )
        source_lookup[index] = {
            "document_id": str(doc["id"]),
            "title": doc["title"],
            "filename": doc["original_name"],
            "source_label": chunk["source_label"],
            "snippet": chunk["content"][:280],
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

    cited_numbers = []
    for match in re.finditer(r"\[Source\s+(\d+)\]", answer, flags=re.IGNORECASE):
        number = int(match.group(1))
        if number in source_lookup and number not in cited_numbers:
            cited_numbers.append(number)

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
