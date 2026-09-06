import sqlite3
from pathlib import Path

def dump():
    db_path = Path("revive.db")
    if not db_path.exists():
        raise FileNotFoundError("revive.db not found")
    
    con = sqlite3.connect(str(db_path))
    rows = con.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()
    
    output = [
        "-- Revenue Rescue Engine (REVIVE) Database Baseline Schema",
        "-- Alembic Head: 0004_outcome_discount_total",
        "-- Snapshot source: revive.db (SQLite)",
        "",
    ]
    for obj_type, name, sql in rows:
        output.append(f"-- {obj_type.upper()}: {name}")
        output.append(sql.strip() + ";\n")
    
    out_file = Path("alembic") / "revive_schema_baseline.sql"
    out_file.write_text("\n".join(output), encoding="utf-8")
    print(f"Schema successfully written to {out_file} ({len(rows)} objects)")

if __name__ == "__main__":
    dump()
