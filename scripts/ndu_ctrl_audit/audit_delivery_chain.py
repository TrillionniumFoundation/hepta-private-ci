"""Read-only, fail-closed audit of CTRL content delivery identity.

Input contains *digests*, not private candidate text. This checks receipt
consistency, not the semantics of delivery or the evaluator's correctness.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

HEX64 = re.compile(r"^[0-9a-f]{64}$")
STAGES = ("candidate", "selected", "serialized", "delivered", "evaluated")
REQUIRED = {
    "candidate": ("candidate_id", "payload_sha256"),
    "selected": ("candidate_id", "payload_sha256"),
    "serialized": ("candidate_id", "payload_sha256", "wire_sha256"),
    "delivered": ("candidate_id", "wire_sha256", "delivery_receipt_id"),
    "evaluated": ("candidate_id", "wire_sha256", "delivery_receipt_id", "score"),
}


def audit(record):
    """Return (pass, errors). Missing evidence is never interpreted as success."""
    errors = []
    if not isinstance(record, dict) or record.get("schema") != "ctrl.delivery-chain.v1":
        return False, ["BAD_SCHEMA"]
    stages = record.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        return False, ["MISSING_OR_UNKNOWN_STAGE"]
    for stage in STAGES:
        item = stages[stage]
        if not isinstance(item, dict):
            errors.append(f"{stage}:NOT_OBJECT")
            continue
        for field in REQUIRED[stage]:
            if field not in item or item[field] is None:
                errors.append(f"{stage}:MISSING_{field}")
        for field in ("payload_sha256", "wire_sha256"):
            if field in item and (
                not isinstance(item[field], str) or not HEX64.fullmatch(item[field])
            ):
                errors.append(f"{stage}:INVALID_{field}")
        for field in ("candidate_id", "delivery_receipt_id"):
            if field in item and (
                not isinstance(item[field], str) or not item[field].strip()
            ):
                errors.append(f"{stage}:INVALID_{field}")
    if errors:
        return False, errors
    identities = [stages[s]["candidate_id"] for s in STAGES]
    if len(set(identities)) != 1:
        errors.append("CANDIDATE_ID_DRIFT")
    payloads = [stages[s]["payload_sha256"] for s in STAGES[:3]]
    if len(set(payloads)) != 1:
        errors.append("SELECTED_PAYLOAD_DRIFT")
    wires = [stages[s]["wire_sha256"] for s in STAGES[2:]]
    if len(set(wires)) != 1:
        errors.append("WIRE_PAYLOAD_DRIFT")
    if (
        stages["delivered"]["delivery_receipt_id"]
        != stages["evaluated"]["delivery_receipt_id"]
    ):
        errors.append("EVALUATOR_DELIVERY_RECEIPT_DRIFT")
    score = stages["evaluated"]["score"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (float, int))
        or not (0 <= score <= 1)
    ):
        errors.append("INVALID_SCORE")
    return not errors, errors


OBSERVED_SCHEMA = "ctrl.delivery-chain.observed.v2"
IDENTITY_FIELDS = (
    "source_tree_sha256",
    "evaluator_sha256",
    "run_id",
    "task_id",
    "episode_id",
)


def audit_observed(record):
    """Check declared observed receipts; this does NOT authenticate their issuer.

    A consistent synthetic or self-asserted receipt cannot prove an owner ran,
    that a candidate inventory was complete, or that a score was correct.
    """
    if not isinstance(record, dict) or record.get("schema") != OBSERVED_SCHEMA:
        return False, ["BAD_OBSERVED_SCHEMA"]
    # Retain all v1 byte-chain checks without changing the historical format.
    _, original_errors = audit({**record, "schema": "ctrl.delivery-chain.v1"})
    errors = list(original_errors)
    identity = record.get("identity")
    identity_ok = (
        isinstance(identity, dict)
        and all(
            isinstance(identity.get(key), str) and bool(identity[key].strip())
            for key in IDENTITY_FIELDS
        )
        and all(
            HEX64.fullmatch(identity[key])
            for key in ("source_tree_sha256", "evaluator_sha256")
        )
        and type(identity.get("evidence_cutoff_ns")) is int
        and identity["evidence_cutoff_ns"] >= 0
    )
    identity_hash = None
    if not identity_ok:
        errors.append("INVALID_OWNER_BOUND_IDENTITY")
    else:
        canonical = json.dumps(
            identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        identity_hash = hashlib.sha256(canonical).hexdigest()

    launch = record.get("launch")
    launch_ok = (
        isinstance(launch, dict)
        and type(launch.get("exit_code")) is int
        and launch["exit_code"] == 0
        and launch.get("enforced_before_actor_exec") is True
        and launch.get("callback_error") is None
        and launch.get("protocol_error") is None
        and launch.get("limit_reason") is None
        and isinstance(launch.get("wire_sha256"), str)
        and bool(HEX64.fullmatch(launch["wire_sha256"]))
    )
    if not launch_ok:
        errors.insert(0, "ISOLATED_ACTOR_NOT_COMPLETED")
    elif identity_ok and (
        launch.get("run_id") != identity["run_id"]
        or launch.get("task_id") != identity["task_id"]
        or launch.get("episode_id") != identity["episode_id"]
    ):
        errors.insert(0, "LAUNCH_IDENTITY_DRIFT")

    stages = record.get("stages")
    if not isinstance(stages, dict) or any(
        not isinstance(stages.get(stage), dict) for stage in STAGES
    ):
        return False, errors
    if launch_ok and launch["wire_sha256"] != stages["serialized"].get("wire_sha256"):
        errors.append("ACTOR_WIRE_DRIFT")

    # A stable selected index is essential: a candidate-set membership claim
    # alone cannot reconstruct the selected index after the fact.
    inventory = record.get("candidate_inventory")
    inventory_ok = (
        isinstance(inventory, list)
        and 0 < len(inventory) <= 1024
        and all(
            isinstance(item, dict)
            and isinstance(item.get("candidate_id"), str)
            and bool(item["candidate_id"].strip())
            and isinstance(item.get("payload_sha256"), str)
            and bool(HEX64.fullmatch(item["payload_sha256"]))
            for item in inventory
        )
    )
    if not inventory_ok or len({x["candidate_id"] for x in inventory}) != len(
        inventory
    ):
        errors.append("INVALID_CANDIDATE_INVENTORY")
    selected_index = record.get("selected_index")
    if (
        type(selected_index) is not int
        or not inventory_ok
        or not 0 <= selected_index < len(inventory)
    ):
        errors.append("UNKNOWN_SELECTED_INDEX")
    else:
        chosen = inventory[selected_index]
        selected = stages["selected"]
        if chosen["candidate_id"] != selected.get("candidate_id") or chosen[
            "payload_sha256"
        ] != selected.get("payload_sha256"):
            errors.append("SELECTED_INDEX_PAYLOAD_DRIFT")

    last_time = -1
    for stage in STAGES:
        item = stages[stage]
        if identity_hash is None or item.get("identity_sha256") != identity_hash:
            errors.append(f"{stage}:IDENTITY_BINDING_DRIFT")
        observed_ns = item.get("observed_ns")
        if (
            type(observed_ns) is not int
            or observed_ns < 0
            or observed_ns < last_time
            or (identity_ok and observed_ns > identity["evidence_cutoff_ns"])
        ):
            errors.append(f"{stage}:INVALID_OBSERVATION_TIME")
        else:
            last_time = observed_ns
    return not errors, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument(
        "--observed",
        action="store_true",
        help="require v2 identity, launch and selected-index claims",
    )
    args = parser.parse_args()
    obj = json.loads(args.receipt.read_text(encoding="utf-8"))
    passed, errors = audit_observed(obj) if args.observed else audit(obj)
    print(
        json.dumps(
            {
                "pass": passed,
                "errors": errors,
                "scope": "declared_observed_receipt_consistency"
                if args.observed
                else "v1_digest_consistency",
                "owner_signature_verified": False,
                "production_admitted": False,
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
