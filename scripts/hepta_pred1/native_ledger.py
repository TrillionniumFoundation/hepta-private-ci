"""Read-only TaskFlow facts and immutable PRED snapshot/readback joins.

Database provenance, identity and clock ID are trusted host inputs, not
authenticated here. Native timestamps remain raw metadata; availability is
stamped after collection using the collector's monotonic clock. Keep clock_id
fixed across process recovery and change it after reboot. Dispatch boundaries
and owner settlements never become execution, goal, duration or cost labels.
"""

from contextlib import closing
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from time import monotonic

import numpy as np

from .action_history import (
    ActionEvent,
    EncodedHistory,
    OTHER_VALUES,
    Stage,
    TIME_VALUES,
)
from .contracts import Evidence, ObservationStatus

MAX_BYTES = 1_048_576
IDENTITY_FIELDS = (
    "owner_agent_id",
    "run_id",
    "step_id",
    "attempt",
    "intent_digest",
    "payload_digest",
    "binding_digest",
    "destination_id",
)
KEY_FIELDS = IDENTITY_FIELDS[:4]
ATTEMPT_FIELDS = IDENTITY_FIELDS + (
    "authority_epoch",
    "grant_id",
    "grant_nonce_digest",
    "record_command_id",
    "started_at_ms",
)
OBSERVATION_FIELDS = KEY_FIELDS + ("observation", "evidence_digest", "observed_at_ms")
TABLE_FIELDS = {
    "attempts": ATTEMPT_FIELDS,
    "observations": OBSERVATION_FIELDS,
    "reconciliations": OBSERVATION_FIELDS,
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, low=0, high=2**63 - 1):
    _require(type(value) is int and low <= value <= high, "invalid bounded integer")


def _text(value, limit=256):
    _require(
        type(value) is str and 0 < len(value) <= limit and value.strip() == value,
        "invalid bounded identity",
    )


def _time(value):
    _require(
        type(value) in (float, int) and math.isfinite(value) and value >= 0,
        "invalid collector time",
    )


def _digest(value):
    _require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        "invalid SHA256",
    )


def _identity(value):
    _require(
        type(value) is dict and set(value) == set(IDENTITY_FIELDS),
        "identity fields differ",
    )
    for name, item in value.items():
        if name == "attempt":
            _integer(item, 1, 1_000_000)
        elif name.endswith("_digest"):
            _digest(item)
        else:
            _text(item, 128 if name == "destination_id" else 256)


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True)
class Artifact:
    """Immutable bytes; reads return copies. Hashes detect corruption, not forgery."""

    encoded: bytes

    def __post_init__(self):
        _require(
            type(self.encoded) is bytes and len(self.encoded) <= MAX_BYTES,
            "artifact must contain bounded immutable bytes",
        )
        value = json.loads(self.encoded)
        _require(
            type(value) is dict and set(value) == {"payload", "sha256"},
            "invalid envelope",
        )
        _require(
            value["sha256"] == sha256(_canonical(value["payload"])).hexdigest()
            and self.encoded == _canonical(value),
            "artifact hash or canonical bytes differ",
        )

    @property
    def payload(self):
        return json.loads(self.encoded)["payload"]

    @property
    def digest(self):
        return sha256(self.encoded).hexdigest()

    @classmethod
    def make(cls, payload):
        encoded = _canonical(
            {"payload": payload, "sha256": sha256(_canonical(payload)).hexdigest()}
        )
        _require(len(encoded) <= MAX_BYTES, "artifact exceeds byte limit")
        return cls(encoded)

    @classmethod
    def read(cls, path):
        with Path(path).open("rb") as stream:
            encoded = stream.read(MAX_BYTES + 1)
        return cls(encoded)

    def save(self, path):
        # xb refuses existing files and symlinks, including an old snapshot.
        with Path(path).open("xb") as stream:
            stream.write(self.encoded)
            stream.flush()
            os.fsync(stream.fileno())


