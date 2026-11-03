"""Immutable artifacts and atomic compare-and-swap of a coherent serving bundle."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .contracts import bounded_text, canonical, digest, integer, valid_digest
from .store import StaleSource


def durable_bytes(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("artifact symlink")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    try:
        os.replace(temporary, path)
        if os.name != "nt":
            handle = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(handle)
            finally:
                os.close(handle)
    finally:
        temporary.unlink(missing_ok=True)


class ArtifactOwner:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "owner.sqlite", timeout=5, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS active (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL, digest TEXT)"
        )
        self.db.execute("INSERT OR IGNORE INTO active VALUES (1,0,NULL)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS transitions (generation INTEGER PRIMARY KEY, predecessor TEXT, successor TEXT NOT NULL)"
        )

    def active(self):
        generation, identity = self.db.execute("SELECT generation,digest FROM active WHERE id=1").fetchone()
        return generation, identity

    def put(self, raw):
        identity = hashlib.sha256(raw).hexdigest()
        path = self.root / "objects" / identity
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError("content-addressed object was corrupted")
        else:
            durable_bytes(path, raw)
        return {"sha256": identity, "bytes": len(raw)}

    def get(self, reference):
        identity = reference["sha256"]
        if len(identity) != 64 or any(x not in "0123456789abcdef" for x in identity):
            raise ValueError("invalid object address")
        path = self.root / "objects" / identity
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_000_000:
            raise ValueError("missing or invalid object")
        raw = path.read_bytes()
        if len(raw) != reference["bytes"] or hashlib.sha256(raw).hexdigest() != identity:
            raise ValueError("object integrity mismatch")
        return raw

    def publish(self, manifest, *, expected_generation, fail_before_commit=False):
        generation, previous = self.active()
        if generation != expected_generation:
            raise StaleSource("publication predecessor changed")
        manifest = {**manifest, "generation": generation + 1, "predecessor": previous}
        validate_bundle(manifest)
        # Validate every child before publishing the one pointer that exposes them.
        from .cells import AssociativeCell, key_digest

        for kind, reference in manifest["cells"].items():
            cell = AssociativeCell.from_bytes(self.get(reference))
            expected = {key_digest(key): [source] for key, source in manifest["supports"][kind].items()}
            if (
                cell.kind != kind
                or cell.supports != expected
                or cell.training_receipt != manifest["training_receipts"][kind]
            ):
                raise ValueError("cell type, provenance, or training receipt differs from bundle")
        raw = canonical(manifest)
        identity = digest(manifest)
        durable_bytes(self.root / "snapshots" / (identity + ".json"), raw)
        if fail_before_commit:
            raise RuntimeError("injected exit boundary before publication")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.active() != (generation, previous):
                raise StaleSource("concurrent publication lost CAS")
            self.db.execute("INSERT INTO transitions VALUES (?,?,?)", (generation + 1, previous, identity))
            self.db.execute("UPDATE active SET generation=?,digest=? WHERE id=1", (generation + 1, identity))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return identity

    def manifest(self, expected_digest=None):
        generation, identity = self.active()
        if identity is None or (expected_digest is not None and identity != expected_digest):
            raise StaleSource("requested generation is not active")
        path = self.root / "snapshots" / (identity + ".json")
        if path.is_symlink():
            raise ValueError("snapshot symlink")
        raw = path.read_bytes()
        value = json.loads(raw)
        if digest(value) != identity or value["generation"] != generation:
            raise ValueError("snapshot integrity mismatch")
        validate_bundle(value)
        return value, identity

    def close(self):
        self.db.close()


def validate_bundle(value):
    keys = {
        "schema",
        "scope",
        "source_cut",
        "source_frontier",
        "cells",
        "supports",
        "router_contract",
        "router_digest",
        "primitives",
        "training_receipts",
        "seed",
        "generation",
        "predecessor",
    }
    if not isinstance(value, dict) or set(value) != keys or value["schema"] != "hepta.memory.bundle.v1":
        raise ValueError("invalid bundle schema")
    if (
        not bounded_text(value["scope"])
        or not integer(value["source_cut"], 1, 2**53 - 1)
        or not integer(value["generation"], 1, 2**53 - 1)
    ):
        raise ValueError("invalid bundle scope or generation")
    if not valid_digest(value["source_frontier"]) or not valid_digest(value["router_digest"]):
        raise ValueError("invalid bundle binding")
    if value["predecessor"] is not None and not valid_digest(value["predecessor"]):
        raise ValueError("invalid bundle predecessor")
    if value["router_contract"] != "hepta.memory.router.v1" or value["primitives"] != "typed-arithmetic-v1":
        raise ValueError("unsupported bundle contract")
    if not integer(value["seed"], 0, 2**32 - 1):
        raise ValueError("invalid training seed")
    for field in ("cells", "supports", "training_receipts"):
        if not isinstance(value[field], dict) or set(value[field]) != {"semantic", "procedure"}:
            raise ValueError("incomplete typed bundle")
    for kind, reference in value["cells"].items():
        if (
            not isinstance(reference, dict)
            or set(reference) != {"sha256", "bytes"}
            or not valid_digest(reference["sha256"])
            or not integer(reference["bytes"], 1, 32_000_000)
        ):
            raise ValueError("invalid model reference")
        support = value["supports"][kind]
        if (
            not isinstance(support, dict)
            or not 1 <= len(support) <= 4096
            or not all(bounded_text(key) and valid_digest(item) for key, item in support.items())
        ):
            raise ValueError("invalid typed source support")
