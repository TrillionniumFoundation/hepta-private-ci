"""Bind a proposed credit experiment to actual updated-student A trajectories."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
from cell_experiments import data, protocol_v3, repo_execution

PARENT = "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786"
INDEX = "44b49dc400d756daa6552f6d89aee409513f78abb54a5c5fbf26e50ad43391be"


def main(originals, output):
    index_file = originals / "ARCHIVE_MANIFEST.json"
    if hashlib.sha256(index_file.read_bytes()).hexdigest() != INDEX:
        raise ValueError("original completed run index differs")
    index = data._parse(index_file.read_bytes())

    def original(name):
        path = originals / name
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != index["files"][name]["sha256"]:
            raise ValueError("original file changed: " + name)
        return data._parse(raw)

    training = original("retained/TRAIN_RECORDS.json")
    if data.digest(training) != "f3206c37a200890561b47b3823a39a5419189d06861c161f5c92ca7de5c6d644":
        raise ValueError("authorized A records differ")
    repo_execution.load_catalog("open")
    records, receipts, labels = [], [], []
    for number, record in enumerate(training):
        if record["split"] != "train" or not record["authorization"]["training_allowed"]:
            raise ValueError("A-only authorized source required")
        prefix = f"retained/evaluation/all_actions/A_retention/{number}/"
        if original(prefix + "ORIGINAL_RECORD.json") != record:
            raise ValueError("actual current-policy task differs")
        events, steps = [], []
        chosen, chosen_source = None, None
        for attempt in range(2):
            request = original(prefix + f"REQUEST-{attempt}.json")
            prediction = original(prefix + f"OUTPUT-{attempt}.json")
            verification = original(prefix + f"VERIFICATION-{attempt}.json")
            if (prediction["loaded_model_digest"] != PARENT or
                    prediction["messages_sha256"] != data.digest(request["task"]["messages"]) or
                    verification["answer_sha256"] != hashlib.sha256(prediction["answer"].encode()).hexdigest()):
                raise ValueError("current student generation or verification binding differs")
            step = {"request": request, "output": prediction, "verification": verification}
            step_digest = data.digest(step)
            steps.append({"original_prefix": prefix, "attempt": attempt, "receipt_sha256": step_digest})
            events.append({"actor": "student", "kind": "action", "content": prediction["answer"],
                           "executed": verification["result"].get("executed", False),
                           "receipt_sha256": step_digest, "policy_sha256": PARENT,
                           "receipt_actor": "student", "trainable": True,
                           "target_verified": verification["success"]})
            events.append({"actor": "environment", "kind": "observation",
                           "content": protocol_v3.feedback(verification), "executed": False,
                           "trainable": False})
            if chosen is None and verification["success"]:
                chosen, chosen_source = prediction["answer"], "earliest verified current-policy output"
            labels.append({"task_id": record["task_id"], "target": attempt,
                           "verified": verification["success"], "origin": "actual current policy"})
        if chosen is None:
            chosen, chosen_source = record["final_answer"], "existing authored A reference fallback"
        derived = copy.deepcopy(record)
        derived["record_id"] += "/current-policy-credit-v1"
        derived["teacher_id"] = None
        derived["final_answer"] = chosen
        target_check = data.verify_answer(derived, chosen)
        if not target_check["success"]:
            raise ValueError("selected A correction does not pass original strict verification")
        events.append({"actor": "curator", "kind": "correction", "content": chosen,
                       "executed": False, "trainable": True, "target_verified": True,
                       "correction_source": chosen_source})
        labels.append({"task_id": record["task_id"], "target": 2,
                       "verified": True, "origin": chosen_source})
        derived["trajectory"] = [{"index": i, **event} for i, event in enumerate(events)]
        derived["derivation"] = {"source_model_digest": PARENT, "original_record_digest": data.digest(record),
                                 "current_policy_steps": steps, "correction_source": chosen_source,
                                 "correction_verification": target_check,
                                 "independent_sample_increment": 0,
                                 "new_model_calls_performed_by_builder": 0}
        derived["verified_outcome"] = {"success": True, "receipt_sha256": target_check["receipt_sha256"],
                                       "verifier_name": "repo_patch", "verifier_version": "1"}
        protocol_v3.require_prepared(derived)
        data.validate_record(derived)
        records.append(derived)
        receipts.append(target_check)
    output.mkdir(exist_ok=False)
    with (output / "records.jsonl").open("xb") as stream:
        for record in records:
            stream.write(data.canonical(record) + b"\n")
    manifest = {"schema": "hepta.current-policy-credit-corpus.v1", "parent_model_digest": PARENT,
                "original_index_sha256": INDEX, "original_execution_source": "992f2b3de51902448abf5743f94179bf40e11b6d",
                "records_digest": data.digest(records), "records_file_sha256": hashlib.sha256((output / "records.jsonl").read_bytes()).hexdigest(),
                "records": 6, "actual_current_policy_calls_reused": 12,
                "verified_current_actions": sum(row["verified"] for row in labels if row["target"] < 2),
                "unverified_current_actions": sum(not row["verified"] for row in labels if row["target"] < 2),
                "correction_checks": receipts, "target_labels": labels,
                "new_model_calls": 0, "new_verifier_calls": 6, "B_data_loaded": False,
                "independent_users": 0, "new_source_increment": 0, "weights_updated": False,
                "native_adoption": False, "scientific_confirmation_qualified": False}
    (output / "CORPUS.json").write_bytes(data.canonical(manifest) + b"\n")
    print(json.dumps({key: value for key, value in manifest.items() if key not in ("correction_checks", "target_labels")}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("originals", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    main(arguments.originals, arguments.output)