def _collection(artifact):
    _require(isinstance(artifact, Artifact), "expected immutable artifact")
    p = artifact.payload
    _require(p.get("schema") == "pred1-native-collection-v1", "wrong collection schema")
    _identity(p["identity"])
    _text(p["clock_id"])
    _time(p["available_at"])
    _integer(p["cursor"])
    rows = p["rows"]
    _require(
        type(rows) is dict and set(rows) == set(TABLE_FIELDS), "wrong native tables"
    )
    for name, fields in TABLE_FIELDS.items():
        records = rows[name]
        _require(
            type(records) is list and len(records) <= 1, "duplicate native identity"
        )
        for row in records:
            _require(
                type(row) is dict and set(row) == set(fields),
                "native row columns differ",
            )
            _require(
                all(row[k] == p["identity"][k] for k in KEY_FIELDS),
                "native key differs",
            )
            if name == "attempts":
                _require(
                    all(row[k] == p["identity"][k] for k in IDENTITY_FIELDS),
                    "native identity differs",
                )
                _integer(row["authority_epoch"], 1)
                _text(row["grant_id"], 128)
                _text(row["record_command_id"])
                _digest(row["grant_nonce_digest"])
                _integer(row["started_at_ms"])
            else:
                valid = {"proven_absent", "succeeded", "failed"}
                if name == "observations":
                    valid.add("indeterminate")
                _require(row["observation"] in valid, "invalid owner settlement")
                _digest(row["evidence_digest"])
                _integer(row["observed_at_ms"])
    _require(
        bool(rows["attempts"]) or not (rows["observations"] or rows["reconciliations"]),
        "orphan native observation",
    )
    _require(
        not rows["reconciliations"]
        or (
            rows["observations"]
            and rows["observations"][0]["observation"] == "indeterminate"
        ),
        "reconciliation requires original indeterminate observation",
    )
    return p


def collect_native(database, *, identity, clock_id, cursor):
    """Collect one identity in one WAL-aware read-only SQLite transaction.

    No database is created or migrated. SQLite may manage reader locks in
    shared memory; no owner record is written. Cursor comes from the host's
    single arrival sequencer, shared with the numerical history encoder.
    """
    _identity(identity)
    _text(clock_id)
    _integer(cursor)
    path = Path(database).resolve(strict=True)
    _require(path.is_file(), "native database must be an existing file")
    rows = {}
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", timeout=5, uri=True)
    ) as connection:
        limit = getattr(connection, "setlimit", None)
        category = getattr(sqlite3, "SQLITE_LIMIT_LENGTH", None)
        if limit is not None and category is not None:
            limit(category, MAX_BYTES)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        for name, fields in TABLE_FIELDS.items():
            table = "taskflow_effect_dispatch_" + name
            where = " AND ".join(k + " = ?" for k in KEY_FIELDS)
            # Always bound transfer into Python, including Python 3.10 without
            # Connection.setlimit. Native strings allow at most 256 Unicode
            # characters (1024 UTF-8 bytes). NULL fails the structural checks.
            projection = ",".join(
                f"CASE WHEN length(CAST({field} AS BLOB)) <= 1024 THEN {field} ELSE NULL END AS {field}"
                for field in fields
            )
            query = f"SELECT {projection} FROM {table} WHERE {where} LIMIT 2"
            rows[name] = [
                dict(row)
                for row in connection.execute(
                    query, tuple(identity[k] for k in KEY_FIELDS)
                )
            ]
        connection.rollback()
    artifact = Artifact.make(
        {
            "schema": "pred1-native-collection-v1",
            "identity": identity,
            "clock_id": clock_id,
            "cursor": cursor,
            "available_at": monotonic(),
            "database_path": str(path),
            "rows": rows,
            "scope": "structural native owner facts; no authentication or effect labels",
        }
    )
    _collection(artifact)
    return artifact


