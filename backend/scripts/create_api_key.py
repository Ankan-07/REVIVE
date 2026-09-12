#!/usr/bin/env python3
"""CLI utility to create a per-person service API key (Phase A2.2).

Usage:
    python backend/scripts/create_api_key.py --name "Alice Vance" --scopes operator --expires-days 90
    python backend/scripts/create_api_key.py --name "Worker Cron" --scopes internal
    python backend/scripts/create_api_key.py --name "Dev Admin" --scopes admin,operator,internal

Prints the plaintext key ONCE to stdout. Keys are per-person and should never be shared.
"""
import argparse
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.db import SessionLocal
from app.services import api_key_service


def main():
    parser = argparse.ArgumentParser(description="Create a new service API key for REVIVE.")
    parser.add_argument("--name", required=True, help="Operator or service name (e.g. 'Alice Vance')")
    parser.add_argument(
        "--scopes",
        default="operator",
        help="Comma-separated scopes (operator, internal, admin, webhooks:receive). Default: operator",
    )
    parser.add_argument(
        "--expires-days",
        type=int,
        default=None,
        help="Optional expiration in days. Defaults to non-expiring.",
    )

    args = parser.parse_args()

    db = SessionLocal()
    try:
        key_record, raw_key = api_key_service.create_key(
            db=db,
            name=args.name,
            scopes=args.scopes,
            expires_days=args.expires_days,
        )
        print("=" * 70)
        print("REVIVE SERVICE API KEY CREATED")
        print("=" * 70)
        print(f"ID:           {key_record.id}")
        print(f"Name:         {key_record.name}")
        print(f"Prefix:       {key_record.key_prefix}")
        print(f"Scopes:       {key_record.scopes}")
        print(f"Expires:      {key_record.expires_at or 'Never'}")
        print("-" * 70)
        print("PLAINTEXT KEY (PRINTED ONCE — STORE IN A SECURE PASSWORD MANAGER):")
        print(f"\n    {raw_key}\n")
        print("=" * 70)
    except Exception as exc:
        print(f"Error creating API key: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
