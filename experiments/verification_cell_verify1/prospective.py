"""Frozen-roster observation ledger; hashes and call order are not trusted clocks.

The host authenticates separate terminal labels. A distinct issuer name does not
establish independent custody. No forecast, journal or label grants authority.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3

from .contracts import _pairs, _require, _sha, _text, canonical_json, digest
from .shadow_risk import (
    DISPOSITIONS,
    Prediction,
    Snapshot,
    Target,
    TerminalLabel,
    evaluate_shadow,
)


MAX_ATTEMPTS = 1000
MAX_EVENTS = 10000
MAX_BODY = 65536


@dataclass(frozen=True)
class FrozenAttempt:
    trajectory_id: str
    source_group: str
    subject_sha256: str

    def __post_init__(self):
        for name in ("trajectory_id", "source_group"):
            _text(getattr(self, name), name)
            _require(len(getattr(self, name)) <= 256, "identity too long")
        _sha(self.subject_sha256, "subject_sha256")


def _manifest(
    target,
    roster,
    frontiers,
    risk_model_sha256,
    checker_model_sha256,
    scheduler_sha256,
    producer_id,
    evaluator_id,
    evaluator_version_sha256,
):
    _require(type(target) is Target, "exact target required")
    _require(
        type(roster) in (tuple, list) and 0 < len(roster) <= MAX_ATTEMPTS,
        "bounded nonempty roster required",
    )
    _require(all(type(row) is FrozenAttempt for row in roster), "invalid roster")
    _require(
        len({row.trajectory_id for row in roster}) == len(roster),
        "duplicate trajectory",
    )
    _require(
        type(frontiers) in (tuple, list) and 0 < len(frontiers) <= 8,
        "one to eight frontiers required",
    )
    _require(
        all(type(step) is int and 0 <= step < target.horizon_end for step in frontiers)
        and tuple(sorted(set(frontiers))) == tuple(frontiers),
        "invalid forecast frontiers",
    )
    identities = dict(
        risk_model_sha256=risk_model_sha256,
        checker_model_sha256=checker_model_sha256,
        scheduler_sha256=scheduler_sha256,
        evaluator_version_sha256=evaluator_version_sha256,
    )
    for name, value in identities.items():
        _sha(value, name)
    _text(producer_id, "producer_id")
    _text(evaluator_id, "evaluator_id")
    _require(producer_id != evaluator_id, "producer cannot be label evaluator")
    return dict(
        schema="hepta.verify.prospective.v1",
        target=asdict(target),
        roster=[asdict(row) for row in roster],
        frontiers=list(frontiers),
        producer_id=producer_id,
        evaluator_id=evaluator_id,
        **identities,
    )


class ShadowJournal:
    """Transactional append-only API for a trusted host-owned local path.

    Retain manifest and ledger roots externally. SQLite order does not prove
    wall time or protect against the database owner rewriting the whole run.
    """

    def __init__(self, path, *, expected_manifest_sha256=None):
        self.path = Path(path).resolve()
        _require(self.path.is_file(), "existing journal required")
        if expected_manifest_sha256 is not None:
            _sha(expected_manifest_sha256, "expected_manifest_sha256")
        self.manifest_sha256 = expected_manifest_sha256
        with self._transaction() as connection:
            manifest, *_ = self._read(connection)
        self.manifest_sha256 = digest(manifest)

    @classmethod
    def create(cls, path, **configuration):
        manifest = _manifest(**configuration)
        path = Path(path).absolute()
        with path.open("xb"):
            pass
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute(
                    "CREATE TABLE frozen (body TEXT NOT NULL, sha TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE events (seq INTEGER PRIMARY KEY, body TEXT NOT NULL, sha TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO frozen VALUES (?, ?)",
                    (canonical_json(manifest), digest(manifest)),
                )
        finally:
            connection.close()
        return cls(path, expected_manifest_sha256=digest(manifest))

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=rw", uri=True, timeout=30
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read(self, connection):
        rows = connection.execute("SELECT body, sha FROM frozen LIMIT 2").fetchall()
        _require(len(rows) == 1, "invalid frozen manifest")
        manifest = json.loads(rows[0][0], object_pairs_hook=_pairs)
        _require(
            type(manifest) is dict
            and set(manifest)
            == {
                "schema",
                "target",
                "roster",
                "frontiers",
                "producer_id",
                "evaluator_id",
                "risk_model_sha256",
                "checker_model_sha256",
                "scheduler_sha256",
                "evaluator_version_sha256",
            },
            "invalid manifest fields",
        )
        configuration = {
            key: value for key, value in manifest.items() if key != "schema"
        }
        configuration["target"] = Target(**configuration["target"])
        configuration["roster"] = tuple(
            FrozenAttempt(**row) for row in configuration["roster"]
        )
        _require(manifest == _manifest(**configuration), "manifest schema mismatch")
        root = rows[0][1]
        _require(digest(manifest) == root, "manifest digest mismatch")
        _require(
            self.manifest_sha256 is None or root == self.manifest_sha256,
            "frozen manifest identity changed",
        )
        predictions, finishes, labels, steps = [], {}, {}, {}
        events = connection.execute(
            "SELECT seq, body, sha FROM events ORDER BY seq LIMIT ?", (MAX_EVENTS + 1,)
        ).fetchall()
        _require(len(events) <= MAX_EVENTS, "event limit exceeded")
        for expected, (seq, body, sha) in enumerate(events, 1):
            _require(
                seq == expected and len(body) <= MAX_BODY, "invalid event sequence/size"
            )
            event = json.loads(body, object_pairs_hook=_pairs)
            _require(
                type(event) is dict
                and set(event) == {"kind", "value", "previous_sha256"}
                and type(event["value"]) is dict
                and event["previous_sha256"] == root
                and digest(event) == sha,
                "event digest mismatch",
            )
            self._apply(manifest, event, predictions, finishes, labels, steps)
            root = sha
        return manifest, predictions, finishes, labels, root, len(events)

    @staticmethod
    def _apply(manifest, event, predictions, finishes, labels, steps):
        kind, value = event["kind"], event["value"]
        if kind == "prediction":
            snapshot = value["snapshot"]
            row = Snapshot(**{**snapshot, "target": Target(**snapshot["target"])})
            prediction = Prediction(row, value["probability"], value["model_sha256"])
            _require(
                set(value) == {"snapshot", "probability", "model_sha256"},
                "invalid prediction fields",
            )
        elif kind == "label":
            row = TerminalLabel(**{**value, "target": Target(**value["target"])})
        elif kind == "finish":
            _require(
                set(value) == {"trajectory_id", "disposition"}, "invalid finish fields"
            )
            row = None
        else:
            raise ValueError("unknown event kind")
        trajectory = row.trajectory_id if row is not None else value["trajectory_id"]
        roster = {item["trajectory_id"]: item for item in manifest["roster"]}
        _require(trajectory in roster, "attempt is outside frozen roster")
        if row is not None:
            _require(
                {name: getattr(row, name) for name in roster[trajectory]}
                == roster[trajectory]
                and asdict(row.target) == manifest["target"],
                "frozen attempt/target mismatch",
            )
        if kind == "prediction":
            _require(trajectory not in finishes, "forecast after host completion")
            _require(
                prediction.model_sha256 == manifest["risk_model_sha256"],
                "risk model changed",
            )
            step = row.observed_step
            _require(
                step in manifest["frontiers"] and step > steps.get(trajectory, -1),
                "unplanned, duplicate or reversed forecast frontier",
            )
            steps[trajectory] = step
            predictions.append(prediction)
        elif kind == "finish":
            _require(trajectory not in finishes, "duplicate host completion")
            _require(value["disposition"] in DISPOSITIONS, "invalid disposition")
            finishes[trajectory] = value["disposition"]
        else:
            _require(
                trajectory in finishes and trajectory not in labels,
                "label before completion or duplicate label",
            )
            _require(
                row.disposition == finishes[trajectory], "label disposition mismatch"
            )
            labels[trajectory] = row

    def _append(self, kind, value, expected_manifest=None):
        with self._transaction() as connection:
            manifest, predictions, finishes, labels, root, count = self._read(
                connection
            )
            _require(
                expected_manifest is None or digest(manifest) == expected_manifest,
                "manifest changed during authentication",
            )
            _require(count < MAX_EVENTS, "event limit exceeded")
            event = dict(kind=kind, value=value, previous_sha256=root)
            steps = {}
            for prediction in predictions:
                steps[prediction.snapshot.trajectory_id] = (
                    prediction.snapshot.observed_step
                )
            self._apply(manifest, event, predictions, finishes, labels, steps)
            body = canonical_json(event)
            _require(len(body) <= MAX_BODY, "event body too large")
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?)", (count + 1, body, digest(event))
            )

    def record(self, prediction):
        _require(type(prediction) is Prediction, "exact prediction required")
        self._append("prediction", asdict(prediction))

    def finish(self, trajectory_id, disposition):
        _text(trajectory_id, "trajectory_id")
        _require(
            type(disposition) is str and disposition in DISPOSITIONS,
            "invalid disposition",
        )
        self._append(
            "finish", dict(trajectory_id=trajectory_id, disposition=disposition)
        )

    def label(self, label, *, evaluator_id, authenticate):
        """Authenticate exact label, issuer version and manifest via the host.

        The callback must validate original evidence. It is called outside the
        writer transaction; its literal True is a host trust decision, not proof
        of evaluator independence. A changed manifest refuses publication.
        Callback attestations/signatures are not retained or reverified on reopen.
        """
        _require(type(label) is TerminalLabel, "exact terminal label required")
        with self._transaction() as connection:
            manifest, *_ = self._read(connection)
        _require(
            evaluator_id == manifest["evaluator_id"], "unregistered label evaluator"
        )
        root = digest(manifest)
        _require(
            callable(authenticate)
            and authenticate(
                evaluator_id, label, manifest["evaluator_version_sha256"], root
            )
            is True,
            "label authentication failed",
        )
        self._append("label", asdict(label), expected_manifest=root)

    def report(self):
        with self._transaction() as connection:
            manifest, predictions, finishes, labels, root, count = self._read(
                connection
            )
        roster = {row["trajectory_id"] for row in manifest["roster"]}
        _require(
            set(finishes) == roster and set(labels) == roster,
            "incomplete roster; retain explicit missing labels for every attempt",
        )
        result = evaluate_shadow(predictions, list(labels.values()))
        for step in manifest["frontiers"]:
            metrics = result["by_step"].setdefault(str(step), {})
            metrics["missing_prediction_count"] = len(roster) - sum(
                row.snapshot.observed_step == step for row in predictions
            )
        result.update(
            manifest=manifest,
            manifest_sha256=digest(manifest),
            ledger_sha256=root,
            event_count=count,
            prospective_order_enforced=True,
            wall_clock_prospectiveness_proved=False,
            independent_evaluation_established=False,
            full_physical_cost_complete=False,
            scientific_admission="HOLD",
        )
        return result
