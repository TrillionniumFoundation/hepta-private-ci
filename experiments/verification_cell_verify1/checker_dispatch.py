"""Durable optional-check dispatch; original owners retain effect authority."""

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import MappingProxyType

from .checker_effects import EffectsModel, _number
from .contracts import _pairs, _require, _sha, _text, canonical_json, digest
from .shadow_risk import Prediction, Snapshot, Target
from .shadow_schedule import CheckObservation, select_shadow_check


def scheduler_identity():
    names = (
        "shadow_schedule.py",
        "check_voi.py",
        "checker_effects.py",
        "checker_dispatch.py",
    )
    return digest(
        {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in names
        }
    )


@dataclass(frozen=True)
class CheckerBinding:
    checker_id: str
    version_sha256: str
    run: object

    def __post_init__(self):
        _text(self.checker_id, "checker_id")
        _sha(self.version_sha256, "version_sha256")
        _require(callable(self.run), "checker callback required")


@dataclass(frozen=True)
class CheckerReply:
    operation_id: str
    checker_id: str
    version_sha256: str
    snapshot_sha256: str
    outcome: str
    evidence_sha256: str
    actual_cost_units: float | None = None

    def __post_init__(self):
        for name in ("operation_id", "checker_id"):
            _text(getattr(self, name), name)
        for name in ("version_sha256", "snapshot_sha256", "evidence_sha256"):
            _sha(getattr(self, name), name)
        _require(
            type(self.outcome) is str and self.outcome in ("pass", "fail", "unknown"),
            "invalid checker outcome",
        )
        if self.actual_cost_units is not None:
            object.__setattr__(
                self, "actual_cost_units", _number(self.actual_cost_units)
            )


def _decode(body):
    return json.loads(body, object_pairs_hook=_pairs)