def _snapshot(artifact):
    """Validate stored structure, not encoder provenance or native action mapping."""
    _require(isinstance(artifact, Artifact), "expected immutable snapshot")
    p = artifact.payload
    fields = {
        "schema",
        "identity",
        "clock_id",
        "cursor",
        "decision_at",
        "features",
        "feature_names",
        "event_references",
        "collection",
        "collection_digest",
        "scope",
    }
    _require(type(p) is dict and set(p) == fields, "snapshot fields differ")
    _require(p["schema"] == "pred1-native-snapshot-v1", "wrong snapshot schema")
    _identity(p["identity"])
    _text(p["clock_id"])
    _integer(p["cursor"])
    _time(p["decision_at"])
    _text(p["scope"])
    _require(type(p["collection"]) is dict, "invalid snapshot collection")
    collection = Artifact.make(p["collection"])
    c = _collection(collection)
    _require(collection.digest == p["collection_digest"], "snapshot collection differs")
    _require(p["identity"] == c["identity"], "snapshot identity differs")
    _require(p["clock_id"] == c["clock_id"], "snapshot clock differs")
    _require(p["cursor"] == c["cursor"], "snapshot cursor differs")
    _require(p["decision_at"] >= c["available_at"], "collection was not yet available")
    names = p["feature_names"]
    _require(type(names) is list and 1 <= len(names) <= 256, "invalid feature names")
    for name in names:
        _text(name)
    actions = [name for name in names if name.startswith("action:")]
    _require(1 <= len(actions) <= 64, "invalid action feature count")
    for name in actions:
        _text(name.removeprefix("action:"))
    expected = actions + ["action_slot"]
    expected += ["stage:" + stage.value for stage in Stage] + ["stage:decision"]
    expected += ["source:real", "source:simulator"]
    expected += ["status:" + status.value for status in ObservationStatus]
    expected += [
        "time_kind:" + kind
        for kind in ("exact", "interval", "right_censored", "unobserved")
    ]
    expected += [
        name + suffix
        for name in TIME_VALUES + OTHER_VALUES
        for suffix in ("", "_known")
    ]
    _require(
        names == expected and len(set(names)) == len(names), "feature schema differs"
    )
    references = p["event_references"]
    _require(
        type(references) is list and len(references) <= 255, "invalid event references"
    )
    prior_sequence, prior_arrival = -1, 0
    for reference in references:
        _require(
            type(reference) is dict
            and set(reference)
            == {
                "sequence",
                "observed_at",
                "record_ref",
                "action_id",
                "candidate_id",
            },
            "event reference fields differ",
        )
        _integer(reference["sequence"])
        _time(reference["observed_at"])
        _require(
            prior_sequence < reference["sequence"] <= p["cursor"]
            and prior_arrival <= reference["observed_at"] <= p["decision_at"],
            "invalid snapshot event order or visibility",
        )
        for name in ("record_ref", "action_id", "candidate_id"):
            _text(reference[name])
        prior_sequence, prior_arrival = reference["sequence"], reference["observed_at"]
    rows = p["features"]
    _require(
        type(rows) is list and len(rows) == len(references) + 1,
        "snapshot row count differs",
    )
    for row in rows:
        _require(
            type(row) is list
            and len(row) == len(names)
            and all(
                type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
                for v in row
            ),
            "invalid numerical snapshot",
        )
    decision = names.index("stage:decision")
    _require(
        rows[-1][decision] == 1 and all(row[decision] == 0 for row in rows[:-1]),
        "snapshot decision row differs",
    )
    return p


