#!/usr/bin/env python3
"""Check the frontend's API types against the backend's OpenAPI schema.

§2.1 requires "a typed API client generated from or checked against the
backend's OpenAPI schema". This is the "checked against" half.

It builds the FastAPI app in-process (no server, no database, no network),
takes the schema it would serve at /openapi.json, and compares it with
frontend/src/api/types.ts:

  - every enum (Category, Priority, Status, TriagedBy) must have exactly the
    same members on both sides, and
  - every response model the frontend consumes must have the same field names.

When the backend adds a category and the frontend does not, CI goes red here,
before a user ever sees an unrenderable badge.

    python scripts/check_openapi_contract.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TYPES_TS = ROOT / "frontend" / "src" / "api" / "types.ts"

# Backend schema name -> frontend type name.
ENUMS = {
    "Category": "Category",
    "Priority": "Priority",
    "Status": "Status",
    "TriagedBy": "TriagedBy",
}
MODELS = {
    "ComplaintOut": "Complaint",
    "ComplaintPage": "ComplaintPage",
    "StatsOut": "Stats",
    "ProvidersOut": "ProvidersInfo",
    "TriageRecordOut": "TriageRecord",
}


def load_schema() -> dict:
    # Building the app must not reach for a real database or key.
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("REDIS_URL", "redis://unused")
    os.environ.setdefault("TRIAGE_PROVIDER", "rules")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import create_app  # noqa: PLC0415 -- after the env is set

    return create_app().openapi()


def ts_union(source: str, name: str) -> set[str] | None:
    match = re.search(rf"export type {name}\s*=\s*((?:\s*\|?\s*'[^']*')+)", source)
    if not match:
        return None
    return set(re.findall(r"'([^']*)'", match.group(1)))


def ts_fields(source: str, name: str) -> set[str] | None:
    match = re.search(rf"export interface {name}\s*\{{(.*?)\n\}}", source, re.DOTALL)
    if not match:
        return None
    fields = set()
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith(("//", "/*", "*")):
            continue
        field = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\??\s*:", line)
        if field:
            fields.add(field.group(1))
    return fields


def main() -> int:
    schemas = load_schema()["components"]["schemas"]
    source = TYPES_TS.read_text(encoding="utf-8")
    problems: list[str] = []

    for backend_name, frontend_name in ENUMS.items():
        expected = set(schemas.get(backend_name, {}).get("enum", []))
        actual = ts_union(source, frontend_name)
        if not expected:
            problems.append(f"enum {backend_name} missing from the OpenAPI schema")
        elif actual is None:
            problems.append(f"type {frontend_name} missing from types.ts")
        elif expected != actual:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            problems.append(
                f"{frontend_name}: frontend is missing {missing or '[]'}, "
                f"has extra {extra or '[]'}"
            )
        else:
            print(f"  ok  enum   {frontend_name:<14} {len(expected)} members")

    for backend_name, frontend_name in MODELS.items():
        expected = set(schemas.get(backend_name, {}).get("properties", {}))
        actual = ts_fields(source, frontend_name)
        if not expected:
            problems.append(f"model {backend_name} missing from the OpenAPI schema")
        elif actual is None:
            problems.append(f"interface {frontend_name} missing from types.ts")
        elif expected != actual:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            problems.append(
                f"{frontend_name} vs {backend_name}: frontend is missing "
                f"{missing or '[]'}, has extra {extra or '[]'}"
            )
        else:
            print(f"  ok  model  {frontend_name:<14} {len(expected)} fields")

    if problems:
        print("\nOpenAPI contract drift:")
        for problem in problems:
            print(f"  FAIL {problem}")
        return 1
    print("\nfrontend/src/api/types.ts matches the backend's OpenAPI schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
