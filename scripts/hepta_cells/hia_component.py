"""Native HIA continuations within the experimental Cell owner's SQLite journal.

Owner intent and native pending state precede real Cell invocation. Recovery
never repeats inference. This is not the Rust daemon's adoption authority.
"""

from dataclasses import asdict, replace
import hashlib
import json
from .component_types import (
    CellError,
    ComponentIdentity,
    PendingExecution,
    ReadbackResult,
    StepResult,
    _bounded_json,
    _hex,
    digest,
)


class HiaCellComponent:
    """Compiled HIA continuation and exact inner Cell; host validates candidate."""

    def __init__(self, owner, inner, native, *, candidate_sha256, image_sha256):
        _hex(candidate_sha256)
        _hex(image_sha256)
        self.owner, self.inner, self.native = owner, inner, native
        self.candidate_sha256, self.image_sha256 = candidate_sha256, image_sha256
        owner.db.execute("""CREATE TABLE IF NOT EXISTS hia_cell_calls(
            partition TEXT NOT NULL, request TEXT NOT NULL,
            identity TEXT NOT NULL, fingerprint TEXT NOT NULL,
            binding TEXT NOT NULL, state BLOB NOT NULL, phase TEXT NOT NULL,
            inner_result TEXT, result TEXT, native_ns INTEGER NOT NULL,
            error TEXT, PRIMARY KEY(partition, request))""")

    @property
    def identity(self):
        inner = self.inner.identity
        return ComponentIdentity(
            "hepta.hia-cell.v1",
            inner.bundle_digest,
            effectful=inner.effectful,
            configuration_digest=digest(
                [inner.digest, self.candidate_sha256, self.image_sha256]
            ),
        )

    def initial_state(self):
        return self.inner.initial_state()

    def migrate_state_from(self, source, state):
        """Delegate an idle upgrade without changing continuation custody.

        CellOwner enforces the retained checkpoint, no pending intents and an
        atomic cutover. This port additionally requires the exact same native
        transport instance and SQLite owner; it transfers no in-flight effects.
        The inner component must validate its own hidden-state relation.
        """
        if type(self) is not HiaCellComponent or type(source) is not HiaCellComponent:
            raise CellError("HIA migration requires canonical wrappers")
        if (
            self.owner is not source.owner
            or self.native is not source.native
            or self.image_sha256 != source.image_sha256
            or type(self.inner) is not type(source.inner)
        ):
            raise CellError("HIA migration must retain owner, native transport and image")
        before, prior = self.identity, source.identity
        owner, native, image = self.owner, self.native, self.image_sha256
        if before.effectful or prior.effectful:
            raise CellError("HIA effectful state requires separate custody")
        convert = getattr(self.inner, "migrate_state_from", None)
        if not callable(convert):
            raise CellError("inner Cell has no checked state migration")
        migrated = convert(source.inner, state)
        if (
            self.identity != before
            or source.identity != prior
            or self.owner is not owner or source.owner is not owner
            or self.native is not native or source.native is not native
            or self.image_sha256 != image or source.image_sha256 != image
        ):
            raise CellError("HIA migration identity or custody changed during conversion")
        return migrated

    def _row(self, partition, request):
        row = self.owner.db.execute(
            "SELECT * FROM hia_cell_calls WHERE partition=? AND request=?",
            (partition.digest, request),
        ).fetchone()
        return dict(row) if row else None

    def step(self, payload, state, context):
        if context.identity != self.identity:
            raise CellError("HIA Cell context differs from frozen candidate")
        encoded = _bounded_json(payload, min(65536, context.budget.max_input_bytes))
        key = (context.partition.digest, context.request_id)
        self.owner._begin()
        try:
            intent = self.owner.db.execute(
                "SELECT * FROM intents WHERE partition=? AND request=?", key
            ).fetchone()
            cell = self.owner._cell(context.partition)
            if (
                intent is None
                or intent["status"] != "pending"
                or intent["identity"] != _bounded_json(asdict(context.identity))
                or intent["payload"] != encoded
                or intent["generation"] != context.epoch
                or cell["identity"] != intent["identity"]
                or cell["generation"] != context.epoch
                or cell["state"] != _bounded_json(state, context.budget.max_state_bytes)
            ):
                raise CellError("native call requires exact pending owner intent")
            if self._row(context.partition, context.request_id) is not None:
                raise PendingExecution("continuation exists; read back only")
            begin = self.native.begin(
                bytes(256),
                candidate_sha256=self.candidate_sha256,
                cell_sha256=self.inner.identity.digest,
                request_sha256=digest([*key, context.epoch, intent["fingerprint"]]),
                input_bytes=encoded.encode(),
                sequence=cell["sequence"] + 1,
                result_limit=65536,
            )
            if begin.action != "INVOKE_CELL" or begin.payload != encoded.encode():
                raise CellError("HIA did not emit exact authorized Cell request")
            self.owner.db.execute(
                "INSERT INTO hia_cell_calls VALUES(?,?,?,?,?,?,'pending',NULL,NULL,?,NULL)",
                (
                    *key,
                    self.identity.digest,
                    intent["fingerprint"],
                    _bounded_json(begin.binding.to_dict()),
                    begin.state,
                    begin.native_wall_ns,
                ),
            )
            self.owner.db.commit()
        except BaseException:
            self.owner.db.rollback()
            raise
        try:
            result = self.inner.step(
                payload, state, replace(context, identity=self.inner.identity)
            )
            if not isinstance(result, StepResult):
                raise CellError("inner Cell returned invalid result")
            self.owner.db.execute(
                "UPDATE hia_cell_calls SET inner_result=?,phase='cell_returned' "
                "WHERE partition=? AND request=?",
                (_bounded_json(asdict(result), 65536), *key),
            )
            return self._finish(context.partition, context.request_id, begin.binding)
        except BaseException as error:
            self.owner.db.execute(
                "UPDATE hia_cell_calls SET error=? WHERE partition=? AND request=?",
                (type(error).__name__, *key),
            )
            raise

    def _finish(self, partition, request, binding):
        self.owner._begin()
        try:
            result = self._finish_locked(partition, request, binding)
            self.owner.db.commit()
            return result
        except BaseException:
            self.owner.db.rollback()
            raise

    def _finish_locked(self, partition, request, binding):
        row = self._row(partition, request)
        if row["identity"] != self.identity.digest or row["inner_result"] is None:
            raise PendingExecution("no exact retained Cell result")
        if row["result"] is not None:
            return StepResult(**json.loads(row["result"]))
        raw = row["inner_result"].encode()
        step = self.native.resume(
            bytes(row["state"]), binding=binding, outcome="success", result_bytes=raw
        )
        if step.action != "COMPLETE" or step.payload != raw:
            raise CellError("HIA completion differs from retained Cell result")
        inner = StepResult(**json.loads(row["inner_result"]))
        result = StepResult(
            {
                "cell": inner.output,
                "hia": {
                    "candidate_sha256": self.candidate_sha256,
                    "image_sha256": self.image_sha256,
                    "binding": binding.to_dict(),
                    "terminal_action": step.action,
                    "native_wall_ns": row["native_ns"] + step.native_wall_ns,
                    "native_state_sha256": hashlib.sha256(step.state).hexdigest(),
                },
            },
            inner.state,
            inner.work_units,
        )
        self.owner.db.execute(
            "UPDATE hia_cell_calls SET state=?,phase='completed',result=?,native_ns=?,error=NULL "
            "WHERE partition=? AND request=?",
            (
                step.state,
                _bounded_json(asdict(result), 262144),
                row["native_ns"] + step.native_wall_ns,
                partition.digest,
                request,
            ),
        )
        return result

    def readback(self, pending):
        """Read retained results; never repeat inference or invent original cost."""
        if pending.identity != self.identity:
            raise CellError("readback candidate differs from original request")
        row = self._row(pending.partition, pending.request_id)
        if row is None:
            return None
        if (
            row["identity"] != pending.identity.digest
            or row["fingerprint"] != pending.request_digest
        ):
            raise CellError("readback differs from durable Cell intent")
        binding = self.native.binding_from_dict(json.loads(row["binding"]))
        if row["inner_result"] is None:
            self.owner._begin()
            try:
                current = self._row(pending.partition, pending.request_id)
                if current["inner_result"] is None:
                    recovered = self.native.recover(
                        bytes(current["state"]), binding=binding
                    )
                    self.owner.db.execute(
                        "UPDATE hia_cell_calls SET state=?,phase='unknown',native_ns=native_ns+? "
                        "WHERE partition=? AND request=?",
                        (
                            recovered.state,
                            recovered.native_wall_ns,
                            pending.partition.digest,
                            pending.request_id,
                        ),
                    )
                    self.owner.db.commit()
                    return None
                self.owner.db.commit()
            except BaseException:
                self.owner.db.rollback()
                raise
        result = self._finish(pending.partition, pending.request_id, binding)
        attempts = self.owner.attempts(pending.partition, pending.request_id)
        measured = [
            a["elapsed_ns"]
            for a in attempts
            if a["phase"] == "invocation" and a["elapsed_ns"] is not None
        ]
        return ReadbackResult(result, measured[0] if measured else None)

    def observe_cancellation(self, partition, request):
        """Record native CANCEL_REQUEST after the owner's durable cancel intent."""
        cancellation = self.owner.cancellation_status(partition, request)
        self.owner._begin()
        try:
            self._cancel_locked(partition, request)
            self.owner.db.commit()
        except BaseException:
            self.owner.db.rollback()
            raise
        return cancellation

    def _cancel_locked(self, partition, request):
        row = self._row(partition, request)
        if (
            row is None
            or row["result"] is not None
            or int.from_bytes(row["state"][184:192], "little") == 1
        ):
            return
        if row["identity"] != self.identity.digest:
            raise CellError("cancellation candidate differs from original invocation")
        binding = self.native.binding_from_dict(json.loads(row["binding"]))
        step = self.native.cancel(bytes(row["state"]), binding=binding)
        self.owner.db.execute(
            "UPDATE hia_cell_calls SET state=?,phase='cancel_requested',native_ns=native_ns+? "
            "WHERE partition=? AND request=?",
            (step.state, step.native_wall_ns, partition.digest, request),
        )

    def continuation_status(self, partition, request):
        """Read original state without inferring model or business completion."""
        row = self._row(partition, request)
        if row is None:
            return None
        return {
            key: row[key]
            for key in ("identity", "fingerprint", "phase", "native_ns", "error")
        } | {
            "native_state_sha256": hashlib.sha256(row["state"]).hexdigest(),
            "cell_result_retained": row["inner_result"] is not None,
            "terminal_result_retained": row["result"] is not None,
        }
