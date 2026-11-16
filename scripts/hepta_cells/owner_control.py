"""Cancellation observations and checked version migration for the local owner.

Cancellation is a durable request, not proof that a dispatched action stopped.
Migration keeps the same SQLite owner and partition; it does not move custody to
another process/database or admit an arbitrary Cell split. Component-specific
state conversion is checked before the atomic version cutover.
"""

from dataclasses import asdict
import hashlib
import json
import time

from .component_types import (
    Budget,
    CellError,
    Qualification,
    RequestConflict,
    _bounded_json,
    _hex,
    _token,
    digest,
)


class OwnerControl:
    """Control ports sharing CellOwner's transaction, quota and identity checks."""

    def _qualified_identity(self, component, qualification):
        if type(qualification) is not Qualification:
            raise CellError("host qualification must be a canonical Qualification")
        expected = (
            qualification.source_identity,
            qualification.candidate_identity,
            qualification.evaluation_digest,
        )
        for value in expected:
            _hex(value)
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
        return identity, expected[0]

    def request_cancel(self, partition, component, request_id):
        """Record intent to cancel; retain reservations and any observed result.

        One row per existing request is bounded by the retained intent quota.
        The host may use this observation for cooperative cancellation. It must
        still reconcile the original operation and cost; this port signals no
        process, invents no result and cannot cancel a future request.
        """
        _token(request_id)
        identity = self._identity(component)
        self._begin()
        try:
            intent = self.db.execute(
                "SELECT identity FROM intents WHERE partition=? AND request=?",
                (partition.digest, request_id),
            ).fetchone()
            if intent is None or intent["identity"] != _bounded_json(asdict(identity)):
                raise CellError("cancellation must name the original request identity")
            self.db.execute(
                "INSERT OR IGNORE INTO cancellations VALUES(?,?,?)",
                (partition.digest, request_id, identity.digest),
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.cancellation_status(partition, request_id)

    def cancellation_status(self, partition, request_id):
        """Read current original outcome, including a result after cancellation."""
        _token(request_id)
        row = self.db.execute(
            "SELECT c.identity,i.status,i.receipt FROM cancellations c "
            "JOIN intents i USING(partition,request) WHERE c.partition=? AND c.request=?",
            (partition.digest, request_id),
        ).fetchone()
        if row is None:
            raise CellError("unknown cancellation request")
        return {
            "request_id": request_id,
            "partition_digest": partition.digest,
            "identity_digest": row["identity"],
            "cancellation_requested": True,
            "outcome": "unknown" if row["status"] == "pending" else "settled",
            "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
        }

    def migrate(
        self,
        partition,
        source,
        component,
        qualification,
        *,
        operation_id,
        checkpoint_id,
    ):
        """Atomically upgrade one idle Cell using its exact retained checkpoint.

        The component's migrate_state_from port must check the state relation.
        Effectful components are excluded. Unsettled intents block migration;
        their effects cannot be transferred merely by copying a journal. The
        previous version remains available only for exact receipt replay.
        """
        _token(operation_id)
        _hex(checkpoint_id)
        started = time.perf_counter_ns()
        if type(qualification) is not Qualification:
            raise CellError("host qualification must be a canonical Qualification")
        qualification = Qualification(**asdict(qualification))
        identity, expected = self._qualified_identity(component, qualification)
        source_identity = self._identity(source)
        if source_identity.digest != expected or identity == source_identity:
            raise CellError("migration requires the qualified distinct source version")
        if identity.effectful or source_identity.effectful:
            raise CellError("effectful state requires a separate custody protocol")
        fingerprint = digest(
            [expected, identity.digest, checkpoint_id, asdict(qualification)]
        )
        self._begin()
        try:
            prior = self.db.execute(
                "SELECT fingerprint,receipt FROM migrations WHERE partition=? AND operation=?",
                (partition.digest, operation_id),
            ).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise RequestConflict("migration ID is bound to different inputs")
                self.db.commit()
                return json.loads(prior["receipt"])
            cell = self._cell(partition)
            self._idle(partition)
            if cell["identity"] != _bounded_json(asdict(source_identity)):
                raise CellError("stale source version")
            self._capacity("epochs", partition)
            self._capacity("checkpoints", partition)
            saved = self.db.execute(
                "SELECT snapshot FROM checkpoints WHERE digest=? AND partition=?",
                (checkpoint_id, partition.digest),
            ).fetchone()
            if (
                saved is None
                or hashlib.sha256(saved["snapshot"].encode()).hexdigest()
                != checkpoint_id
            ):
                raise CellError("source checkpoint is missing or changed")
            snapshot = json.loads(saved["snapshot"])
            if (
                snapshot["identity"] != asdict(source_identity)
                or snapshot["epoch"] != cell["generation"]
                or snapshot["sequence"] != cell["sequence"]
                or snapshot["state"] != json.loads(cell["state"])
                or snapshot["remaining_work_units"] != cell["remaining"]
                or cell["generation"] >= 2**63 - 1
            ):
                raise CellError("source checkpoint is stale")
            state = component.migrate_state_from(source, json.loads(cell["state"]))
            if (
                self._identity(source) != source_identity
                or self._identity(component) != identity
            ):
                raise CellError("component identity changed during migration")
            encoded = _bounded_json(
                state, Budget(**json.loads(cell["budget"])).max_state_bytes
            )
            self._population.transition(partition, component, source_identity, "adopt")
            epoch = cell["generation"] + 1
            self.db.execute(
                "UPDATE cells SET identity=?,generation=?,sequence=sequence+1,state=? WHERE partition=?",
                (_bounded_json(asdict(identity)), epoch, encoded, partition.digest),
            )
            self.db.execute(
                "INSERT INTO history VALUES(?,?,?)",
                (partition.digest, epoch, identity.digest),
            )
            target = self._checkpoint(partition, self._cell(partition))
            receipt = {
                "operation_id": operation_id,
                "source_checkpoint": checkpoint_id,
                "target_checkpoint": target,
                "evaluation_digest": qualification.evaluation_digest,
                "precommit_elapsed_ns": time.perf_counter_ns() - started,
            }
            self.db.execute(
                "INSERT INTO migrations VALUES(?,?,?,?)",
                (
                    partition.digest,
                    operation_id,
                    fingerprint,
                    _bounded_json(receipt, 1048576),
                ),
            )
            self.db.commit()
            return receipt
        except BaseException:
            self.db.rollback()
            raise
