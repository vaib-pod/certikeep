CertiKeep AI provider migration
===============================

New pipeline
------------
PDF native text -> PyMuPDF
Scanned PDF page / image -> Groq Vision
Embeddings -> Cohere Embed 5 (768 dimensions)
Ask CertiKeep -> Gemini primary -> Groq fallback
Vector store -> Supabase pgvector

Environment variables
---------------------
Required:
COHERE_API_KEY=...
GROQ_API_KEY=...

Recommended:
COHERE_EMBED_MODEL=embed-v5.0-pro
COHERE_QUERY_MODEL=embed-v5.0-fast
GROQ_VISION_MODEL=qwen/qwen3.8-27b
GROQ_CHAT_MODEL=openai/gpt-oss-120b

Keep the existing Gemini variables for primary Q&A.

IMPORTANT
---------
If GROQ_VISION_MODEL is still qwen/qwen3.6-27b, change it to
qwen/qwen3.8-27b. The code also automatically upgrades that exact old value.

Run cohere_migration.sql ONCE in Supabase SQL Editor. It clears only the old
vector chunks, not uploaded files or document metadata. Existing documents will
show AI indexing pending and can be re-indexed with Retry AI.

After local testing, add the same Cohere/Groq environment variables to Render
and redeploy the backend.