class DispatchJournal:
    """Trusted-host API, not a sandbox or proof against a database-owner rewrite.

    The host must bind each prediction to the prospective manifest roster. This
    ledger retains that manifest's digest but does not load or authenticate it.
    """

    def __init__(self, path, *, expected_config_sha256=None):
        self.path = Path(path).resolve()
        _require(self.path.is_file(), "existing dispatch ledger required")
        self.config_sha256 = expected_config_sha256
        with self._transaction() as db:
            configuration = self._configuration(db)
        self.config_sha256 = digest(configuration)
        self.configuration = MappingProxyType(configuration)

    @classmethod
    def create(
        cls,
        path,
        *,
        manifest_sha256,
        risk_model_sha256,
        checker_model_sha256,
        scheduler_sha256,
        effects_body_sha256,
    ):
        configuration = dict(
            manifest_sha256=manifest_sha256,
            risk_model_sha256=risk_model_sha256,
            checker_model_sha256=checker_model_sha256,
            scheduler_sha256=scheduler_sha256,
            effects_body_sha256=effects_body_sha256,
        )
        for name, value in configuration.items():
            _sha(value, name)
        _require(
            scheduler_sha256 == scheduler_identity(),
            "scheduler source identity mismatch",
        )
        path = Path(path).absolute()
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE frozen (body TEXT NOT NULL, sha TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE operations (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, checker TEXT, request TEXT NOT NULL, request_sha TEXT NOT NULL, result TEXT, result_sha TEXT, UNIQUE(snapshot,checker))"
            )
            db.execute(
                "CREATE TABLE budgets (snapshot TEXT PRIMARY KEY, original REAL NOT NULL, reserved REAL NOT NULL)"
            )
            db.execute(
                "INSERT INTO frozen VALUES (?, ?)",
                (canonical_json(configuration), digest(configuration)),
            )
        return cls(path, expected_config_sha256=digest(configuration))

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=30)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _configuration(self, db):
        rows = db.execute("SELECT body, sha FROM frozen LIMIT 2").fetchall()
        _require(len(rows) == 1, "invalid dispatch configuration")
        value = _decode(rows[0][0])
        _require(
            type(value) is dict
            and set(value)
            == {
                "manifest_sha256",
                "risk_model_sha256",
                "checker_model_sha256",
                "scheduler_sha256",
                "effects_body_sha256",
            },
            "invalid configuration fields",
        )
        for name, item in value.items():
            _sha(item, name)
        _require(
            digest(value) == rows[0][1]
            and (self.config_sha256 is None or self.config_sha256 == rows[0][1]),
            "configuration changed",
        )
        return value

    def _get(self, db, operation_id):
        self._configuration(db)
        row = db.execute(
            "SELECT request, request_sha, result, result_sha FROM operations WHERE id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        request = _decode(row[0])
        _require(digest(request) == row[1], "request digest mismatch")
        result = _decode(row[2]) if row[2] is not None else None
        _require(
            (result is None and row[3] is None) or digest(result) == row[3],
            "result digest mismatch",
        )
        return request, result

    @staticmethod
    def _pending(request):
        return dict(
            status="pending",
            reason="original_dispatch_outcome_unknown",
            operation_id=request["operation_id"],
            observation=None,
            request_sha256=digest(request),
            production_authority="NONE",
        )

    def dispatch_one(
        self,
        prediction,
        effects,
        observations,
        actions,
        losses,
        remaining_budget,
        *,
        hard_checks_complete,
        operation_id,
        checkers,
        read_snapshot,
    ):
        started = time.perf_counter_ns()
        _text(operation_id, "operation_id")
        _require(
            type(prediction) is Prediction and type(effects) is EffectsModel,
            "typed models required",
        )
        _require(
            type(checkers) in (tuple, list)
            and len(checkers) <= 8
            and all(type(item) is CheckerBinding for item in checkers),
            "invalid checker registry",
        )
        registry = {item.checker_id: item for item in checkers}
        _require(
            len(registry) == len(checkers) and callable(read_snapshot),
            "registry/readback required",
        )
        config = self.configuration
        _require(
            config["risk_model_sha256"] == prediction.model_sha256
            and config["checker_model_sha256"] == effects.model_sha256
            and config["effects_body_sha256"] == digest(asdict(effects))
            and config["scheduler_sha256"] == scheduler_identity(),
            "frozen model/source mismatch",
        )
        choice = select_shadow_check(
            prediction,
            effects,
            observations,
            actions,
            losses,
            remaining_budget,
            hard_checks_complete=hard_checks_complete,
        )
        checker = (
            choice["selection"]["checker_id"] if choice["status"] == "check" else None
        )
        version = next(
            (
                item.version_sha256
                for item in effects.checkers
                if item.checker_id == checker
            ),
            None,
        )
        evaluations = choice["selection"]["evaluations"] if choice["selection"] else ()
        selected = next(
            (item for item in evaluations if item["checker_id"] == checker), None
        )
        cost = selected["cost"] if selected else 0
        if checker is not None:
            _require(
                checker in registry and registry[checker].version_sha256 == version,
                "selected checker unavailable or version changed",
            )
        request = dict(
            operation_id=operation_id,
            config_sha256=self.config_sha256,
            prediction=asdict(prediction),
            choice=choice,
            checker_id=checker,
            checker_version_sha256=version,
            remaining_budget=float(remaining_budget),
            declared_cost_units=cost,
        )
        _require(len(canonical_json(request)) <= 262144, "dispatch request too large")
        return self._dispatch(request, observations, registry, read_snapshot, started)

    def _dispatch(self, request, observations, registry, read_snapshot, started):
        operation, checker = request["operation_id"], request["checker_id"]
        snapshot_sha = request["choice"]["snapshot_sha256"]
        with self._transaction() as db:
            retained = self._get(db, operation)
            if retained is not None:
                _require(
                    retained[0] == _decode(canonical_json(request)),
                    "operation identity conflict",
                )
                return {**(retained[1] or self._pending(request)), "reused": True}
            self._admit(db, request, observations)
            result = (
                None
                if checker is not None
                else dict(
                    status="not_run",
                    reason=request["choice"]["reason"],
                    operation_id=operation,
                    observation=None,
                    production_authority="NONE",
                    request_sha256=digest(request),
                )
            )
            db.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    operation,
                    snapshot_sha,
                    checker,
                    canonical_json(request),
                    digest(request),
                    canonical_json(result) if result else None,
                    digest(result) if result else None,
                ),
            )
            db.execute(
                "UPDATE budgets SET reserved=reserved+? WHERE snapshot=?",
                (request["declared_cost_units"], snapshot_sha),
            )
        if result is not None:
            return {**result, "reused": False}
        return self._invoke(
            operation, request, registry[checker], read_snapshot, started
        )

    def _admit(self, db, request, observations):
        snapshot = request["choice"]["snapshot_sha256"]
        _require(
            db.execute("SELECT count(*) FROM operations").fetchone()[0] < 10000,
            "bounded operation ledger is full",
        )
        prior = [
            self._get(db, row[0])
            for row in db.execute(
                "SELECT id FROM operations WHERE snapshot=? ORDER BY rowid", (snapshot,)
            ).fetchall()
        ]
        _require(
            all(result is not None for _, result in prior),
            "pending original dispatch blocks new operation",
        )
        _require(
            all(
                old["prediction"] == _decode(canonical_json(request["prediction"]))
                for old, _ in prior
            ),
            "pre-history prediction changed",
        )
        contract = request["choice"]["decision_contract"]
        _require(
            all(
                all(
                    old["choice"]["decision_contract"][key]
                    == _decode(canonical_json(contract[key]))
                    for key in ("actions", "losses")
                )
                for old, _ in prior
            ),
            "frozen follow-up actions/losses changed",
        )
        history = [
            result["observation"]
            for _, result in prior
            if result.get("observation") is not None
        ]
        _require(
            history == _decode(canonical_json([asdict(item) for item in observations])),
            "history is not the retained checker observations",
        )
        _require(
            request["checker_id"] is None
            or all(old["checker_id"] != request["checker_id"] for old, _ in prior),
            "checker already attempted on this snapshot",
        )
        budget = db.execute(
            "SELECT original,reserved FROM budgets WHERE snapshot=?", (snapshot,)
        ).fetchone()
        if budget is None:
            db.execute(
                "INSERT INTO budgets VALUES (?, ?, 0)",
                (snapshot, request["remaining_budget"]),
            )
        else:
            _require(
                abs(max(0, budget[0] - budget[1]) - request["remaining_budget"])
                <= 1e-9,
                "remaining budget changed",
            )

    def _invoke(self, operation, request, binding, read_snapshot, started):
        value = request["prediction"]["snapshot"]
        snapshot = Snapshot(**{**value, "target": Target(**value["target"])})
        try:
            if read_snapshot(snapshot) != request["choice"]["snapshot_sha256"]:
                return self._complete(
                    operation,
                    request,
                    None,
                    read_snapshot,
                    started,
                    "stale_before_check",
                )
        except Exception:
            return self._complete(
                operation,
                request,
                None,
                read_snapshot,
                started,
                "snapshot_readback_failed",
            )
        try:
            reply = binding.run(operation, snapshot)
        except Exception as error:
            return self._complete(
                operation,
                request,
                None,
                read_snapshot,
                started,
                "checker_exception:" + type(error).__name__,
            )
        return self._complete(operation, request, reply, read_snapshot, started)

    @staticmethod
    def _reply_matches(request, reply):
        if type(reply) is not CheckerReply:
            return False
        try:
            CheckerReply(**asdict(reply))
        except (AttributeError, TypeError, ValueError):
            return False
        return (
            reply.operation_id,
            reply.checker_id,
            reply.version_sha256,
            reply.snapshot_sha256,
        ) == (
            request["operation_id"],
            request["checker_id"],
            request["checker_version_sha256"],
            request["choice"]["snapshot_sha256"],
        )

    def _complete(self, operation, request, reply, read_snapshot, started, reason=None):
        value = request["prediction"]["snapshot"]
        snapshot = Snapshot(**{**value, "target": Target(**value["target"])})
        expected = request["choice"]["snapshot_sha256"]
        valid = self._reply_matches(request, reply)
        frozen_reply = canonical_json(asdict(reply)) if valid else None
        if reason is None and not valid:
            reason = "invalid_checker_reply"
        try:
            if reason is None and read_snapshot(snapshot) != expected:
                reason = "stale_after_check"
        except Exception:
            reason = "snapshot_readback_failed"
        if valid:
            _require(
                canonical_json(asdict(reply)) == frozen_reply,
                "checker reply changed during snapshot readback",
            )
        observation = (
            asdict(
                CheckObservation(
                    reply.checker_id,
                    reply.version_sha256,
                    expected,
                    reply.outcome,
                    reply.evidence_sha256,
                )
            )
            if reason is None
            else None
        )
        actual = reply.actual_cost_units if valid else None
        charge = max(request["declared_cost_units"], actual or 0)
        result = dict(
            status="completed" if reason is None else "unknown",
            reason=reason or "checker_observed",
            operation_id=operation,
            observation=observation,
            reply=asdict(reply) if valid else None,
            request_sha256=digest(request),
            declared_cost_units=request["declared_cost_units"],
            actual_cost_units=actual,
            charged_cost_units=charge,
            budget_overrun=actual > request["remaining_budget"]
            if actual is not None
            else None,
            measured_precommit_wall_ns=time.perf_counter_ns() - started
            if started is not None
            else None,
            full_physical_cost_complete=False,
            production_authority="NONE",
        )
        return self._retain_result(operation, request, result)

    def _retain_result(self, operation, request, result):
        with self._transaction() as db:
            retained = self._get(db, operation)
            _require(
                retained is not None
                and retained[0] == _decode(canonical_json(request)),
                "original operation changed",
            )
            if retained[1] is not None:
                return {**retained[1], "reused": True}
            db.execute(
                "UPDATE operations SET result=?,result_sha=? WHERE id=? AND result IS NULL",
                (canonical_json(result), digest(result), operation),
            )
            db.execute(
                "UPDATE budgets SET reserved=reserved+? WHERE snapshot=?",
                (
                    result["charged_cost_units"] - request["declared_cost_units"],
                    request["choice"]["snapshot_sha256"],
                ),
            )
        return {**result, "reused": False}

    def reconcile(self, operation_id, reply, *, read_snapshot, authenticate):
        """Attach original retained evidence; never invoke the checker again."""
        _text(operation_id, "operation_id")
        _require(callable(read_snapshot), "snapshot readback required")
        _require(
            self.configuration["scheduler_sha256"] == scheduler_identity(),
            "scheduler source changed",
        )
        with self._transaction() as db:
            retained = self._get(db, operation_id)
        _require(retained is not None, "unknown original operation")
        if retained[1] is not None:
            return {**retained[1], "reused": True}
        _require(
            self._reply_matches(retained[0], reply), "original bound reply required"
        )
        frozen_reply = canonical_json(asdict(reply))
        _require(
            callable(authenticate)
            and authenticate(
                operation_id, reply, digest(retained[0]), self.config_sha256
            )
            is True,
            "original evidence authentication failed",
        )
        _require(
            canonical_json(asdict(reply)) == frozen_reply,
            "checker reply changed during authentication",
        )
        return self._complete(operation_id, retained[0], reply, read_snapshot, None)

    def status(self, operation_id):
        """Read original operation without calling a checker or recomputing selection."""
        _text(operation_id, "operation_id")
        with self._transaction() as db:
            retained = self._get(db, operation_id)
        _require(retained is not None, "unknown original operation")
        return dict(
            request=retained[0],
            result=retained[1] or self._pending(retained[0]),
            config_sha256=self.config_sha256,
            production_authority="NONE",
        )
