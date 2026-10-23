"""Persistent research-only adapter pointers; no source ledger or model authority.

The host supplies an independently retained manifest digest, allowed source roots,
and a current withdrawal view. These inputs are not authenticated by this module.
Model compatibility is still checked by LoRAReader.load_candidate in the callback.
SQLite serializes local processes; this is not a distributed consensus service.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3

from tensor_contract import bounded_read, sha256, strict_json, validate_tensor_bytes

MAX_ROOTS = 4096
MAX_CELLS = 64


def _name(value):
    return (
        isinstance(value, str) and 1 <= len(value.encode()) <= 128 and "\0" not in value
    )


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _roots(values):
    if (
        not isinstance(values, (tuple, list, set, frozenset))
        or len(values) > MAX_ROOTS
        or any(not _digest(v) for v in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("bounded unique source digests required")
    return tuple(sorted(values))


@dataclass(frozen=True)
class Frontier:
    scope: str
    epoch: int = 0
    revoked: tuple[str, ...] = ()

    def __post_init__(self):
        if (
            not _name(self.scope)
            or type(self.epoch) is not int
            or not 0 <= self.epoch < 2**63
        ):
            raise ValueError("invalid source frontier")
        object.__setattr__(self, "revoked", _roots(self.revoked))


@dataclass(frozen=True)
class ActiveCell:
    cell_id: str
    scope: str
    directory: str
    manifest_sha256: str
    generation: int
    parent_manifest_sha256: str | None
    roots: tuple[str, ...]
    base_identity: str


def _checkpoint(directory, expected, scope):
    path = Path(directory)
    if path.is_symlink() or not path.is_dir() or not _digest(expected):
        raise ValueError("real checkpoint directory and retained digest required")
    data = bounded_read(path / "lineage.json", 256 * 1024)
    if sha256(data) != expected:
        raise ValueError("checkpoint manifest changed")
    manifest = strict_json(data)
    json.dumps(manifest, allow_nan=False)
    required = {
        "schema",
        "base_identity",
        "scope",
        "roots",
        "tensor_layout",
        "adapter_sha256",
        "config_sha256",
        "training",
        "model_install_authority",
        "production_accepted",
    }
    if (
        set(manifest) != required
        or manifest["schema"] != "hepta.memory-lora-candidate.v2"
        or manifest["scope"] != scope
        or not _digest(manifest["base_identity"])
        or manifest["model_install_authority"] is not False
        or manifest["production_accepted"] is not False
    ):
        raise ValueError("checkpoint scope or research contract mismatch")
    roots = _roots(manifest["roots"])
    if not roots:
        raise ValueError("empty checkpoint provenance")
    config = bounded_read(path / "adapter_config.json", 64 * 1024)
    if sha256(config) != manifest["config_sha256"]:
        raise ValueError("checkpoint configuration changed")
    json.dumps(strict_json(config), allow_nan=False)
    validate_tensor_bytes(
        bounded_read(path / "adapter_model.safetensors", 64 * 1024 * 1024),
        expected_sha256=manifest["adapter_sha256"],
        expected_layout=manifest["tensor_layout"],
    )
    return roots, manifest["base_identity"]


class ParametricOwner:
    """CAS active research versions and latch every valid observed withdrawal view."""

    def __init__(self, database):
        self.database = str(Path(database).absolute())
        if Path(self.database).is_symlink():
            raise ValueError("owner database cannot be a symlink")
        with self._transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS frontiers (scope TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS cells (scope TEXT NOT NULL, cell TEXT NOT NULL, "
                "value TEXT NOT NULL, PRIMARY KEY(scope, cell))"
            )

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _observe(self, scope, provider):
        if not _name(scope) or not callable(provider):
            raise ValueError("scope and current frontier provider required")
        view = provider()
        if type(view) is not Frontier or view.scope != scope:
            raise ValueError("source frontier scope mismatch")
        with self._transaction() as db:
            old = db.execute(
                "SELECT value FROM frontiers WHERE scope=?", (scope,)
            ).fetchone()
            if old:
                previous = Frontier(**strict_json(old[0].encode()))
                if (
                    view.epoch < previous.epoch
                    or not set(previous.revoked) <= set(view.revoked)
                    or (view.epoch == previous.epoch and view != previous)
                ):
                    raise ValueError("withdrawal frontier rollback or same-epoch fork")
            elif (
                db.execute("SELECT count(*) FROM frontiers").fetchone()[0] >= MAX_CELLS
            ):
                raise ValueError("owner scope budget exceeded")
            db.execute(
                "INSERT OR REPLACE INTO frontiers VALUES (?, ?)",
                (scope, json.dumps(asdict(view), sort_keys=True)),
            )
        # This transaction stays committed even if the subsequent request fails.
        return view

    @staticmethod
    def _current(db, scope, cell_id):
        row = db.execute(
            "SELECT value FROM cells WHERE scope=? AND cell=?", (scope, cell_id)
        ).fetchone()
        if not row:
            return None
        value = strict_json(row[0].encode())
        value["roots"] = _roots(value["roots"])
        return ActiveCell(**value)

    @staticmethod
    def _barrier(db, view):
        row = db.execute(
            "SELECT value FROM frontiers WHERE scope=?", (view.scope,)
        ).fetchone()
        if not row or Frontier(**strict_json(row[0].encode())) != view:
            raise ValueError("source frontier changed during operation")

    def activate(
        self,
        cell_id,
        snapshot_dir,
        expected_manifest_sha256,
        *,
        scope,
        expected_current,
        generation,
        provider,
        allowed_roots,
        parent_manifest_sha256=None,
    ):
        """Publish a version; parent describes the pointer, not gradient ancestry.

        A clean replay may replace a revoked version. Its manifest must contain
        only replayed source roots; the owner cannot certify how weights trained.
        """
        if (
            not _name(cell_id)
            or not _name(scope)
            or type(generation) is not int
            or not 0 <= generation < 2**63
            or len(str(snapshot_dir).encode()) > 4096
            or (expected_current is not None and not _digest(expected_current))
            or parent_manifest_sha256 != expected_current
        ):
            raise ValueError("invalid cell version or parent binding")
        allowed = set(_roots(allowed_roots))
        self._observe(scope, provider)
        roots, base = _checkpoint(snapshot_dir, expected_manifest_sha256, scope)
        if not set(roots) <= allowed:
            raise ValueError("checkpoint source not independently allowed")
        candidate = ActiveCell(
            cell_id,
            scope,
            str(Path(snapshot_dir).absolute()),
            expected_manifest_sha256,
            generation,
            parent_manifest_sha256,
            roots,
            base,
        )
        view = self._observe(scope, provider)
        if set(roots) & set(view.revoked):
            raise ValueError("withdrawn learning ancestor")
        with self._transaction() as db:
            self._barrier(db, view)
            current = self._current(db, scope, cell_id)
            if (
                current.manifest_sha256 if current else None
            ) != expected_current or generation != (
                current.generation + 1 if current else 0
            ):
                raise ValueError("active version CAS or generation mismatch")
            if current is not None and current.base_identity != base:
                raise ValueError("active base identity cannot change")
            if (
                current is None
                and db.execute("SELECT count(*) FROM cells").fetchone()[0] >= MAX_CELLS
            ):
                raise ValueError("active cell budget exceeded")
            db.execute(
                "INSERT OR REPLACE INTO cells VALUES (?, ?, ?)",
                (scope, cell_id, json.dumps(asdict(candidate), sort_keys=True)),
            )
        return candidate

    def current(self, cell_id, scope):
        """Read pointer metadata only; this does not admit a model for inference."""
        if not _name(cell_id) or not _name(scope):
            raise ValueError("cell identity and scope required")
        with self._transaction() as db:
            return self._current(db, scope, cell_id)

    def invoke(self, cell_id, scope, provider, callback, *, query_roots=()):
        """Admit after byte validation; suppress results changed after admission.

        The final short transaction is the local admission linearization point.
        No SQLite transaction spans callback execution. An authority/version
        change after admission may overlap an in-flight callback, but its result
        is rejected by the existing post-callback checks.
        """
        if not _name(cell_id) or not callable(callback):
            raise ValueError("cell identity and inference callback required")
        query = set(_roots(query_roots))
        before = self._observe(scope, provider)
        with self._transaction() as db:
            self._barrier(db, before)
            cell = self._current(db, scope, cell_id)
        if cell is None:
            raise ValueError("no active cell in requested scope")
        if (set(cell.roots) | query) & set(before.revoked):
            raise ValueError("withdrawn inference source")
        if _checkpoint(cell.directory, cell.manifest_sha256, scope) != (
            cell.roots,
            cell.base_identity,
        ):
            raise ValueError("active checkpoint differs from retained metadata")
        admission = self._observe(scope, provider)
        with self._transaction() as db:
            self._barrier(db, admission)
            if admission != before or self._current(db, scope, cell_id) != cell:
                raise ValueError(
                    "inference frontier or active version changed before callback"
                )
        result = callback(cell)
        after = self._observe(scope, provider)
        if _checkpoint(cell.directory, cell.manifest_sha256, scope) != (
            cell.roots,
            cell.base_identity,
        ):
            raise ValueError("checkpoint changed during inference")
        with self._transaction() as db:
            self._barrier(db, after)
            if after != before or self._current(db, scope, cell_id) != cell:
                raise ValueError("inference frontier or active version changed")
        return result
