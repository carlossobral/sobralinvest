from supabase import create_client

from etl.config.settings import settings

supabase = create_client(
    settings.supabase_url,
    settings.supabase_key
)
