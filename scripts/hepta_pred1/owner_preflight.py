"""Check a known owner database before retrospective research collection.

This opt-in structural check does not authenticate the database or replace the
native Store verifier. No owner records, snapshots, labels or cursors are made.
Run only on an exact existing source; returned owner identities remain private.
"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .native_ledger import Artifact, MAX_BYTES, TABLE_FIELDS, _integer, _require, _text

# Pinned to hepta-automation/src/lib.rs at 10629bab4d5f948854e7c59fed331213956fb974.
# A newer deployed schema needs a separately reviewed contract, not a CLI override.
SUPPORTED_SCHEMA_VERSION = 20


def inspect_owner_database(database, *, expected_owner, row_limit=256):
    """Read metadata, required columns and bounded counts in one WAL snapshot.

    ``bounded_rows`` is a lower bound when ``row_count_complete`` is false.
    This is neither a stream cursor nor a complete integrity/foreign-owner scan.
    A later collector opens its own transaction and must not infer continuity.
    """
    _text(expected_owner)
    _integer(row_limit, 1, 256)
    path = Path(database).resolve(strict=True)
    _require(path.is_file(), "owner database must already be a regular file")
    tables = {"automation_meta": ("singleton", "schema_version", "owner_agent_id")}
    tables.update(
        {
            "taskflow_effect_dispatch_" + key: fields
            for key, fields in TABLE_FIELDS.items()
        }
    )
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    ) as db:
        if hasattr(db, "setlimit"):
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_BYTES)
        db.execute("PRAGMA query_only = ON")
        db.execute("BEGIN")
        inventory = {}
        for table, required in tables.items():
            # SQL projection bounds transfer even on Python 3.10, which lacks
            # Connection.setlimit. A view cannot stand in for an owner table.
            kind = db.execute(
                "SELECT type FROM sqlite_master WHERE name=? LIMIT 2", (table,)
            ).fetchall()
            _require(kind == [("table",)], "required owner table missing or ambiguous")
            columns = db.execute(
                "SELECT CASE WHEN length(CAST(name AS BLOB)) <= 256 THEN name ELSE NULL END "
                "FROM pragma_table_info(?) LIMIT 65",
                (table,),
            ).fetchall()
            _require(
                len(columns) <= 64 and all(type(row[0]) is str for row in columns),
                "owner table column bounds differ",
            )
            names = [row[0] for row in columns]
            _require(
                set(required).issubset(names), "required owner table columns missing"
            )
            inventory[table] = {"columns": names}
        meta = db.execute(
            "SELECT CASE WHEN typeof(singleton)='integer' THEN singleton ELSE NULL END, "
            "CASE WHEN typeof(schema_version)='integer' THEN schema_version ELSE NULL END, "
            "CASE WHEN length(CAST(owner_agent_id AS BLOB)) <= 1024 "
            "THEN owner_agent_id ELSE NULL END FROM automation_meta LIMIT 2"
        ).fetchall()
        _require(len(meta) == 1, "owner metadata must have exactly one row")
        singleton, schema, owner = meta[0]
        _require(
            type(singleton) is int and singleton == 1,
            "invalid owner metadata singleton",
        )
        _require(
            type(schema) is int and schema == SUPPORTED_SCHEMA_VERSION,
            "unsupported owner schema version",
        )
        _text(owner)
        _require(owner == expected_owner, "owner metadata identity differs")
        for table in tables:
            if table != "automation_meta":
                count = db.execute(
                    f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} LIMIT ?)",
                    (row_limit + 1,),
                ).fetchone()[0]
                inventory[table].update(
                    bounded_rows=count, row_count_complete=count <= row_limit
                )
        db.rollback()
    return Artifact.make(
        {
            "schema": "pred1-owner-preflight-v1",
            "owner_agent_id": owner,
            "schema_version": schema,
            "row_limit": row_limit,
            "tables": inventory,
            "metadata_owner_matches": True,
            "native_provenance_authenticated": False,
            "source_provenance": "operator-supplied existing database and expected owner",
            "scope": "one read-only transaction; structural preflight, not native Store verification",
            "arrival_sequencer_verified": False,
            "host_boot_clock_verified": False,
            "predecision_snapshots_created": 0,
            "effect_labels_created": 0,
            "independent_confirmation_units_added": 0,
            "qualification": "HOLD",
            "production_activation": False,
        }
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--expected-owner", required=True)
    parser.add_argument(
        "--output", required=True, help="new private artifact path; never overwritten"
    )
    parser.add_argument("--row-limit", type=int, default=256)
    args = parser.parse_args()
    report = inspect_owner_database(
        args.database, expected_owner=args.expected_owner, row_limit=args.row_limit
    )
    report.save(args.output)
    print(json.dumps({"preflight_sha256": report.digest, "qualification": "HOLD"}))


if __name__ == "__main__":
    main()
