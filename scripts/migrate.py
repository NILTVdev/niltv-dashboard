#!/usr/bin/env python3
"""
Apply backend/migrations/*.sql in order, once each, tracked in schema_migrations.

Replaces the hand-run `psql -f backend/migrations/NNN_*.sql` with something the
deploy step, the local compose stack and CI can all call the same way:

    python -m scripts.migrate                 # apply everything not yet applied
    python -m scripts.migrate --status        # list applied / pending
    python -m scripts.migrate --fake 026      # mark 001..026 applied WITHOUT running them
                                              # (one-time on a database that was migrated by hand)
    python -m scripts.migrate --dry-run       # show what would run

Each file runs inside its own transaction via psycopg2 (files that carry their
own BEGIN/COMMIT are fine — psql-style transaction control is stripped so the
whole file is one atomic unit either way). A failure stops the run and leaves
the failed file unrecorded, so the next run retries it.
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from backend.database import engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "backend" / "migrations"
_TX_CONTROL = re.compile(r"^\s*(BEGIN|COMMIT|END)\s*;\s*$", re.IGNORECASE | re.MULTILINE)


def _files() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.name[:3].isdigit())


def _ensure_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            faked      BOOLEAN NOT NULL DEFAULT FALSE
        )"""))


def _applied(conn) -> set[str]:
    return {r[0] for r in conn.execute(text("SELECT filename FROM schema_migrations"))}


def _apply(conn, path: Path) -> None:
    sql = _TX_CONTROL.sub("", path.read_text(encoding="utf-8"))
    # Raw DBAPI cursor with no parameters: psycopg2 then leaves '%' alone, so
    # LIKE patterns and format strings inside the SQL are not misread as
    # placeholders (exec_driver_sql would try to interpolate them).
    cur = conn.connection.cursor()
    try:
        cur.execute(sql)
    finally:
        cur.close()
    conn.execute(text("INSERT INTO schema_migrations (filename) VALUES (:f)"), {"f": path.name})


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply pending SQL migrations")
    ap.add_argument("--status", action="store_true", help="list applied and pending files")
    ap.add_argument("--dry-run", action="store_true", help="print pending files, apply nothing")
    ap.add_argument("--fake", metavar="NNN",
                    help="record every migration up to and including NNN as applied, without running them")
    args = ap.parse_args()

    files = _files()
    with engine.begin() as conn:
        _ensure_table(conn)
        applied = _applied(conn)

    if args.fake:
        with engine.begin() as conn:
            n = 0
            for p in files:
                if p.name[:3] <= args.fake and p.name not in applied:
                    conn.execute(text(
                        "INSERT INTO schema_migrations (filename, faked, applied_at) VALUES (:f, TRUE, :t)"),
                        {"f": p.name, "t": datetime.now(tz=timezone.utc)})
                    n += 1
        print(f"marked {n} migration(s) up to {args.fake} as applied (faked)")
        return 0

    pending = [p for p in files if p.name not in applied]
    if args.status or args.dry_run:
        for p in files:
            print(f"  {'applied' if p.name in applied else 'PENDING'}  {p.name}")
        print(f"{len(applied)} applied, {len(pending)} pending")
        return 0

    if not pending:
        print("schema up to date — nothing to apply")
        return 0

    for p in pending:
        print(f"==> applying {p.name}", flush=True)
        try:
            with engine.begin() as conn:
                _apply(conn, p)
        except Exception as e:  # noqa: BLE001 — report and stop; the file stays pending
            print(f"FAILED {p.name}: {e}", file=sys.stderr)
            return 1
    print(f"applied {len(pending)} migration(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
