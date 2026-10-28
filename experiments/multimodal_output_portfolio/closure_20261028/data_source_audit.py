"""Source-ID and literal-original-byte audit before any new observer prediction."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from .data_sources import digest, save
from .data_v3_contract import load_plan, validate_receipt


def audit(root, output, extra_history):
    plan = load_plan(root)
    selected = {row["source_id"]: row for row in plan["selected"]}
    if len(selected) != 1024:
        raise ValueError("Distinct approved v3 allocation changed")
    prior = {}
    prior_inputs = {}
    for raw, pin in plan["prior_allocation_pins"].items():
        path = Path(raw)
        if digest(path.read_bytes()) != pin:
            raise ValueError("Historical source manifest changed")
        record = json.loads(path.read_text())
        prior_inputs[str(path)] = pin
        for row in record["events"]:
            if row["source_id"] in prior and prior[row["source_id"]] != row["source_sha256"]:
                raise ValueError("Historical source-byte identity conflict")
            prior[row["source_id"]] = row["source_sha256"]
    for path in extra_history:
        record = json.loads(path.read_text())
        prior_inputs[str(path)] = digest(path.read_bytes())
        rows = record.get("events", record.get("sources", []))
        if isinstance(rows, dict):
            rows = [{"source_id": key, "source_sha256": value} for key, value in rows.items()]
        for row in rows:
            pin = row.get("source_sha256", row.get("original_source_sha256", row.get("sha256")))
            if not isinstance(pin, str) or len(pin) != 64:
                raise ValueError("Historical source requires an actual original-video hash")
            if row["source_id"] in prior and prior[row["source_id"]] != pin:
                raise ValueError("Additional historical source-byte identity conflict")
            prior[row["source_id"]] = pin
    expected_roles = ("generator_train", "observer_train", "development")
    receipts, source_hashes, counts = [], defaultdict(list), Counter()
    for source in selected.values():
        folder = root / "prepared" / source["role"] / source["source_id"]
        path = folder / "RECEIPT.json"
        if source["role"] not in expected_roles:
            if folder.exists():
                raise ValueError("Held-out source access preceded the new observer fit")
            continue
        record = validate_receipt(root, plan, source, json.loads(path.read_text()))
        counts[source["role"]] += 1
        source_hashes[record["original_source_sha256"]].append(source["source_id"])
        receipts.append({"source_id": source["source_id"], "role": source["role"],
                         "original_source_sha256": record["original_source_sha256"],
                         "receipt_sha256": digest(path.read_bytes()), "retained_files": record["retained_files"]})
    if dict(counts) != {role: plan["roles"][role] for role in expected_roles}:
        raise ValueError("Incomplete approved training/development source preparation")
    if set(selected) & set(prior):
        raise ValueError("A current source ID overlaps recorded historical evidence")
    within = [ids for ids in source_hashes.values() if len(ids) > 1]
    prior_by_sha = defaultdict(list)
    for sid, pin in prior.items():
        prior_by_sha[pin].append(sid)
    cross = [{"original_source_sha256": pin, "current_ids": ids, "historical_ids": prior_by_sha[pin]}
             for pin, ids in source_hashes.items() if pin in prior_by_sha]
    result = {"schema": "hepta.closure.pre-fit-source-audit.v1", "source_protocol_sha256": plan["protocol_sha256"],
        "implementation_sha256": digest(Path(__file__).read_bytes()), "roles": dict(counts),
        "prepared_original_videos": len(receipts), "historical_original_hashes_checked": len(prior),
        "historical_input_files_sha256": prior_inputs, "within_current_literal_duplicates": within,
        "current_vs_historical_literal_duplicates": cross,
        "all_retained_tensor_and_feature_hashes_verified": True, "prepared_source_receipts": receipts,
        "heldout_pixels_or_predictions_accessed": False, "passed": not within and not cross,
        "scope": "original-video ID and literal byte identity only; no perceptual-duplicate or participant-independence guarantee"}
    save(output, result)
    if not result["passed"]:
        raise ValueError("Source independence audit failed; preserve the frozen allocation and evidence")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extra-history", type=Path, action="append", default=[])
    args = parser.parse_args()
    result = audit(args.assets, args.output, args.extra_history)
    print(json.dumps({key: result[key] for key in ("roles", "prepared_original_videos", "historical_original_hashes_checked", "passed")}))
