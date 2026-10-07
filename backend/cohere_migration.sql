-- CertiKeep: one-time migration when switching embeddings from Gemini to Cohere.
-- Existing Gemini vectors cannot be compared with Cohere query vectors, even though
-- both are 768-dimensional. Clear the old vector index and re-index documents.

alter table public.document_chunks
add column if not exists source_label text default 'Document';

-- Rebuild the RPC so source labels are available to Ask CertiKeep citations.
drop function if exists public.match_document_chunks(vector, uuid, integer);

create function public.match_document_chunks(
    query_embedding vector(768),
    match_user_id uuid,
    match_count int default 5
)
returns table (
    id bigint,
    document_id uuid,
    content text,
    source_label text,
    similarity float
)
language sql
stable
as $$
    select
        dc.id,
        dc.document_id,
        dc.content,
        coalesce(dc.source_label, 'Document') as source_label,
        1 - (dc.embedding <=> query_embedding) as similarity
    from public.document_chunks dc
    where dc.user_id = match_user_id
      and dc.embedding is not null
    order by dc.embedding <=> query_embedding
    limit match_count;
$$;

-- HNSW keeps vector retrieval fast as the chunk table grows.
create index if not exists document_chunks_embedding_hnsw_idx
on public.document_chunks
using hnsw (embedding vector_cosine_ops);

-- IMPORTANT: embeddings from different model families are not compatible.
delete from public.document_chunks;
update public.documents set ai_indexed = false;
