"""Exact optional HIA continuation profile for existing experimental owners.

Activation adds only the known table before any HIA history exists. Missing
continuations are never recreated. Pending intents can precede native BEGIN;
their absent results remain unresolved and never authorize another dispatch.
"""

import hashlib
import json

from .component_types import CellError, ComponentIdentity, _bounded_json, _hex, digest
from .owner_hia_state import validate_native_state


HIA_SCHEMA = """CREATE TABLE hia_cell_calls(
            partition TEXT NOT NULL, request TEXT NOT NULL,
            identity TEXT NOT NULL, fingerprint TEXT NOT NULL,
            binding TEXT NOT NULL, state BLOB NOT NULL, phase TEXT NOT NULL,
            inner_result TEXT, result TEXT, native_ns INTEGER NOT NULL,
            error TEXT, PRIMARY KEY(partition, request))"""


def _require(condition, reason):
    if not condition:
        raise CellError("retained HIA owner profile is inconsistent: " + reason)


def _same_json(left, right):
    """JSON types are significant; Python bool/int/float equality is weaker."""
    return _bounded_json(left) == _bounded_json(right)


def validate_hia_profile(db, *, enabled):
    """Cross-check the optional table against independently retained owner rows."""
    identities = [
        json.loads(row[0]) for row in db.execute("SELECT identity FROM cells")
    ]
    identities += [
        json.loads(row[0])["identity"]
        for row in db.execute("SELECT snapshot FROM checkpoints")
    ]
    cursor = db.execute("SELECT * FROM intents")
    names = [column[0] for column in cursor.description]
    intents = {
        (row["partition"], row["request"]): row
        for row in (dict(zip(names, values)) for values in cursor)
    }
    identities += [json.loads(row["identity"]) for row in intents.values()]
    if not enabled:
        _require(
            not any(
                identity["implementation"] == "hepta.hia-cell.v1"
                for identity in identities
            ),
            "HIA history has lost its continuation table",
        )
        return
    try:
        sequences = dict(db.execute("SELECT partition,sequence FROM cells"))
        cursor = db.execute("SELECT * FROM hia_cell_calls")
        names = [column[0] for column in cursor.description]
        calls = {
            (row["partition"], row["request"]): row
            for row in (dict(zip(names, values)) for values in cursor)
        }
        for key, call in calls.items():
            _require(key in intents, "orphan continuation")
            intent = intents[key]
            identity = ComponentIdentity(**json.loads(intent["identity"]))
            _require(
                identity.implementation == "hepta.hia-cell.v1"
                and call["identity"] == identity.digest
                and call["fingerprint"] == intent["fingerprint"],
                "original intent binding",
            )
            binding = json.loads(call["binding"])
            # Mirror the pinned transport's BridgeBinding structure without
            # loading a native image or executing any recovery operation.
            hashes = (
                "candidate_sha256",
                "cell_sha256",
                "request_sha256",
                "input_sha256",
            )
            _require(
                type(binding) is dict
                and set(binding) == {*hashes, "sequence", "result_limit"},
                "native binding fields",
            )
            for name in hashes:
                _hex(binding[name])
            _require(
                type(binding["sequence"]) is int and 1 <= binding["sequence"] < 1 << 64,
                "native binding sequence",
            )
            if intent["status"] == "pending":
                _require(
                    binding["sequence"] == sequences[key[0]] + 1,
                    "pending native sequence differs from original owner",
                )
            _require(
                type(binding["result_limit"]) is int
                and 1 <= binding["result_limit"] <= 65536,
                "native result limit",
            )
            _require(
                binding["input_sha256"]
                == hashlib.sha256(intent["payload"].encode()).hexdigest(),
                "original input digest",
            )
            _require(
                binding["request_sha256"]
                == digest([*key, intent["generation"], intent["fingerprint"]]),
                "original request digest",
            )
            _require(
                type(call["native_ns"]) is int and call["native_ns"] >= 0,
                "native elapsed observation",
            )
            _require(
                call["phase"]
                in {
                    "pending",
                    "cell_returned",
                    "completed",
                    "unknown",
                    "cancel_requested",
                },
                "continuation phase",
            )
            _require(
                (call["result"] is not None) == (call["phase"] == "completed"),
                "terminal result or phase missing",
            )
            validate_native_state(call, binding, intent["payload"].encode())
            if int.from_bytes(call["state"][184:192], "little") == 1:
                cancellation = db.execute(
                    "SELECT identity FROM cancellations WHERE partition=? AND request=?",
                    key,
                ).fetchone()
                _require(
                    cancellation is not None and cancellation[0] == call["identity"],
                    "native cancellation lacks the original owner intent",
                )
        for key, intent in intents.items():
            identity = json.loads(intent["identity"])
            if identity["implementation"] != "hepta.hia-cell.v1":
                continue
            cancellation = db.execute(
                "SELECT identity FROM cancellations WHERE partition=? AND request=?",
                key,
            ).fetchone()
            if cancellation is not None:
                _require(
                    cancellation[0] == ComponentIdentity(**identity).digest,
                    "owner cancellation identity differs from original HIA intent",
                )
            if intent["status"] == "committed":
                _require(key in calls, "committed intent has lost its continuation")
                _require(
                    calls[key]["phase"] == "completed",
                    "committed intent has lost its result",
                )
            call = calls.get(key)
            if call is None or call["phase"] != "completed":
                continue
            # Native completion may be durable before owner settlement. Its
            # retained result must also be checked before readback can use it.
            _require(
                call["inner_result"] is not None,
                "terminal continuation has lost its inner result",
            )
            result, inner = (
                json.loads(value) for value in (call["result"], call["inner_result"])
            )
            for value, limit in ((result, 262144), (inner, 65536)):
                _require(
                    type(value) is dict
                    and set(value) == {"output", "state", "work_units"},
                    "retained result fields",
                )
                _bounded_json(value, limit)
                _require(
                    type(value["work_units"]) is int and value["work_units"] >= 0,
                    "retained result work",
                )
            _require(
                _same_json(result["state"], inner["state"])
                and result["work_units"] == inner["work_units"]
                and _same_json(result["output"]["cell"], inner["output"]),
                "inner result differs",
            )
            binding = json.loads(call["binding"])
            native = result["output"]["hia"]
            _require(
                _same_json(native["binding"], binding)
                and native["candidate_sha256"] == binding["candidate_sha256"]
                and native["terminal_action"] == "COMPLETE",
                "terminal binding differs",
            )
            _require(
                type(native["native_wall_ns"]) is int and native["native_wall_ns"] >= 0,
                "terminal native elapsed observation",
            )
            _require(
                native["native_state_sha256"]
                == hashlib.sha256(call["state"]).hexdigest()
                and native["native_wall_ns"] == call["native_ns"],
                "terminal state differs",
            )
            _require(
                identity["configuration_digest"]
                == digest(
                    [
                        binding["cell_sha256"],
                        binding["candidate_sha256"],
                        native["image_sha256"],
                    ]
                ),
                "candidate or native image differs",
            )
            if intent["status"] == "committed":
                receipt = json.loads(intent["receipt"])
                _require(
                    _same_json(result["output"], receipt["output"])
                    and result["work_units"] == receipt["work_units"],
                    "owner receipt differs from native result",
                )
                _require(
                    _same_json(binding["sequence"], receipt["sequence"]),
                    "committed native sequence differs",
                )
                if receipt["state_applied"]:
                    _require(
                        receipt["state_digest"]
                        == hashlib.sha256(
                            _bounded_json(result["state"], 262144).encode()
                        ).hexdigest(),
                        "applied state differs",
                    )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, CellError):
            raise
        raise CellError(
            "retained HIA owner profile contains invalid records"
        ) from error


def enable_hia_profile(db):
    """Explicit, atomic base-to-HIA activation; complete legacy profiles reopen."""
    from .owner_store import _expected_schema, _schema, _validate

    if db.in_transaction:
        raise CellError("HIA profile activation requires its own owner transaction")
    db.execute("BEGIN IMMEDIATE")
    try:
        _validate(db, None)
        if _schema(db) == _expected_schema():
            db.execute(HIA_SCHEMA)
        db.commit()
    except BaseException:
        db.rollback()
        raise
