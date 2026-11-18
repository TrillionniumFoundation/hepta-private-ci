"""Check retained owner conservation laws without replaying any component.

These relations detect missing or inconsistent rows in the unchanged schema.
They cannot establish external freshness of a consistently replaced database.
"""

from dataclasses import asdict
from bisect import bisect_right
import hashlib
import json

from .component_types import Budget, CellError, ComponentIdentity, Partition
from .component_types import _bounded_json, _hex, digest


def _require(value, message):
    if not value:
        raise CellError("owner history is inconsistent: " + message)


def _rows(db, table):
    cursor = db.execute("SELECT * FROM " + table)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def _integer(value, minimum=0, maximum=2**63 - 1):
    _require(type(value) is int and minimum <= value <= maximum, "integer range")
    return value


def validate_owner_history(db):
    """Validate the serialized state reached by committed owner operations."""
    try:
        _validate(db)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, CellError):
            raise
        raise CellError("owner history contains invalid retained records") from error


def _validate(db):
    tables = {
        name: _rows(db, name)
        for name in (
            "cells",
            "intents",
            "history",
            "checkpoints",
            "attempts",
            "cancellations",
            "migrations",
        )
    }
    cells = {cell["partition"]: cell for cell in tables["cells"]}
    for name, rows in tables.items():
        _require(
            all(row["partition"] in cells for row in rows), name + " orphan partition"
        )
    requests = {(row["partition"], row["request"]) for row in tables["intents"]}
    for name in ("attempts", "cancellations"):
        _require(
            all((row["partition"], row["request"]) in requests for row in tables[name]),
            name + " missing intent",
        )
    for partition, cell in cells.items():
        _hex(partition)
        epoch, sequence = _integer(cell["generation"]), _integer(cell["sequence"])
        _integer(cell["remaining"], minimum=-(10**12), maximum=10**12)
        policy = Budget(**json.loads(cell["budget"]))
        _require(json.loads(cell["budget"]) == asdict(policy), "budget fields missing")
        active = ComponentIdentity(**json.loads(cell["identity"]))
        history = {
            row["generation"]: row["identity"]
            for row in tables["history"]
            if row["partition"] == partition
        }
        _require(
            len(history) == epoch + 1 and set(history) == set(range(epoch + 1)),
            "epochs missing",
        )
        _require(
            history[epoch] == active.digest, "current identity differs from history"
        )
        for identity in history.values():
            _hex(identity)

        snapshots = []
        for row in tables["checkpoints"]:
            if row["partition"] != partition:
                continue
            _require(
                hashlib.sha256(row["snapshot"].encode()).hexdigest() == row["digest"],
                "checkpoint digest",
            )
            snapshot = json.loads(row["snapshot"])
            saved_epoch = _integer(snapshot["epoch"], maximum=epoch)
            _integer(snapshot["sequence"], maximum=sequence)
            _require(
                Partition(**snapshot["partition"]).digest == partition,
                "checkpoint partition",
            )
            _require(
                ComponentIdentity(**snapshot["identity"]).digest
                == history[saved_epoch],
                "checkpoint identity",
            )
            _require(
                _bounded_json(snapshot["budget"]) == cell["budget"]
                and _bounded_json(snapshot["retrieval_view"]) == cell["view"],
                "checkpoint policy",
            )
            _bounded_json(snapshot["state"], policy.max_state_bytes)
            snapshots.append(snapshot)
        initial = [
            saved
            for saved in snapshots
            if (saved["epoch"], saved["sequence"]) == (0, 0)
        ]
        _require(len(initial) == 1, "initial checkpoint missing or ambiguous")
        initial_work = _integer(initial[0]["remaining_work_units"], 1, 10**12)

        receipts, reservations = {}, []
        for intent in tables["intents"]:
            if intent["partition"] != partition:
                continue
            identity = ComponentIdentity(**json.loads(intent["identity"]))
            generation = _integer(intent["generation"], maximum=epoch)
            _require(identity.digest == history[generation], "intent identity")
            _require(
                (intent["budget"], intent["view"], intent["reserved"])
                == (cell["budget"], cell["view"], policy.max_work_units),
                "intent policy or reservation",
            )
            _require(
                intent["fingerprint"]
                == digest(
                    [
                        identity.digest,
                        generation,
                        intent["payload"],
                        intent["view"],
                        intent["budget"],
                    ]
                ),
                "intent fingerprint",
            )
            if intent["status"] == "pending":
                _require(
                    intent["receipt"] is None and generation == epoch,
                    "pending receipt or epoch",
                )
                reservations.append(intent["reserved"])
                continue
            _require(intent["status"] == "committed", "intent status")
            receipt = json.loads(intent["receipt"])
            order = _integer(receipt["sequence"], 1, sequence)
            _require(order not in receipts, "duplicate receipt sequence")
            expected = dict(
                request_id=intent["request"],
                partition_digest=partition,
                identity_digest=identity.digest,
                bundle_digest=identity.bundle_digest,
                epoch=generation,
            )
            _require(
                all(receipt[key] == value for key, value in expected.items()),
                "receipt identity",
            )
            work = _integer(receipt["work_units"], maximum=10**12)
            elapsed = _integer(receipt["elapsed_ns"])
            exceeded = (
                work > intent["reserved"] or elapsed > policy.max_elapsed_ms * 1000000
            )
            _require(
                receipt["status"] == ("budget_exceeded" if exceeded else "committed"),
                "receipt budget outcome",
            )
            _require(
                receipt["state_applied"] is (not exceeded or identity.effectful)
                and receipt["requires_recovery"] is (exceeded and identity.effectful),
                "receipt state policy",
            )
            _hex(receipt["state_digest"])
            _bounded_json(receipt["output"], policy.max_output_bytes)
            receipts[order] = receipt
        _require(len(reservations) <= 1, "multiple pending intents")
        _require(
            sequence == epoch + len(receipts),
            "sequence does not conserve committed intents",
        )
        _require(
            cell["remaining"]
            == initial_work
            - sum(row["work_units"] for row in receipts.values())
            - sum(reservations),
            "work budget does not conserve intents",
        )

        starts, offset = {}, 0
        points = {(saved["epoch"], saved["sequence"]): saved for saved in snapshots}
        by_epoch = {generation: [] for generation in history}
        orders = sorted(receipts)
        spent = [0]
        for order in orders:
            receipt = receipts[order]
            by_epoch[receipt["epoch"]].append(order)
            spent.append(spent[-1] + receipt["work_units"])
        for generation in range(epoch + 1):
            starts[generation] = offset
            _require((generation, offset) in points, "transition checkpoint missing")
            epoch_orders = by_epoch[generation]
            _require(
                epoch_orders == list(range(offset + 1, offset + len(epoch_orders) + 1)),
                "receipt epoch sequence",
            )
            offset += len(epoch_orders) + 1
        for saved in snapshots:
            order = saved["sequence"]
            end = starts.get(saved["epoch"] + 1, sequence + 1)
            _require(starts[saved["epoch"]] <= order < end, "checkpoint sequence epoch")
            _require(
                saved["remaining_work_units"]
                == initial_work - spent[bisect_right(orders, order)],
                "checkpoint work budget",
            )
            if order in receipts:
                _require(
                    hashlib.sha256(
                        _bounded_json(saved["state"], policy.max_state_bytes).encode()
                    ).hexdigest()
                    == receipts[order]["state_digest"],
                    "checkpoint state differs from receipt",
                )
        latest = receipts.get(sequence)
        expected_state = (
            latest["state_digest"]
            if latest
            else hashlib.sha256(
                _bounded_json(
                    points[(epoch, sequence)]["state"], policy.max_state_bytes
                ).encode()
            ).hexdigest()
        )
        _require(
            hashlib.sha256(cell["state"].encode()).hexdigest() == expected_state,
            "current state differs from retained result",
        )
