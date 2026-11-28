"""Durable per-peer fixed-feature sums; research data binding, not authentication.

Each peer keeps its own ledger. No migration across feature epochs is implicit.
The exact JSON canonical bytes are exported for readers in other languages.
"""

from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

import numpy as np

from .pft_linear import solve_normal


DIGEST_FIELDS = (
    "parent_model_sha256",
    "feature_program_sha256",
    "normalization_sha256",
    "objective_sha256",
    "time_semantics_sha256",
)
CONTRACT_FIELDS = set(DIGEST_FIELDS) | {
    "schema",
    "model_family",
    "epoch",
    "dimension",
    "outputs",
    "regularizer",
    "dtype",
    "aggregation",
    "statistics_validation",
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True
    ).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def checked_contract(value):
    if (
        type(value) is not dict
        or set(value) != CONTRACT_FIELDS
        or any(not valid_digest(value[k]) for k in DIGEST_FIELDS)
    ):
        raise ValueError("contract fields or digest invalid")
    for key, upper in (("dimension", 1024), ("outputs", 32), ("epoch", 2**63 - 1)):
        if (
            type(value[key]) is not int
            or not (0 if key == "epoch" else 1) <= value[key] <= upper
        ):
            raise ValueError("contract integer out of range")
    regularizer = value["regularizer"]
    if (
        type(regularizer) not in (int, float)
        or not math.isfinite(regularizer)
        or regularizer <= 0
        or value["schema"] != "pft-online-statistics-v1"
        or value["model_family"] != "hcsn-pft-readout-research-v1"
        or value["dtype"] != "float64"
        or value["aggregation"] != "sum-f64-canonical-batch-id"
        or value["statistics_validation"] != "augmented-psd-rtol-1e-10-v1"
    ):
        raise ValueError("unsupported contract or regularizer")
    return json.loads(canonical(value))


def make_packet(contract, batch_id, source_sha256, sample_ids, x, y):
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    body = dict(
        contract_sha256=digest(checked_contract(contract)),
        batch_id=batch_id,
        source_sha256=source_sha256,
        sample_ids=sorted(sample_ids),
        count=len(x),
        gram=(x.T @ x).tolist(),
        rhs=(x.T @ y).tolist(),
        yty=(y.T @ y).tolist(),
    )
    packet = dict(body=body, payload_sha256=digest(body))
    validate_packet(packet, contract)
    return packet


def validate_packet(packet, contract):
    if (
        type(packet) is not dict
        or set(packet) != {"body", "payload_sha256"}
        or type(packet["body"]) is not dict
    ):
        raise ValueError("invalid contribution envelope")
    body = packet["body"]
    if (
        set(body)
        != {
            "contract_sha256",
            "batch_id",
            "source_sha256",
            "sample_ids",
            "count",
            "gram",
            "rhs",
            "yty",
        }
        or packet["payload_sha256"] != digest(body)
        or body["contract_sha256"] != digest(contract)
        or not valid_digest(body["source_sha256"])
        or not isinstance(body["batch_id"], str)
        or re.fullmatch("[A-Za-z0-9_.-]{1,128}", body["batch_id"]) is None
    ):
        raise ValueError("incompatible or changed contribution")
    count, ids = body["count"], body["sample_ids"]
    if (
        type(count) is not int
        or not 1 <= count <= 100000
        or not isinstance(ids, list)
        or len(ids) != count
        or any(not valid_digest(v) for v in ids)
        or ids != sorted(set(ids))
    ):
        raise ValueError("sample identities and count disagree")
    d, m = contract["dimension"], contract["outputs"]
    g, h, t = (np.asarray(body[k], dtype=np.float64) for k in ("gram", "rhs", "yty"))
    if g.shape != (d, d) or h.shape != (d, m) or t.shape != (m, m):
        raise ValueError("statistics dimensions disagree")
    augmented = np.block([[g, h], [h.T, t]])
    if not np.isfinite(augmented).all() or not np.allclose(
        augmented, augmented.T, rtol=1e-11, atol=1e-11
    ):
        raise ValueError("nonfinite or asymmetric statistics")
    eigenvalues = np.linalg.eigvalsh((augmented + augmented.T) / 2)
    if eigenvalues[0] < -1e-10 * max(1.0, float(np.max(np.abs(eigenvalues)))):
        raise ValueError("statistics are not positive semidefinite")
    return g, h, t


