"""Faults use actual signed receipts and require zero gate or owner mutation."""

from copy import deepcopy
import json

from experiments.adaptive_neuron_v2.ledger import sha, write_json_exclusive

from .transport import file_manifest


def reject(root, gate, kind, value, label):
    before = (gate.phase, gate.sequence, gate.head, sha(gate.path))
    files = file_manifest(root / "owner")
    try:
        gate.append(kind, gate.case, value)
    except ValueError as error:
        reason = str(error)
    else:
        raise AssertionError(
            "Mismatched signed or native receipt was accepted: " + label
        )
    after = (gate.phase, gate.sequence, gate.head, sha(gate.path))
    if after != before or file_manifest(root / "owner") != files:
        raise AssertionError("Rejected receipt changed gate or owner: " + label)
    write_json_exclusive(
        root / "negative" / f"{gate.case}.{label}.json",
        {
            "label": label,
            "case": gate.case,
            "kind": kind,
            "candidate": value,
            "rejection": reason,
            "gate_before": before,
            "gate_after": after,
            "owner_files_unchanged": True,
        },
    )


def corrupt_closure(root, gate, closure):
    changed = deepcopy(closure)
    changed["binding"]["terminal_checkpoint"] = "1" * 64
    reject(root, gate, "closure_accepted", changed, "changed_terminal_binding")


def corrupt_settlement(root, gate, result, label):
    value = {
        "native_response": deepcopy(result),
        "settlement_file": json.loads(
            (root / "owner" / gate.case / "SETTLEMENT.json").read_text()
        ),
    }
    if label == "resource_record_digest":
        value["native_response"]["record"]["record_digest"] = "2" * 64
    elif label == "settlement_outcome_binding":
        value["settlement_file"]["outcome_digest"] = "3" * 64
    else:
        raise ValueError("Unknown settlement fault")
    reject(root, gate, "settled", value, label)
