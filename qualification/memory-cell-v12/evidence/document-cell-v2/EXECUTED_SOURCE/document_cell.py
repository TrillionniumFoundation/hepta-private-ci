"""A durable learned cell for a deliberately bounded real-document field task.

The public address/operation parser canonicalizes supported questions. Actual
owner/deputy/lifecycle answers come from trained weights. This demonstrates a
source-to-answer lifecycle, not learned open-language understanding or storage
compression. Source bodies and optimizer state are retained and counted.
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

import numpy as np

from content_experiment import FIELDS, WIDTHS, decode, encode, resolve
from learned import MLP, canonical, features, predict_export, train_mlp


class Refused(RuntimeError):
    """No current, verified answer can be released."""


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def field_values(body):
    values = {}
    for label in ("Module", "Owner", "Deputy", "Lifecycle"):
        found = re.search(r"\*\*" + label + r":\*\*\s*`([^`]+)`", body)
        if found is None:
            raise ValueError("source is missing a declared document field")
        values[label.lower()] = found.group(1)
    return values


def canonical_question(module):
    return "State the owner, deputy, and lifecycle of " + module + "."


def write_durable(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


class DocumentCell:
    """One trusted local source owner; serving bytes have an immutable identity."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "owner.sqlite", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sources(
                module TEXT, revision INTEGER, active INTEGER, body TEXT,
                body_sha TEXT, provenance TEXT, PRIMARY KEY(module,revision));
            CREATE TABLE IF NOT EXISTS releases(
                cell TEXT PRIMARY KEY, artifact TEXT NOT NULL, epoch INTEGER NOT NULL);
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def source(self, module):
        row = self.db.execute("SELECT * FROM sources WHERE module=? ORDER BY revision DESC LIMIT 1",
                              (module,)).fetchone()
        if row is None:
            raise Refused("source address is absent")
        if hashlib.sha256(row["body"].encode()).hexdigest() != row["body_sha"]:
            raise Refused("source bytes differ from their committed digest")
        return dict(row)

    def put(self, body, provenance, *, expected_revision=0, active=True):
        module = field_values(body)["module"]
        with self.transaction():
            row = self.db.execute("SELECT MAX(revision) AS revision FROM sources WHERE module=?",
                                  (module,)).fetchone()
            current = row["revision"] or 0
            if current != expected_revision:
                raise Refused("source revision compare-and-swap failed")
            self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?)",
                            (module, current + 1, int(active), body,
                             hashlib.sha256(body.encode()).hexdigest(), canonical(provenance).decode()))
        return current + 1

    def cut(self, modules):
        # This serving freshness query does not fetch source bodies or answers.
        result = []
        for module in modules:
            row = self.db.execute("SELECT revision,active,body_sha FROM sources WHERE module=? "
                                  "ORDER BY revision DESC LIMIT 1", (module,)).fetchone()
            if row is None or not row["active"]:
                raise Refused("a fitted source was removed or revoked")
            result.append(dict(module=module, revision=row["revision"], source_sha256=row["body_sha"]))
        return result

    def fit(self, modules, *, seed=17041, steps=600, initial=None):
        modules = sorted(set(modules))
        with self.transaction():
            cut = self.cut(modules)
            rows = [field_values(self.source(module)["body"]) for module in modules]
        codebook = {field: sorted({row[field] for row in rows}) for field in FIELDS}
        if any(not 0 < len(codebook[field]) <= 2**width for field, width in zip(FIELDS, WIDTHS)):
            raise Refused("source vocabulary exceeds the declared field codec")
        # A changing vocabulary is a new encoding. Reusing a different codebook's
        # optimizer would silently change the meaning of old output bits.
        prior_model = None
        if initial is not None and initial["codebook"] == codebook and initial["modules"] == modules:
            prior_model = MLP.from_export(initial["checkpoint"])
        X = features([canonical_question(module) for module in modules], 128)
        Y = np.asarray([encode(row, codebook) for row in rows], dtype=np.float32)
        model = train_mlp(X, Y, hidden=32, steps=steps, seed=seed, initial=prior_model)
        serving, checkpoint = model.export(), model.export(include_optimizer=True)
        logits = predict_export(serving, X)
        if any(decode(logit, codebook) != {field: row[field] for field in FIELDS}
               for logit, row in zip(logits, rows)) or float(np.abs(logits).min()) < 1.0:
            raise Refused("candidate failed the canonical reconstruction gate")
        return dict(schema="hepta.memory.document-field-cell.v1", modules=modules, codebook=codebook,
                    cut=cut, serving=serving, checkpoint=checkpoint, minimum_margin=1.0,
                    continuation=prior_model is not None, training_receipt=model.receipt,
                    canonical_reconstruction=dict(queries=len(rows), exact=len(rows),
                                                  minimum_margin=float(np.abs(logits).min())))

    def stage(self, candidate, *, boundary_hook=None):
        # The serving object carries codebook/address metadata but no source
        # field values, target map, decoded-answer cache or optimizer moments.
        serving = {k: candidate[k] for k in ("schema", "modules", "codebook", "cut", "minimum_margin")}
        serving["model"] = candidate["serving"]
        checkpoint = candidate["checkpoint"]
        blobs = {"serving.json": canonical(serving), "checkpoint.json": canonical(checkpoint),
                 "training.json": canonical({k: candidate[k] for k in
                                               ("training_receipt", "canonical_reconstruction", "continuation")})}
        inventory = {name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                     for name, data in blobs.items()}
        artifact = digest(inventory)
        directory = self.root / "artifacts" / artifact
        if directory.exists():
            self.load(artifact)
            return artifact
        pending = Path(tempfile.mkdtemp(prefix=".staging-", dir=directory.parent))
        try:
            for name, data in blobs.items():
                write_durable(pending / name, data)
            write_durable(pending / "manifest.json", canonical(inventory))
            for path in (pending, directory.parent):
                descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            if boundary_hook is not None:
                boundary_hook("before_rename")
            try:
                pending.rename(directory)
            except OSError:
                # Another retry may have installed exactly the same immutable
                # object. Only a complete, verified destination is reusable.
                if not directory.is_dir():
                    raise
                self.load(artifact)
            descriptor = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if boundary_hook is not None:
                boundary_hook("after_rename")
        finally:
            if pending.exists():
                shutil.rmtree(pending)
        self.load(artifact)
        return artifact

    def load(self, artifact):
        if not re.fullmatch("[0-9a-f]{64}", artifact):
            raise Refused("invalid immutable artifact address")
        directory = self.root / "artifacts" / artifact
        if directory.is_symlink():
            raise Refused("linked artifact directory")
        names = {"serving.json", "checkpoint.json", "training.json"}
        if {path.name for path in directory.iterdir()} != names | {"manifest.json"}:
            raise Refused("incomplete or unexpected artifact directory inventory")
        if (directory / "manifest.json").is_symlink():
            raise Refused("linked artifact manifest")
        manifest = json.loads((directory / "manifest.json").read_text())
        if set(manifest) != names or digest(manifest) != artifact:
            raise Refused("artifact inventory identity mismatch")
        loaded = {}
        for name in sorted(names):
            path = directory / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size != manifest[name]["bytes"]:
                raise Refused("artifact file inventory mismatch")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != manifest[name]["sha256"]:
                raise Refused("artifact bytes changed")
            loaded[name] = json.loads(raw)
        serving = loaded["serving.json"]
        MLP.from_export(serving["model"])
        optimizer = MLP.from_export(loaded["checkpoint.json"])
        if optimizer.export()["parameter_sha256"] != serving["model"]["parameter_sha256"]:
            raise Refused("optimizer and serving tensors differ")
        return loaded

    def publish(self, cell, artifact):
        serving = self.load(artifact)["serving.json"]
        with self.transaction():
            if self.cut(serving["modules"]) != serving["cut"]:
                raise Refused("source changed after fitting; publication denied")
            vectors = features([canonical_question(module) for module in serving["modules"]],
                               serving["model"]["dimension"])
            logits = predict_export(serving["model"], vectors)
            for module, row in zip(serving["modules"], logits):
                expected = field_values(self.source(module)["body"])
                if (decode(row, serving["codebook"]) != {field: expected[field] for field in FIELDS} or
                        float(np.abs(row).min()) < serving["minimum_margin"]):
                    raise Refused("candidate fails current source reconstruction at publication")
            old = self.db.execute("SELECT epoch FROM releases WHERE cell=?", (cell,)).fetchone()
            epoch = old["epoch"] + 1 if old is not None else 1
            self.db.execute("INSERT INTO releases VALUES (?,?,?) ON CONFLICT(cell) "
                            "DO UPDATE SET artifact=excluded.artifact,epoch=excluded.epoch", (cell, artifact, epoch))
        return epoch

    def read(self, cell, question):
        # The transaction is the answer's freshness point: no concurrent source
        # correction can commit between checking the full fitted cut and release.
        with self.transaction():
            selected = self.db.execute("SELECT * FROM releases WHERE cell=?", (cell,)).fetchone()
            if selected is None:
                raise Refused("cell is unpublished")
            serving = self.load(selected["artifact"])["serving.json"]
            if self.cut(serving["modules"]) != serving["cut"]:
                raise Refused("source correction invalidated this fitted cell")
            module = resolve(question, serving["modules"])
            if module is None:
                raise Refused("address or requested operation is outside written support")
            vector = features([canonical_question(module)], serving["model"]["dimension"])
            logits = predict_export(serving["model"], vector)[0]
            answer = decode(logits, serving["codebook"])
            if answer is None or float(np.abs(logits).min()) < serving["minimum_margin"]:
                raise Refused("decoded field or model confidence is outside the release contract")
            return dict(module=module, fields=answer, logits=logits.tolist(), epoch=selected["epoch"],
                        artifact=selected["artifact"], parameter_sha256=serving["model"]["parameter_sha256"],
                        source_cut_sha256=digest(serving["cut"]),
                        addressing="explicit-public-scope-parser-plus-canonical-model-input")

