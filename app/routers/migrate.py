"""
Temporary migration endpoint — copy data from Supabase to current DB (Neon).
Remove this file after migration is complete.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, text
from ..database import engine as neon_engine

router = APIRouter(prefix="/migrate", tags=["Migration"])

TABLES_IN_ORDER = [
    "users",
    "qc_content",
    "qc_history",
    "subtitle_tasks",
    "on_air_entries",
    "push_subscriptions",
    "user_notifications",
    "deliveries",
    "content_requests",
    "logbook_entries",
]

@router.post("/from-supabase")
def migrate_from_supabase(supabase_url: str):
    results = {}
    try:
        src_engine = create_engine(supabase_url, connect_args={"connect_timeout": 15})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot create source engine: {e}")

    with src_engine.connect() as src, neon_engine.connect() as dst:
        existing = src.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )).fetchall()
        existing_tables = {r[0] for r in existing}

        for table in TABLES_IN_ORDER:
            if table not in existing_tables:
                results[table] = "skipped (not in source)"
                continue
            try:
                rows = src.execute(text(f"SELECT * FROM {table}")).fetchall()
                if not rows:
                    results[table] = "empty"
                    continue

                cols = src.execute(text(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_schema='public' AND table_name='{table}' "
                    f"ORDER BY ordinal_position"
                )).fetchall()
                col_names = [c[0] for c in cols]

                # Truncate target table
                dst.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))

                # Quote all column names to avoid reserved keyword issues
                col_str = ", ".join([f'"{c}"' for c in col_names])
                placeholders = ", ".join([f":{c}" for c in col_names])
                insert_sql = text(f'INSERT INTO {table} ({col_str}) VALUES ({placeholders})')

                for row in rows:
                    row_dict = dict(zip(col_names, row))
                    dst.execute(insert_sql, row_dict)

                # Reset sequence if id column exists
                if "id" in col_names:
                    dst.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
                    ))

                dst.commit()
                results[table] = f"migrated {len(rows)} rows"
            except Exception as e:
                dst.rollback()
                results[table] = f"ERROR: {str(e)[:200]}"

    src_engine.dispose()
    return {"status": "done", "results": results}
