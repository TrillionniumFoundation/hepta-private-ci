"""Experimental receiver fencing for one authoritative local append ledger.

Appending a bounded record is the effect, committed atomically with its receipt.
This is not a transaction adapter for arbitrary external APIs. The trusted host
provisions leases; SQLite file access is administrative access. A copied database
is not a second authority. CellOwner's effectful migration refusal is unchanged.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json

from .component_types import CellError, RequestConflict, _bounded_json, _hex, _token
from .deterministic import ToolInvocation, ToolReply
from .receiver_store import create_receiver, open_receiver


@dataclass(frozen=True)
class ReceiverLease:
    partition: str
    owner: str
    epoch: int
    key: str

    def __post_init__(self):
        _hex(self.partition)
        _token(self.owner)
        _hex(self.key)
        if type(self.epoch) is not int or not 0 <= self.epoch < 2**63 - 1:
            raise CellError("invalid receiver epoch")

    @property
    def binding(self):
        self.__post_init__()
        return [
            self.partition,
            self.owner,
            self.epoch,
            hashlib.sha256(self.key.encode()).hexdigest(),
        ]


class ReceiverLedger:
    """Bounded, receiver-owned effect and handoff state; no automatic retry."""

    def __init__(self, path, receiver_id):
        self.db = open_receiver(path, receiver_id)

    @classmethod
    def create(cls, path, receiver_id):
        create_receiver(path, receiver_id)
        return cls(path, receiver_id)

    def close(self):
        self.db.close()

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _authorize(self, lease, phase):
        if type(lease) is not ReceiverLease:
            raise CellError("canonical receiver lease required")
        row = self.db.execute(
            "SELECT * FROM authority WHERE partition=?", (lease.partition,)
        ).fetchone()
        binding = lease.binding
        if (
            row is None
            or row["owner"] != lease.owner
            or row["epoch"] != lease.epoch
            or row["phase"] != phase
            or not hmac.compare_digest(row["key_hash"], binding[3])
        ):
            raise CellError("receiver lease is fenced or unrecognized")
        return row

    def provision(self, lease, component_digest, tool_digest):
        """Trusted host creates one initial authority; reopening cannot reset it."""
        if type(lease) is not ReceiverLease or lease.epoch != 0:
            raise CellError("provisioning requires canonical epoch zero")
        _hex(component_digest)
        _hex(tool_digest)
        with self._transaction():
            row = self.db.execute(
                "SELECT * FROM authority WHERE partition=?", (lease.partition,)
            ).fetchone()
            if row is not None:
                existing = self._authorize(lease, "active")
                if (existing["component"], existing["tool_digest"]) != (
                    component_digest,
                    tool_digest,
                ):
                    raise RequestConflict("provisioned component changed")
                return
            if self.db.execute("SELECT count(*) FROM authority").fetchone()[0] >= 128:
                raise CellError("receiver partition capacity exhausted")
            self.db.execute(
                "INSERT INTO authority VALUES(?,?,?,?,?,?,'active')",
                (*lease.binding, component_digest, tool_digest),
            )

    def prepare(self, transfer_id, source, target, component_digest, manifest):
        """Fence both writers while retaining the exact, host-supplied custody map.

        The map is bound, not independently verified as a CellOwner checkpoint.
        Only a qualified coordinator may use this primitive for actual migration.
        """
        _token(transfer_id)
        _hex(component_digest)
        if type(manifest) is not dict:
            raise CellError("custody manifest must be a bounded mapping")
        if (
            type(source) is not ReceiverLease
            or type(target) is not ReceiverLease
            or source.partition != target.partition
            or source.owner == target.owner
            or source.key == target.key
            or target.epoch != source.epoch + 1
        ):
            raise CellError("handoff requires a distinct next-epoch owner and key")
        encoded = _bounded_json(manifest, 65536)
        binding = _bounded_json([source.binding, target.binding, component_digest])
        with self._transaction():
            prior = self.db.execute(
                "SELECT * FROM transfers WHERE id=?", (transfer_id,)
            ).fetchone()
            if prior is not None:
                if (prior["binding"], prior["manifest"]) != (binding, encoded):
                    raise RequestConflict("handoff ID is bound to different custody")
                return
            self._authorize(source, "active")
            if self.db.execute("SELECT count(*) FROM transfers").fetchone()[0] >= 4096:
                raise CellError("receiver handoff capacity exhausted")
            self.db.execute(
                "INSERT INTO transfers VALUES(?,?,?,NULL)",
                (transfer_id, binding, encoded),
            )
            self.db.execute(
                "UPDATE authority SET owner=?,epoch=?,key_hash=?,component=?,phase='prepared' WHERE partition=?",
                (*target.binding[1:], component_digest, target.partition),
            )

    def commit(self, transfer_id, target):
        """The designated target activates once; exact replays return retained bytes."""
        _token(transfer_id)
        if type(target) is not ReceiverLease:
            raise CellError("canonical receiver lease required")
        with self._transaction():
            row = self.db.execute(
                "SELECT * FROM transfers WHERE id=?", (transfer_id,)
            ).fetchone()
            if row is None or json.loads(row["binding"])[1] != target.binding:
                raise CellError("target does not own the prepared handoff")
            if row["receipt"] is not None:
                return json.loads(row["receipt"])
            self._authorize(target, "prepared")
            receipt = _bounded_json(
                {
                    "schema": "hepta.receiver-handoff.v1",
                    "transfer_id": transfer_id,
                    "owner": target.owner,
                    "epoch": target.epoch,
                    "partition": target.partition,
                    "manifest_sha256": hashlib.sha256(
                        row["manifest"].encode()
                    ).hexdigest(),
                }
            )
            self.db.execute(
                "UPDATE authority SET phase='active' WHERE partition=?",
                (target.partition,),
            )
            self.db.execute(
                "UPDATE transfers SET receipt=? WHERE id=?", (receipt, transfer_id)
            )
            return json.loads(receipt)

    @staticmethod
    def _invocation(invocation):
        if type(invocation) is not ToolInvocation:
            raise CellError("canonical tool invocation required")
        # Validate the retained snapshot, never the caller's mutable arguments.
        encoded = _bounded_json(asdict(invocation), 32768)
        invocation = ToolInvocation(**json.loads(encoded))
        for value in (
            invocation.operation_id,
            invocation.tool_digest,
            invocation.partition_digest,
            invocation.component_digest,
        ):
            _hex(value)
        _token(invocation.request_id)
        if (
            invocation.tool_name != "append_record"
            or type(invocation.arguments) is not dict
            or set(invocation.arguments) != {"record"}
            or type(invocation.epoch) is not int
            or not 0 <= invocation.epoch < 2**63 - 1
            or type(invocation.max_work_units) is not int
            or not 1 <= invocation.max_work_units <= 1000000000
            or type(invocation.deadline_ms) is not int
            or not 1 <= invocation.deadline_ms <= 60000
        ):
            raise CellError("unsupported bounded append request")
        return encoded

    def invoke(self, lease, invocation):
        encoded = self._invocation(invocation)
        # BEGIN IMMEDIATE can wait while the caller changes nested arguments.
        # Authority checks, the effect and its receipt must use these same bytes.
        invocation = ToolInvocation(**json.loads(encoded))
        with self._transaction():
            authority = self._authorize(lease, "active")
            if (
                invocation.partition_digest != lease.partition
                or invocation.epoch != lease.epoch
                or invocation.component_digest != authority["component"]
                or invocation.tool_digest != authority["tool_digest"]
            ):
                raise CellError("request differs from the receiver authority")
            prior = self.db.execute(
                "SELECT invocation,receipt FROM effects WHERE partition=? AND (request=? OR operation=?)",
                (lease.partition, invocation.request_id, invocation.operation_id),
            ).fetchone()
            if prior is not None:
                if prior["invocation"] != encoded:
                    raise RequestConflict(
                        "effect ID is already bound to different inputs"
                    )
                return json.loads(prior["receipt"])
            if self.db.execute("SELECT count(*) FROM effects").fetchone()[0] >= 4096:
                raise CellError("receiver effect capacity exhausted")
            record = _bounded_json(invocation.arguments["record"], 16384)
            receipt = _bounded_json(
                {
                    "schema": "hepta.receiver-effect.v1",
                    "operation_id": invocation.operation_id,
                    "partition": lease.partition,
                    "request_id": invocation.request_id,
                    "owner": lease.owner,
                    "epoch": lease.epoch,
                    "outcome": "committed",
                    "record_sha256": hashlib.sha256(record.encode()).hexdigest(),
                }
            )
            self.db.execute(
                "INSERT INTO effects VALUES(?,?,?,?,?,?)",
                (
                    lease.partition,
                    invocation.request_id,
                    invocation.operation_id,
                    encoded,
                    record,
                    receipt,
                ),
            )
            return json.loads(receipt)

    def readback(self, invocation):
        """An absent row is UNKNOWN, never evidence authorizing retransmission."""
        encoded = self._invocation(invocation)
        invocation = ToolInvocation(**json.loads(encoded))
        row = self.db.execute(
            "SELECT invocation,receipt FROM effects WHERE partition=? AND (request=? OR operation=?)",
            (
                invocation.partition_digest,
                invocation.request_id,
                invocation.operation_id,
            ),
        ).fetchone()
        if row is None:
            return None
        if row["invocation"] != encoded:
            raise RequestConflict("readback does not name the original effect")
        return json.loads(row["receipt"])


class ReceiverPort:
    """Existing ToolCell adapter; receiver timing cannot stand in for owner timing."""

    def __init__(self, ledger, lease):
        self.ledger, self.lease = ledger, lease

    def invoke(self, invocation):
        return ToolReply(self.ledger.invoke(self.lease, invocation), 1)

    def readback(self, invocation):
        receipt = self.ledger.readback(invocation)
        return None if receipt is None else ToolReply(receipt, 1, None)
