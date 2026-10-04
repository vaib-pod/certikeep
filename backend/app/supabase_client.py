import os

from supabase import Client, create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "certikeep-documents")

supabase_admin: Client | None = None
if SUPABASE_URL and SUPABASE_SECRET_KEY:
    supabase_admin = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


def require_supabase() -> Client:
    if not supabase_admin:
        raise RuntimeError(
            "Supabase backend is not configured. Add SUPABASE_URL and "
            "SUPABASE_SECRET_KEY to backend/.env."
        )
    return supabase_admin
