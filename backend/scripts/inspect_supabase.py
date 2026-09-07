import psycopg
from app.config import settings

def inspect():
    conn_str = settings.supabase_db_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
            tables = [r[0] for r in cur.fetchall()]
            print("Existing tables in Supabase public schema:")
            for t in tables:
                print(" -", t)

if __name__ == "__main__":
    inspect()