def freeze_snapshot(path, snapshot, collection):
    """Persist existing causal encoder output without inventing native phases."""
    c = _collection(collection)
    _require(isinstance(snapshot, EncodedHistory), "expected encoded causal history")
    _integer(snapshot.through_sequence)
    _require(snapshot.through_sequence == c["cursor"], "snapshot cursor differs")
    _time(snapshot.decision_at)
    _require(
        snapshot.decision_at >= c["available_at"], "collection was not yet available"
    )
    x = snapshot.features
    _require(
        isinstance(x, np.ndarray)
        and x.ndim == 2
        and 1 <= x.shape[0] <= 256
        and 1 <= x.shape[1] <= 256
        and x.dtype.kind in "fiu"
        and np.isfinite(x).all()
        and ((x >= 0) & (x <= 1)).all(),
        "invalid numerical snapshot",
    )
    names = snapshot.feature_names
    _require(
        len(names) == x.shape[1] and len(set(names)) == len(names),
        "feature names differ",
    )
    for name in names:
        _text(name)
    _require(
        type(snapshot.events) is tuple
        and len(snapshot.events) <= 255
        and all(isinstance(event, ActionEvent) for event in snapshot.events),
        "invalid encoded events",
    )
    references = []
    for e in snapshot.events:
        _require(
            e.sequence <= c["cursor"] and e.observed_at <= snapshot.decision_at,
            "future event in encoded snapshot",
        )
        references.append(
            {
                "sequence": e.sequence,
                "observed_at": e.observed_at,
                "record_ref": e.record_ref,
                "action_id": e.action_id,
                "candidate_id": e.candidate_id,
            }
        )
    artifact = Artifact.make(
        {
            "schema": "pred1-native-snapshot-v1",
            "identity": c["identity"],
            "clock_id": c["clock_id"],
            "cursor": c["cursor"],
            "decision_at": snapshot.decision_at,
            "features": x.tolist(),
            "feature_names": list(names),
            "event_references": references,
            "collection": c,
            "collection_digest": collection.digest,
            "scope": "frozen numerical inputs; ledger supplies no accepted/executed phase",
        }
    )
    _snapshot(artifact)
    artifact.save(path)
    return artifact


def join_readback(path, snapshot_path, later):
    """Retain later owner settlement separately; outcome/time/cost stay unknown.

    A later cursor at the same clock tick is valid. Earlier snapshots are never
    rewritten. Native succeeded/failed settles only the owner contract and
    does not establish independent business-effect supervision.
    """
    frozen = Artifact.read(snapshot_path)
    p, new = _snapshot(frozen), _collection(later)
    old = p["collection"]
    _require(
        p["identity"] == old["identity"] == new["identity"], "readback identity differs"
    )
    _require(
        p["clock_id"] == old["clock_id"] == new["clock_id"], "collector clock differs"
    )
    _require(
        p["cursor"] == old["cursor"] and new["cursor"] > p["cursor"],
        "readback cursor is not later",
    )
    _time(p["decision_at"])
    _require(
        old["available_at"] <= p["decision_at"] <= new["available_at"],
        "readback availability is not later",
    )
    for name in TABLE_FIELDS:
        _require(
            not old["rows"][name] or old["rows"][name] == new["rows"][name],
            "previous immutable native facts changed",
        )
    settlement = new["rows"]["reconciliations"] or new["rows"]["observations"]
    artifact = Artifact.make(
        {
            "schema": "pred1-native-readback-v1",
            "identity": new["identity"],
            "snapshot_digest": frozen.digest,
            "collection_digest": later.digest,
            "collection": new,
            "clock_id": new["clock_id"],
            "cursor": new["cursor"],
            "available_at": new["available_at"],
            "target_domain": "OWNER_SETTLEMENT",
            "raw_owner_settlement": settlement[0] if settlement else None,
            "effect_evidence": asdict(
                Evidence(
                    observation_status=ObservationStatus.RECEIPT_MISSING,
                    observed_at=new["available_at"],
                )
            ),
            "business_outcome": None,
            "effect_duration": None,
            "physical_cost": None,
            "training_outcome_available": False,
            "scope": "owner settlement only; missing effect readback supplies no outcome label",
        }
    )
    artifact.save(path)
    return artifact
