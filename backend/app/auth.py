from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from .supabase_client import require_supabase

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class CurrentUser:
    id: str
    email: str
    name: str


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """Validate the browser's Supabase access token and return the Supabase user."""
    try:
        supabase = require_supabase()
        response = supabase.auth.get_user(token)
        user = response.user
        if not user:
            raise _credentials_error()

        user_id = str(user.id)
        email = (user.email or "").strip().lower()
        metadata = user.user_metadata or {}
        name = (metadata.get("full_name") or metadata.get("name") or "").strip()

        # Prefer the profile table because that is now the canonical profile record.
        try:
            profile_response = (
                supabase.table("profiles")
                .select("full_name")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            rows = profile_response.data or []
            if rows and (rows[0].get("full_name") or "").strip():
                name = rows[0]["full_name"].strip()
        except Exception as exc:
            print(f"Profile lookup warning: {exc}")

        if not name:
            name = email.split("@", 1)[0] if email else "My profile"

        return CurrentUser(id=user_id, email=email, name=name)
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Supabase auth validation failed: {type(exc).__name__}: {exc}")
        raise _credentials_error()
