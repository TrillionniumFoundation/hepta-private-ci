"""Single-owner source revisions and immutable learned-adapter publication.

This is a research owner, not the native Hepta authority. Source freshness and
artifact integrity are separate from the caller's executable quality validator.
Revocation fences reads; it does not erase historical weights or source bytes.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from adapter import Adapter


class Refused(RuntimeError):
    """A source, model, namespace, or publication precondition did not hold."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fsync_dir(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class SourceOwner:
    """One SQLite writer with explicit scope and immutable source history."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "sources.sqlite", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sources(
                scope TEXT, source_id TEXT, revision INTEGER, body TEXT,
                body_sha256 TEXT, active INTEGER,
                PRIMARY KEY(scope,source_id,revision));
            CREATE TABLE IF NOT EXISTS releases(
                scope TEXT, cell TEXT, epoch INTEGER, artifact TEXT,
                validation TEXT, PRIMARY KEY(scope,cell));
        """)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def source(self, scope, source_id):
        row = self.db.execute(
            "SELECT * FROM sources WHERE scope=? AND source_id=? "
            "ORDER BY revision DESC LIMIT 1", (scope, source_id)).fetchone()
        return None if row is None else dict(row)

    def put(self, scope, source_id, body, *, expected_revision, active=True):
        if not scope or not source_id or not isinstance(body, str):
            raise Refused("source needs an explicit scope, identity, and text")
        with self.transaction():
            prior = self.source(scope, source_id)
            current = 0 if prior is None else prior["revision"]
            if current != expected_revision:
                raise Refused("source revision changed")
            revision = current + 1
            self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?)",
                            (scope, source_id, revision, body, sha(body.encode()), int(active)))
        return revision

    def cut(self, scope, source_ids):
        ids = sorted(set(source_ids))
        if not scope or not ids:
            raise Refused("empty source scope")
        records = []
        for source_id in ids:
            row = self.source(scope, source_id)
            if row is None or not row["active"]:
                raise Refused("fitted source is missing or revoked")
            records.append({k: row[k] for k in ("source_id", "revision", "body_sha256")})
        return dict(scope=scope, records=records)

    def snapshot(self, scope, source_ids):
        with self.transaction():
            cut = self.cut(scope, source_ids)
            records = [self.source(scope, r["source_id"]) for r in cut["records"]]
        return cut, records

    def stage(self, scope, cut, model, *, parent_artifact=None):
        if cut.get("scope") != scope or model.source_version != sha(canonical(cut)):
            raise Refused("model source version is not this scope's frozen cut")
        if not re.fullmatch(r"[0-9a-f]{64}", model.encoder_hash):
            raise Refused("base encoder must have an exact SHA-256 identity")
        if parent_artifact is not None:
            _, parent = self.load(parent_artifact, scope, model.encoder_hash)
            before = {r["source_id"] for r in parent["source_cut"]["records"]}
            after = {r["source_id"] for r in cut["records"]}
            if not before.issubset(after):
                raise Refused("continued parameters cannot silently discard fitted source dependencies")
        pending = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.root / "artifacts"))
        try:
            model.save(pending / "model.npz")
            with (pending / "model.npz").open("rb") as stream:
                os.fsync(stream.fileno())
            manifest = dict(schema="hepta.memory.adapter-release.v13", scope=scope,
                            source_cut=cut, source_version=sha(canonical(cut)),
                            encoder_sha256=model.encoder_hash, parent_artifact=parent_artifact,
                            state_sha256=model.state_hash(),
                            model_sha256=sha((pending / "model.npz").read_bytes()))
            raw = canonical(manifest)
            with (pending / "manifest.json").open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            fsync_dir(pending)
            artifact = sha(raw)
            target = self.root / "artifacts" / artifact
            if target.exists():
                self.load(artifact, scope, model.encoder_hash)
            else:
                try:
                    pending.rename(target)
                except OSError:
                    if not target.is_dir():
                        raise
                    self.load(artifact, scope, model.encoder_hash)
                fsync_dir(target.parent)
            return artifact
        finally:
            if pending.exists():
                shutil.rmtree(pending)

    def load(self, artifact, scope, encoder_hash):
        if not re.fullmatch(r"[0-9a-f]{64}", artifact):
            raise Refused("invalid artifact identity")
        directory = self.root / "artifacts" / artifact
        if directory.is_symlink() or not directory.is_dir():
            raise Refused("missing or linked artifact")
        paths = list(directory.iterdir())
        if {p.name for p in paths} != {"manifest.json", "model.npz"} or any(
                p.is_symlink() or not p.is_file() for p in paths):
            raise Refused("artifact inventory changed")
        raw = (directory / "manifest.json").read_bytes()
        manifest = json.loads(raw)
        if sha(raw) != artifact or manifest.get("schema") != "hepta.memory.adapter-release.v13":
            raise Refused("artifact manifest identity changed")
        if manifest["scope"] != scope or manifest["encoder_sha256"] != encoder_hash:
            raise Refused("artifact belongs to a different scope or encoder")
        if sha((directory / "model.npz").read_bytes()) != manifest["model_sha256"]:
            raise Refused("model bytes changed")
        model = Adapter.load(directory / "model.npz", expected_encoder_hash=encoder_hash,
                             expected_source_version=manifest["source_version"])
        if model.state_hash() != manifest["state_sha256"]:
            raise Refused("complete model state changed")
        return model, manifest

    def publish(self, scope, cell, artifact, encoder_hash, *, expected_epoch,
                validator, boundary_hook=None):
        model, manifest = self.load(artifact, scope, encoder_hash)
        with self.transaction():
            ids = [r["source_id"] for r in manifest["source_cut"]["records"]]
            if self.cut(scope, ids) != manifest["source_cut"]:
                raise Refused("source changed after fitting")
            prior = self.db.execute("SELECT * FROM releases WHERE scope=? AND cell=?",
                                    (scope, cell)).fetchone()
            epoch = 0 if prior is None else prior["epoch"]
            if epoch != expected_epoch:
                raise Refused("publication epoch changed")
            validation = validator(model, [self.source(scope, sid) for sid in ids])
            if not isinstance(validation, dict) or validation.get("passed") is not True:
                raise Refused("executable publication validator rejected the model")
            self.db.execute("INSERT INTO releases VALUES (?,?,?,?,?) ON CONFLICT(scope,cell) "
                            "DO UPDATE SET epoch=excluded.epoch,artifact=excluded.artifact,"
                            "validation=excluded.validation",
                            (scope, cell, epoch + 1, artifact, canonical(validation).decode()))
            if boundary_hook is not None:
                boundary_hook("before_commit")
        if boundary_hook is not None:
            boundary_hook("after_commit")
        return epoch + 1

    def read(self, scope, cell, X, encoder_hash):
        with self.transaction():
            row = self.db.execute("SELECT * FROM releases WHERE scope=? AND cell=?",
                                  (scope, cell)).fetchone()
            if row is None:
                raise Refused("cell has no release in this scope")
            model, manifest = self.load(row["artifact"], scope, encoder_hash)
            ids = [r["source_id"] for r in manifest["source_cut"]["records"]]
            if self.cut(scope, ids) != manifest["source_cut"]:
                raise Refused("source correction invalidated this release")
            return dict(predictions=model.predict(X).tolist(), epoch=row["epoch"],
                        artifact=row["artifact"], source_version=manifest["source_version"])
