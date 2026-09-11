import os
from typing import Optional
from supabase import create_async_client, AsyncClient

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_supabase_client: Optional[AsyncClient] = None

async def get_supabase() -> Optional[AsyncClient]:
    global _supabase_client
    if _supabase_client is None and SUPABASE_URL and SUPABASE_KEY:
        _supabase_client = await create_async_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client
