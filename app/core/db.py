from functools import lru_cache

from .config import get_settings


@lru_cache
def get_supabase():
    """Returns a Supabase client, or None when not configured (dev/in-memory mode)."""
    s = get_settings()
    if not (s.supabase_url and s.supabase_service_key):
        return None
    from supabase import create_client

    return create_client(s.supabase_url, s.supabase_service_key)
