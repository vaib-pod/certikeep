import os
import re
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import cohere
from google import genai
from groq import Groq

from .extraction import chunk_text, extract_segments
from .supabase_client import SUPABASE_STORAGE_BUCKET, require_supabase

# -----------------------------
# Provider configuration
# -----------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
FALLBACK_CHAT_MODEL = os.getenv("GEMINI_FALLBACK_CHAT_MODEL", "gemini-3.5-flash-lite")

COHERE_API_KEY = os.getenv("COHERE_API_KEY")
COHERE_INDEX_MODEL = os.getenv(
    "COHERE_INDEX_MODEL",
    os.getenv("COHERE_EMBED_MODEL", "embed-v5.0-pro"),
)
COHERE_QUERY_MODEL = os.getenv("COHERE_QUERY_MODEL", "embed-v5.0-fast")
EMBEDDING_DIMENSIONS = 768
COHERE_BATCH_SIZE = 96

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")

# qwen3.6 was retired on Groq developer/free tiers. Automatically move an old
# environment value to its direct successor so an older .env does not break OCR.
if GROQ_VISION_MODEL == "qwen/qwen3.6-27b":
    print("GROQ_VISION_MODEL qwen3.6 is deprecated; using qwen/qwen3.8-27b instead.")
    GROQ_VISION_MODEL = "qwen/qwen3.8-27b"


gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
cohere_client = cohere.ClientV2(api_key=COHERE_API_KEY) if COHERE_API_KEY else None
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def require_cohere():
    if not cohere_client:
        raise RuntimeError("COHERE_API_KEY is not configured in the backend environment")
    return cohere_client


def require_groq():
    if not groq_client:
        raise RuntimeError("GROQ_API_KEY is not configured in the backend environment")
    return groq_client


