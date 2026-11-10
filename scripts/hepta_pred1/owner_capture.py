"""Bounded retrospective TaskFlow inventory, never a predecision observation.

The operator supplies an existing database and the host arrival sequencer.
Captured owner settlements remain distinct from independently observed effects.
Database paths and identities are private artifacts; publish only reviewed data.
"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .native_ledger import (
    Artifact,
    IDENTITY_FIELDS,
    KEY_FIELDS,
    MAX_BYTES,
    _identity,
    _integer,
    _require,
    _text,
    collect_native,
)


def discover_native(database, *, limit=64, after=None):
    """Read at most one page; the key cursor is not a transactional log cursor.

    Later inserts behind this key need a separate inventory. The result does
    not claim a complete live change stream or authenticate an owner.
    """
    _integer(limit, 1, 256)
    path = Path(database).resolve(strict=True)
    _require(path.is_file(), "native database must already exist")
    if after is not None:
        _require(type(after) is list and len(after) == 4, "invalid page key")
        for value in after[:3]:
            _text(value)
        _integer(after[3], 1, 1_000_000)
    fields = ",".join(
        f"CASE WHEN length(CAST({field} AS BLOB)) <= 1024 "
        f"THEN {field} ELSE NULL END AS {field}"
        for field in IDENTITY_FIELDS
    )
    keys = ",".join(KEY_FIELDS)
    where = f" WHERE ({keys}) > (?,?,?,?)" if after is not None else ""
    query = (
        f"SELECT {fields} FROM taskflow_effect_dispatch_attempts{where} "
        f"ORDER BY {keys} LIMIT ?"
    )
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        if hasattr(db, "setlimit"):
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_BYTES)
        db.execute("PRAGMA query_only = ON")
        db.execute("BEGIN")
        rows = [dict(row) for row in db.execute(query, tuple(after or ()) + (limit + 1,))]
        db.rollback()
    for row in rows:
        _identity(row)
    page = rows[:limit]
    identities = [tuple(row[key] for key in KEY_FIELDS) for row in rows]
    _require(len(set(identities)) == len(identities), "duplicate native attempt key")
    return {
        "identities": page,
        "next_after": [page[-1][key] for key in KEY_FIELDS] if len(rows) > limit else None,
        "pagination_scope": "retrospective ordered keys; not a live change stream",
    }


def capture_native(database, output, *, clock_id, start_cursor, limit=64, after=None):
    """Create immutable collection files and a final manifest, with no labels.

    A failed capture leaves its partial directory for inspection. An existing
    output is never overwritten or silently resumed with another arrival order.
    """
    _text(clock_id)
    _integer(start_cursor)
    _require(start_cursor + limit < 2**63, "arrival cursor overflow")
    page = discover_native(database, limit=limit, after=after)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for index, identity in enumerate(page["identities"]):
        artifact = collect_native(
            database, identity=identity, clock_id=clock_id, cursor=start_cursor + index
        )
        filename = f"collection-{index:04d}.json"
        artifact.save(output / filename)
        records.append({"path": filename, "sha256": artifact.digest})
    manifest = Artifact.make(
        {
            "schema": "pred1-owner-capture-v1",
            "database_path": str(Path(database).resolve(strict=True)),
            "clock_id": clock_id,
            "start_cursor": start_cursor,
            "next_cursor": start_cursor + len(records),
            "records": records,
            "next_after": page["next_after"],
            "record_count": len(records),
            "source_provenance": "operator-supplied database; not authenticated",
            "predecision_snapshots_created": 0,
            "effect_labels_created": 0,
            "independent_confirmation_units_added": 0,
            "scope": page["pagination_scope"],
            "qualification": "HOLD",
            "production_activation": False,
        }
    )
    manifest.save(output / "CAPTURE.json")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--clock-id", required=True)
    parser.add_argument("--start-cursor", type=int, required=True)
    parser.add_argument("--limit", type=int, default=64)
    parser.add_argument("--after-json", help="previous CAPTURE.json next_after JSON")
    args = parser.parse_args()
    result = capture_native(
        args.database,
        args.output,
        clock_id=args.clock_id,
        start_cursor=args.start_cursor,
        limit=args.limit,
        after=json.loads(args.after_json) if args.after_json else None,
    )
    print(json.dumps({"manifest_sha256": result.digest, "records": result.payload["record_count"]}))


if __name__ == "__main__":
    main()
