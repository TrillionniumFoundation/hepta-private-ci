"""Read-only, fail-closed audit of CTRL content delivery identity.

Input contains *digests*, not private candidate text. This checks receipt
consistency, not the semantics of delivery or the evaluator's correctness.
"""
import argparse
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
            if field in item and (not isinstance(item[field], str) or not HEX64.fullmatch(item[field])):
                errors.append(f"{stage}:INVALID_{field}")
        for field in ("candidate_id", "delivery_receipt_id"):
            if field in item and (not isinstance(item[field], str) or not item[field].strip()):
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
    if stages["delivered"]["delivery_receipt_id"] != stages["evaluated"]["delivery_receipt_id"]:
        errors.append("EVALUATOR_DELIVERY_RECEIPT_DRIFT")
    score = stages["evaluated"]["score"]
    if isinstance(score, bool) or not isinstance(score, (float, int)) or not (0 <= score <= 1):
        errors.append("INVALID_SCORE")
    return not errors, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    obj = json.loads(args.receipt.read_text(encoding="utf-8"))
    passed, errors = audit(obj)
    print(json.dumps({"pass": passed, "errors": errors}, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