def _cohere_float_embeddings(response) -> list[list[float]]:
    """Handle Cohere SDK float embedding attribute naming across SDK versions."""
    embeddings = response.embeddings
    values = getattr(embeddings, "float", None)
    if values is None:
        values = getattr(embeddings, "float_", None)
    if values is None:
        raise RuntimeError("Cohere did not return float embeddings")
    return [list(vector) for vector in values]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-index document chunks with Cohere Embed 5 in 768 dimensions."""
    if not texts:
        return []

    client = require_cohere()
    vectors: list[list[float]] = []

    for start in range(0, len(texts), COHERE_BATCH_SIZE):
        batch = texts[start : start + COHERE_BATCH_SIZE]
        response = client.embed(
            model=COHERE_INDEX_MODEL,
            texts=batch,
            input_type="search_document",
            embedding_types=["float"],
            output_dimension=EMBEDDING_DIMENSIONS,
        )
        batch_vectors = _cohere_float_embeddings(response)

        if len(batch_vectors) != len(batch):
            raise RuntimeError("Cohere returned an unexpected number of embeddings")
        if any(len(vector) != EMBEDDING_DIMENSIONS for vector in batch_vectors):
            raise RuntimeError("Cohere returned an unexpected embedding dimension")

        vectors.extend(batch_vectors)

    return vectors


def embed_query(text: str) -> list[float]:
    """Create a query embedding in the same shared Embed 5 vector space."""
    client = require_cohere()
    response = client.embed(
        model=COHERE_QUERY_MODEL,
        texts=[text],
        input_type="search_query",
        embedding_types=["float"],
        output_dimension=EMBEDDING_DIMENSIONS,
    )
    vectors = _cohere_float_embeddings(response)
    if not vectors or len(vectors[0]) != EMBEDDING_DIMENSIONS:
        raise RuntimeError("Cohere returned an invalid query embedding")
    return vectors[0]


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
    """Provider-independent fallback that searches document metadata/text."""
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


def _is_transient_ai_error(exc: Exception) -> bool:
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
        "CONNECTION",
    )
    return any(marker in text for marker in transient_markers)


def _generate_with_gemini(prompt: str) -> str:
    if not gemini_client:
        raise RuntimeError("Gemini is not configured")

    models: list[str] = []
    for model in (CHAT_MODEL, FALLBACK_CHAT_MODEL):
        if model and model not in models:
            models.append(model)

    last_error: Exception | None = None
    for model in models:
        for attempt in range(2):
            try:
                print(f"Trying Gemini chat: {model} (attempt {attempt + 1}/2)")
                response = gemini_client.models.generate_content(model=model, contents=prompt)
                answer = (response.text or "").strip()
                if answer:
                    print(f"Gemini chat success: {model}")
                    return answer
                last_error = RuntimeError(f"Gemini model {model} returned an empty response")
            except Exception as exc:
                last_error = exc
                print(f"Gemini chat failed: {type(exc).__name__}: {exc}")
                if _is_transient_ai_error(exc) and attempt == 0:
                    time.sleep(1.25)
                    continue
                break

    raise last_error or RuntimeError("All Gemini chat models failed")


def _generate_with_groq(prompt: str) -> str:
    client = require_groq()
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            print(f"Trying Groq chat fallback: {GROQ_CHAT_MODEL} (attempt {attempt + 1}/2)")
            response = client.chat.completions.create(
                model=GROQ_CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=1400,
            )
            answer = (response.choices[0].message.content or "").strip()
            if answer:
                print(f"Groq chat success: {GROQ_CHAT_MODEL}")
                return answer
            last_error = RuntimeError("Groq returned an empty response")
        except Exception as exc:
            last_error = exc
            print(f"Groq chat failed: {type(exc).__name__}: {exc}")
            if _is_transient_ai_error(exc) and attempt == 0:
                time.sleep(1.0)
                continue
            break

    raise last_error or RuntimeError("Groq chat failed")


def generate_with_fallback(prompt: str) -> str:
    """Use Gemini first for Q&A, then automatically fall back to Groq."""
    errors: list[str] = []

    if gemini_client:
        try:
            return _generate_with_gemini(prompt)
        except Exception as exc:
            errors.append(f"Gemini: {exc}")
            print("Gemini unavailable; switching Ask CertiKeep to Groq.")

    if groq_client:
        try:
            return _generate_with_groq(prompt)
        except Exception as exc:
            errors.append(f"Groq: {exc}")

    raise RuntimeError("No AI chat provider succeeded. " + " | ".join(errors))


def index_document(document_id: str, user_id: str, raise_errors: bool = False) -> bool:
    """Download a private file, extract/OCR it, create Cohere vectors, and save them."""
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

        segments = extract_segments(
            temp_path,
            vision_client=groq_client,
            vision_model=GROQ_VISION_MODEL,
        )
        if not segments:
            raise ValueError("No readable text could be extracted from this document.")

        chunk_records: list[tuple[str, str]] = []
        for source_label, segment_text in segments:
            for chunk in chunk_text(segment_text):
                chunk_records.append((source_label, chunk))

        if not chunk_records:
            raise ValueError("No readable text could be indexed from this document.")

        # Cohere accepts batches, so long documents no longer make one embedding
        # API request per chunk.
        embeddings = embed_texts([chunk for _, chunk in chunk_records])
        extracted_text = "\n\n".join(segment_text for _, segment_text in segments)

        # Only replace the previous index once the new index is fully ready.
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
            # Keep database requests reasonably sized for long documents.
            for start in range(0, len(chunk_rows), 100):
                supabase.table("document_chunks").insert(
                    chunk_rows[start : start + 100]
                ).execute()

        (
            supabase.table("documents")
            .update({"extracted_text": extracted_text, "ai_indexed": True})
            .eq("id", document_id)
            .eq("user_id", user_id)
            .execute()
        )

        print(
            f"AI indexing completed for {document_id}: "
            f"{len(segments)} segments, {len(chunk_rows)} chunks"
        )
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
