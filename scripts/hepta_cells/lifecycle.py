"""Bounded experimental Python Cell owner; not the native daemon state owner.

Component API: identity, initial_state(), step(payload, state, context).
Only JSON values cross this boundary. StepResult carries output, new state, and
work_units. The owner persists intent before invocation. Interrupted/invalid
results stay pending and require explicit host readback; they are never rerun.
"""

from dataclasses import asdict
import hashlib
import json
import sqlite3
import time
from typing import Callable

from .population_owner import PopulationPolicy

from .component_types import (
    Budget as Budget,
    CellError as CellError,
    Component as Component,
    ComponentIdentity as ComponentIdentity,
    OwnerLimits as OwnerLimits,
    Partition as Partition,
    PendingExecution as PendingExecution,
    PendingIntent as PendingIntent,
    Qualification as Qualification,
    ReadbackResult as ReadbackResult,
    RequestConflict as RequestConflict,
    StepContext as StepContext,
    StepResult as StepResult,
    _bounded_json as _bounded_json,
    _hex as _hex,
    _token as _token,
    digest as digest,
)


class CellOwner:
    """SQLite state/journal owner for experiments; host callbacks are trusted.

    Budget reservations survive interruption. Readback and qualification ports
    are injected by the host; their supplied digests are not authentication.
    Deadlines are checked on return, not preemptive cancellation of Python code.
    Epoch is the local owner state epoch, distinct from native Bundle generation.
    Local rollback resets a retained component; native rollback needs a new Bundle.
    A confirmed external effect retains its resulting state even after an overrun.
    Its epoch then blocks new requests until an explicit lifecycle transition.
    Capacity blocks new rows, including new lifecycle epochs, but never settlement
    or exact receipt replay. Recovery does not evict evidence or raise the limits.
    """

    def __init__(
        self,
        database,
        qualify: Callable[[Qualification], bool] | None = None,
        *,
        limits: OwnerLimits | None = None,
        population=None,
    ):
        if limits is not None and not isinstance(limits, OwnerLimits):
            raise CellError("limits must be OwnerLimits")
        self.db = sqlite3.connect(str(database), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.qualify = qualify
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS cells(
                partition TEXT PRIMARY KEY, identity TEXT NOT NULL, generation INTEGER NOT NULL,
                sequence INTEGER NOT NULL, state TEXT NOT NULL, view TEXT NOT NULL,
                budget TEXT NOT NULL, remaining INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS intents(
                partition TEXT NOT NULL, request TEXT NOT NULL, fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL, generation INTEGER NOT NULL, status TEXT NOT NULL,
                reserved INTEGER NOT NULL, identity TEXT NOT NULL, view TEXT NOT NULL,
                budget TEXT NOT NULL, receipt TEXT,
                PRIMARY KEY(partition,request));
            CREATE TABLE IF NOT EXISTS attempts(
                partition TEXT NOT NULL, request TEXT NOT NULL, phase TEXT NOT NULL,
                elapsed_ns INTEGER, work_units INTEGER, outcome TEXT NOT NULL, readback_elapsed_ns INTEGER);
            CREATE TABLE IF NOT EXISTS history(
                partition TEXT NOT NULL, generation INTEGER NOT NULL, identity TEXT NOT NULL,
                PRIMARY KEY(partition,generation));
            CREATE TABLE IF NOT EXISTS checkpoints(
                digest TEXT PRIMARY KEY, partition TEXT NOT NULL, snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS owner_settings(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), limits TEXT NOT NULL);
        """)
        self._begin()
        try:
            self._population = PopulationPolicy(self.db, population)
            saved = self.db.execute(
                "SELECT limits FROM owner_settings WHERE singleton=1"
            ).fetchone()
            self.limits = (
                OwnerLimits(**json.loads(saved["limits"]))
                if saved
                else limits or OwnerLimits()
            )
            if limits is not None and limits != self.limits:
                raise CellError("owner limits differ from the retained database policy")
            if not saved:
                self.db.execute(
                    "INSERT INTO owner_settings VALUES(1,?)",
                    (_bounded_json(asdict(self.limits)),),
                )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @property
    def population_plan(self):
        return self._population.plan

    def _begin(self):
        self.db.execute("BEGIN IMMEDIATE")

    def _capacity(self, resource, partition=None):
        table, limit, per_partition = {
            "cells": ("cells", self.limits.max_cells, None),
            "intents": ("intents", self.limits.max_intents, 1024),
            "checkpoints": ("checkpoints", self.limits.max_checkpoints, 128),
            "epochs": ("history", self.limits.max_epochs, None),
        }[resource]
        if self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] >= limit:
            raise CellError(
                f"owner {resource} capacity exhausted; retained evidence cannot be evicted"
            )
        if (
            per_partition is not None
            and self.db.execute(
                f"SELECT count(*) FROM {table} WHERE partition=?", (partition.digest,)
            ).fetchone()[0]
            >= per_partition
        ):
            raise CellError(
                f"partition {resource} capacity exhausted; retained evidence cannot be evicted"
            )

    def _cell(self, partition):
        row = self.db.execute(
            "SELECT * FROM cells WHERE partition=?", (partition.digest,)
        ).fetchone()
        if row is None:
            raise CellError("unknown cell partition")
        return dict(row)

    def _idle(self, partition):
        if self.db.execute(
            "SELECT 1 FROM intents WHERE partition=? AND status='pending'",
            (partition.digest,),
        ).fetchone():
            raise PendingExecution("pending intent requires host reconciliation")

    def _budget_halt(self, partition, cell):
        if not json.loads(cell["identity"])["effectful"]:
            return None
        rows = self.db.execute(
            "SELECT request,receipt FROM intents WHERE partition=? AND generation=? AND status='committed' ORDER BY request",
            (partition.digest, cell["generation"]),
        )
        return next(
            (
                row["request"]
                for row in rows
                if json.loads(row["receipt"])["status"] == "budget_exceeded"
            ),
            None,
        )

    @staticmethod
    def _identity(component):
        identity = component.identity
        if not isinstance(identity, ComponentIdentity):
            raise CellError("component must expose ComponentIdentity")
        return identity

    def _initial(self, component, identity):
        state = component.initial_state()
        if self._identity(component) != identity:
            raise CellError("component identity changed while initializing state")
        return state

    def create(
        self,
        partition,
        component,
        retrieval_view=None,
        budget=Budget(),
        total_work_units=1000000,
    ):
        identity = self._identity(component)
        if (
            type(total_work_units) is not int
            or not 1 <= total_work_units <= 1000000000000
        ):
            raise CellError("invalid total work budget")
        view, policy = _bounded_json(retrieval_view), _bounded_json(asdict(budget))
        self._begin()
        try:
            if self.db.execute(
                "SELECT 1 FROM cells WHERE partition=?", (partition.digest,)
            ).fetchone():
                raise CellError(
                    "partition already exists; reopen its existing database"
                )
            for resource in ("cells", "epochs", "checkpoints"):
                self._capacity(resource, partition)
            self._population.create(partition, component, budget, total_work_units)
            state = _bounded_json(
                self._initial(component, identity), budget.max_state_bytes
            )
            self.db.execute(
                "INSERT INTO cells VALUES(?,?,?,?,?,?,?,?)",
                (
                    partition.digest,
                    _bounded_json(asdict(identity)),
                    0,
                    0,
                    state,
                    view,
                    policy,
                    total_work_units,
                ),
            )
            self.db.execute(
                "INSERT INTO history VALUES(?,?,?)",
                (partition.digest, 0, identity.digest),
            )
            checkpoint = self._checkpoint(partition, self._cell(partition))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return checkpoint

    def step(self, partition, component, request_id, payload):
        _token(request_id)
        identity = self._identity(component)
        self._begin()
        try:
            cell = self._cell(partition)
            policy = Budget(**json.loads(cell["budget"]))
            payload_json = _bounded_json(payload, policy.max_input_bytes)
            prior = self.db.execute(
                "SELECT * FROM intents WHERE partition=? AND request=?",
                (partition.digest, request_id),
            ).fetchone()
            if prior:
                fingerprint = digest(
                    [
                        identity.digest,
                        prior["generation"],
                        payload_json,
                        prior["view"],
                        prior["budget"],
                    ]
                )
                if prior["fingerprint"] != fingerprint:
                    raise RequestConflict(
                        "request ID is already bound to different arguments or epoch"
                    )
                if prior["status"] == "pending":
                    raise PendingExecution(
                        "unknown outcome; same request must not be executed again"
                    )
                self.db.commit()
                return json.loads(prior["receipt"])
            if _bounded_json(asdict(identity)) != cell["identity"]:
                raise CellError("component identity differs from the active bundle")
            if self._population.plan is not None:
                self._population.describe(partition, component)
            self._idle(partition)
            if self._budget_halt(partition, cell) is not None:
                raise CellError(
                    "confirmed effect exceeded budget; explicit lifecycle recovery is required"
                )
            self._capacity("intents", partition)
            fingerprint = digest(
                [
                    identity.digest,
                    cell["generation"],
                    payload_json,
                    cell["view"],
                    cell["budget"],
                ]
            )
            if cell["remaining"] < policy.max_work_units:
                raise CellError("insufficient budget for a bounded reservation")
            self.db.execute(
                "INSERT INTO intents VALUES(?,?,?,?,?,'pending',?,?,?,?,NULL)",
                (
                    partition.digest,
                    request_id,
                    fingerprint,
                    payload_json,
                    cell["generation"],
                    policy.max_work_units,
                    cell["identity"],
                    cell["view"],
                    cell["budget"],
                ),
            )
            self.db.execute(
                "UPDATE cells SET remaining=remaining-? WHERE partition=?",
                (policy.max_work_units, partition.digest),
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        context = StepContext(
            partition,
            request_id,
            identity,
            json.loads(cell["view"]),
            policy,
            cell["generation"],
        )
        start, result = time.perf_counter_ns(), None
        try:
            result = component.step(
                json.loads(payload_json), json.loads(cell["state"]), context
            )
            elapsed = time.perf_counter_ns() - start
            if self._identity(component) != identity:
                raise CellError("component mutated its bundle during execution")
            return self._settle(partition, request_id, identity, result, elapsed)
        except BaseException as error:
            self._attempt(
                partition,
                request_id,
                "invocation",
                time.perf_counter_ns() - start,
                result,
                type(error).__name__,
            )
            raise PendingExecution(
                "invocation is pending; reconcile without repeating step"
            ) from error

    def _settle(self, partition, request_id, identity, result, elapsed_ns):
        if not isinstance(result, StepResult):
            raise CellError("component must return StepResult")
        self._begin()
        try:
            cell = self._cell(partition)
            intent = self.db.execute(
                "SELECT * FROM intents WHERE partition=? AND request=?",
                (partition.digest, request_id),
            ).fetchone()
            if not intent:
                raise CellError("intent is missing")
            if intent["status"] == "committed":
                if intent["identity"] != _bounded_json(asdict(identity)):
                    raise CellError(
                        "settlement identity differs from the original request"
                    )
                self.db.commit()
                return json.loads(intent["receipt"])
            if (
                cell["identity"] != _bounded_json(asdict(identity))
                or intent["generation"] != cell["generation"]
            ):
                raise CellError("pending intent no longer matches the active bundle")
            policy = Budget(**json.loads(cell["budget"]))
            if (
                type(result.work_units) is not int
                or not 0 <= result.work_units <= 1000000000000
            ):
                raise CellError("reported work is invalid or unknown")
            if type(elapsed_ns) is not int or not 0 <= elapsed_ns <= 2**63 - 1:
                raise CellError("original elapsed cost is invalid or unknown")
            exceeded = (
                result.work_units > intent["reserved"]
                or elapsed_ns > policy.max_elapsed_ms * 1000000
            )
            output = json.loads(_bounded_json(result.output, policy.max_output_bytes))
            candidate_state = _bounded_json(result.state, policy.max_state_bytes)
            apply_state = not exceeded or identity.effectful
            state = candidate_state if apply_state else cell["state"]
            receipt = dict(
                request_id=request_id,
                partition_digest=partition.digest,
                identity_digest=identity.digest,
                bundle_digest=identity.bundle_digest,
                epoch=cell["generation"],
                sequence=cell["sequence"] + 1,
                output=output,
                work_units=result.work_units,
                elapsed_ns=elapsed_ns,
                state_digest=hashlib.sha256(state.encode()).hexdigest(),
                status="budget_exceeded" if exceeded else "committed",
                state_applied=apply_state,
                requires_recovery=exceeded and identity.effectful,
            )
            self._population.annotate(partition, receipt)
            self.db.execute(
                "UPDATE cells SET state=?,sequence=sequence+1,remaining=remaining+? WHERE partition=?",
                (state, intent["reserved"] - result.work_units, partition.digest),
            )
            self.db.execute(
                "UPDATE intents SET status='committed',receipt=? WHERE partition=? AND request=?",
                (_bounded_json(receipt, 524288), partition.digest, request_id),
            )
            self.db.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?,?,NULL)",
                (
                    partition.digest,
                    request_id,
                    "settled",
                    elapsed_ns,
                    result.work_units,
                    receipt["status"],
                ),
            )
            self.db.commit()
            return receipt
        except BaseException:
            self.db.rollback()
            raise

    def _attempt(self, partition, request_id, phase, elapsed_ns, result, outcome):
        work = (
            result.work_units
            if isinstance(result, StepResult)
            and type(result.work_units) is int
            and 0 <= result.work_units <= 10**12
            else None
        )
        elapsed = (
            elapsed_ns
            if type(elapsed_ns) is int and 0 <= elapsed_ns <= 2**63 - 1
            else None
        )
        return self.db.execute(
            "INSERT INTO attempts VALUES(?,?,?,?,?,?,NULL)",
            (partition.digest, request_id, phase, elapsed, work, outcome),
        ).lastrowid

    def attempts(self, partition, request_id):
        """Original cost observations may repeat; readback_elapsed_ns is per readback.

        Use the settled receipt once for original cost, plus measured readback cost.
        None means unknown, never zero.
        """
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT phase,elapsed_ns,work_units,outcome,readback_elapsed_ns FROM attempts WHERE partition=? AND request=? ORDER BY rowid",
                (partition.digest, request_id),
            )
        ]

    def reconcile(
        self,
        partition,
        component,
        request_id,
        readback: Callable[[PendingIntent], ReadbackResult | None],
    ):
        _token(request_id)
        identity, cell = self._identity(component), self._cell(partition)
        row = self.db.execute(
            "SELECT * FROM intents WHERE partition=? AND request=?",
            (partition.digest, request_id),
        ).fetchone()
        if row is None:
            raise CellError("unknown request")
        if row["identity"] != _bounded_json(asdict(identity)):
            raise CellError("readback component differs from original identity")
        if row["status"] == "committed":
            return json.loads(row["receipt"])
        pending = PendingIntent(
            partition,
            request_id,
            identity,
            row["generation"],
            json.loads(row["payload"]),
            json.loads(cell["state"]),
            json.loads(row["view"]),
            Budget(**json.loads(row["budget"])),
            row["fingerprint"],
        )
        self._begin()
        try:
            current = self.db.execute(
                "SELECT * FROM intents WHERE partition=? AND request=?",
                (partition.digest, request_id),
            ).fetchone()
            if current["status"] == "committed":
                self.db.commit()
                return json.loads(current["receipt"])
            if len(self.attempts(partition, request_id)) >= 32:
                raise CellError("bounded readback attempt capacity exhausted")
            attempt = self._attempt(
                partition, request_id, "readback", None, None, "started"
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        start = time.perf_counter_ns()
        try:
            observation = readback(pending)
        except BaseException as error:
            self.db.execute(
                "UPDATE attempts SET outcome=?,readback_elapsed_ns=? WHERE rowid=?",
                (type(error).__name__, time.perf_counter_ns() - start, attempt),
            )
            raise PendingExecution(
                "readback failed; original invocation remains pending"
            ) from error
        readback_elapsed = time.perf_counter_ns() - start
        if observation is None or not isinstance(observation, ReadbackResult):
            self.db.execute(
                "UPDATE attempts SET outcome=?,readback_elapsed_ns=? WHERE rowid=?",
                (
                    "outcome_unknown" if observation is None else "invalid_readback",
                    readback_elapsed,
                    attempt,
                ),
            )
            raise PendingExecution(
                "host readback did not establish an outcome and original cost"
            )
        original = observation.original_elapsed_ns
        original = (
            original if type(original) is int and 0 <= original <= 2**63 - 1 else None
        )
        work = (
            observation.result.work_units
            if isinstance(observation.result, StepResult)
            and type(observation.result.work_units) is int
            and 0 <= observation.result.work_units <= 10**12
            else None
        )
        self.db.execute(
            "UPDATE attempts SET outcome=?,elapsed_ns=?,work_units=?,readback_elapsed_ns=? WHERE rowid=?",
            (
                "original_cost_unknown" if original is None else "observed",
                original,
                work,
                readback_elapsed,
                attempt,
            ),
        )
        try:
            if self._identity(component) != identity:
                raise CellError("component identity changed during readback")
        except BaseException as error:
            self.db.execute(
                "UPDATE attempts SET outcome='identity_changed' WHERE rowid=?",
                (attempt,),
            )
            raise PendingExecution(
                "readback identity changed; original invocation remains pending"
            ) from error
        if original is None:
            raise PendingExecution(
                "original elapsed cost remains unknown; reservation retained"
            )
        return self._settle(
            partition, request_id, identity, observation.result, original
        )

    def _checkpoint(self, partition, cell):
        snapshot = dict(
            partition=asdict(partition),
            identity=json.loads(cell["identity"]),
            epoch=cell["generation"],
            sequence=cell["sequence"],
            state=json.loads(cell["state"]),
            retrieval_view=json.loads(cell["view"]),
            budget=json.loads(cell["budget"]),
            remaining_work_units=cell["remaining"],
        )
        self._population.annotate(partition, snapshot)
        encoded = _bounded_json(snapshot, 1048576)
        checkpoint_id = hashlib.sha256(encoded.encode()).hexdigest()
        if not self.db.execute(
            "SELECT 1 FROM checkpoints WHERE digest=?", (checkpoint_id,)
        ).fetchone():
            self._capacity("checkpoints", partition)
            self.db.execute(
                "INSERT OR IGNORE INTO checkpoints VALUES(?,?,?)",
                (checkpoint_id, partition.digest, encoded),
            )
        return dict(digest=checkpoint_id, **snapshot)

    def checkpoint(self, partition):
        self._begin()
        try:
            cell = self._cell(partition)
            self._idle(partition)
            checkpoint = self._checkpoint(partition, cell)
            self.db.commit()
            return checkpoint
        except BaseException:
            self.db.rollback()
            raise

    def status(self, partition):
        self._begin()
        try:
            cell = self._cell(partition)
            pending = [
                row["request"]
                for row in self.db.execute(
                    "SELECT request FROM intents WHERE partition=? AND status='pending' ORDER BY request",
                    (partition.digest,),
                )
            ]
            result = dict(
                identity=json.loads(cell["identity"]),
                epoch=cell["generation"],
                sequence=cell["sequence"],
                remaining_work_units=cell["remaining"],
                pending=pending,
                budget_halt=self._budget_halt(partition, cell),
            )
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def _transition(
        self,
        partition,
        component,
        identity,
        expected_identity,
        mode,
        checkpoint_id=None,
    ):
        if self._identity(component) != identity:
            raise CellError("target identity changed before transition")
        self._begin()
        try:
            cell = self._cell(partition)
            self._idle(partition)
            self._capacity("epochs", partition)
            self._capacity("checkpoints", partition)
            current = ComponentIdentity(**json.loads(cell["identity"]))
            if current.digest != expected_identity:
                raise CellError("stale active identity")
            if (
                mode == "rollback"
                and not self.db.execute(
                    "SELECT 1 FROM history WHERE partition=? AND identity=?",
                    (partition.digest, identity.digest),
                ).fetchone()
            ):
                raise CellError("rollback target was never admitted for this partition")
            self._population.transition(partition, component, current, mode)
            if mode == "restore":
                row = self.db.execute(
                    "SELECT * FROM checkpoints WHERE digest=? AND partition=?",
                    (checkpoint_id, partition.digest),
                ).fetchone()
                if not row:
                    raise CellError("checkpoint is not retained by this owner")
                if (
                    hashlib.sha256(row["snapshot"].encode()).hexdigest()
                    != checkpoint_id
                ):
                    raise CellError("retained checkpoint integrity check failed")
                saved = json.loads(row["snapshot"])
                if (
                    saved["identity"] != asdict(identity)
                    or saved["epoch"] != cell["generation"]
                    or identity != current
                ):
                    raise CellError(
                        "checkpoint hidden state belongs to a different bundle or epoch"
                    )
                if identity.effectful and saved["sequence"] != cell["sequence"]:
                    raise CellError("cannot rewind external effect state")
                state = saved["state"]
            else:
                state = self._initial(component, identity)
            encoded = _bounded_json(
                state, Budget(**json.loads(cell["budget"])).max_state_bytes
            )
            generation = cell["generation"] + 1
            self.db.execute(
                "UPDATE cells SET identity=?,generation=?,sequence=sequence+1,state=? WHERE partition=?",
                (
                    _bounded_json(asdict(identity)),
                    generation,
                    encoded,
                    partition.digest,
                ),
            )
            self.db.execute(
                "INSERT INTO history VALUES(?,?,?)",
                (partition.digest, generation, identity.digest),
            )
            checkpoint = self._checkpoint(partition, self._cell(partition))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return checkpoint

    def adopt(self, partition, component, qualification: Qualification):
        if type(qualification) is not Qualification:
            raise CellError("host qualification must be a canonical Qualification")
        expected = (
            qualification.source_identity,
            qualification.candidate_identity,
            qualification.evaluation_digest,
        )
        for value in expected:
            _hex(value)
        # Freeze caller values before invoking the trusted host callback.
        checked = Qualification(*expected)
        identity = self._identity(component)
        if (
            expected[1] != identity.digest
            or self.qualify is None
            or self.qualify(checked) is not True
        ):
            raise CellError("host qualification did not admit this candidate")
        returned = (
            checked.source_identity,
            checked.candidate_identity,
            checked.evaluation_digest,
        )
        for value in returned:
            _hex(value)
        if returned != expected or self._identity(component).digest != expected[1]:
            raise CellError("qualification or candidate changed during host validation")
        return self._transition(partition, component, identity, expected[0], "adopt")

    def reset(self, partition, component, expected_identity):
        identity = self._identity(component)
        if identity.digest != expected_identity:
            raise CellError("reset must use the current component")
        return self._transition(
            partition, component, identity, expected_identity, "reset"
        )

    def rollback(self, partition, component, expected_identity):
        identity = self._identity(component)
        return self._transition(
            partition, component, identity, expected_identity, "rollback"
        )

    def restore(self, partition, component, checkpoint_id, expected_identity):
        identity = self._identity(component)
        return self._transition(
            partition, component, identity, expected_identity, "restore", checkpoint_id
        )