class StatisticsLedger:
    """A single representation epoch with exactly-once declared sample admission."""

    def __init__(self, path, contract):
        self.path = str(Path(path))
        self.contract = checked_contract(contract)
        self.contract_hash = digest(self.contract)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS contract (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body BLOB NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, digest TEXT NOT NULL, body BLOB NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS samples (id TEXT PRIMARY KEY, batch TEXT NOT NULL REFERENCES batches(id))"
            )
            db.execute(
                "INSERT OR IGNORE INTO contract VALUES (1, ?)",
                (canonical(self.contract),),
            )
            if db.execute("SELECT body FROM contract WHERE singleton=1").fetchone()[
                0
            ] != canonical(self.contract):
                raise ValueError("ledger belongs to a different contract/epoch")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def state(self, db=None):
        if db is None:
            with self.connect() as connection:
                return self.state(connection)
        rows = db.execute("SELECT id,digest FROM batches ORDER BY id").fetchall()
        material = dict(contract_sha256=self.contract_hash, batches=rows)
        return dict(head=digest(material), revision=len(rows), material=material)

    def append(self, packet, expected_head, *, max_batches=None):
        validate_packet(packet, self.contract)
        if max_batches is not None and (
            type(max_batches) is not int or max_batches <= 0
        ):
            raise ValueError("batch bound must be a positive integer")
        body, packet_hash = packet["body"], packet["payload_sha256"]
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                state = self.state(db)
                if max_batches is not None and state["revision"] > max_batches:
                    raise ValueError("research exchange batch bound exceeded")
                previous = db.execute(
                    "SELECT digest FROM batches WHERE id=?", (body["batch_id"],)
                ).fetchone()
                if previous:
                    if previous[0] != packet_hash:
                        raise ValueError("batch ID conflicts with different bytes")
                    return dict(status="idempotent", **state)
                if max_batches is not None and state["revision"] >= max_batches:
                    raise ValueError("research exchange batch bound exceeded")
                if state["head"] != expected_head:
                    raise ValueError("stale expected head")
                db.execute(
                    "INSERT INTO batches VALUES (?,?,?)",
                    (body["batch_id"], packet_hash, canonical(body)),
                )
                db.executemany(
                    "INSERT INTO samples VALUES (?,?)",
                    [(v, body["batch_id"]) for v in body["sample_ids"]],
                )
                receipt = dict(status="accepted", **self.state(db))
            return receipt
        except sqlite3.IntegrityError as error:
            raise ValueError("sample already admitted in another batch") from error

    def snapshot(self):
        with self.connect() as db:
            db.execute("BEGIN")
            state = self.state(db)
            rows = db.execute("SELECT body,digest FROM batches ORDER BY id").fetchall()
        if not rows:
            raise ValueError("no admitted statistics")
        d, m = self.contract["dimension"], self.contract["outputs"]
        g, h, t, count = np.zeros((d, d)), np.zeros((d, m)), np.zeros((m, m)), 0
        for raw, packet_hash in rows:
            body = json.loads(raw)
            gi, hi, ti = validate_packet(
                dict(body=body, payload_sha256=packet_hash), self.contract
            )
            g += gi
            h += hi
            t += ti
            count += body["count"]
        weight = solve_normal(g, h, self.contract["regularizer"])
        if not np.isfinite(weight).all():
            raise ValueError("nonfinite candidate")
        candidate = dict(
            schema="pft-online-candidate-v1",
            contract=self.contract,
            contract_sha256=self.contract_hash,
            contract_canonical_json=canonical(self.contract).decode(),
            head=state["head"],
            revision=state["revision"],
            head_material_canonical_json=canonical(state["material"]).decode(),
            count=count,
            weight_shape=list(weight.shape),
            weight=weight.tolist(),
            weight_encoding="float64-le-c-rowmajor",
            weight_sha256=hashlib.sha256(
                np.asarray(weight, dtype="<f8").tobytes(order="C")
            ).hexdigest(),
        )
        return dict(candidate=candidate, gram=g, rhs=h, yty=t)
