"""Focused metadata controls; synthetic prediction metadata never represents E data."""

import copy
import json
from pathlib import Path
import time

from build_selection import select
from scorer_contract import FEATURE_ROLES, content_hash, freeze_prediction_metadata


HERE = Path(__file__).resolve().parent


def main():
    started, cpu = time.monotonic(), time.process_time()
    selection = json.loads((HERE / "evidence/SELECTION.json").read_text())
    ledger = json.loads((HERE / "evidence/LEDGER.json").read_text())
    candidates, results = selection["all_42_candidates"], []

    def reject(name, operation):
        try:
            operation()
        except ValueError as error:
            results.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("negative control accepted: " + name)

    families, roster = select(candidates)
    if families != ledger["families"] or len(roster) != 21:
        raise ValueError("actual frozen selection differs")
    results.append({"case": "actual_42_to_21_selection", "passed": True})
    reject("missing_seed", lambda: select(candidates[:-1]))
    reject("duplicate_fit", lambda: select(candidates[:-1] + [candidates[0]]))
    bad = copy.deepcopy(candidates); bad[0]["D_macro_f1"] = float("nan")
    reject("nonfinite_quality", lambda: select(bad))
    bad_bool = copy.deepcopy(candidates); bad_bool[0]["D_macro_f1"] = True
    reject("boolean_quality", lambda: select(bad_bool))
    tie = copy.deepcopy(candidates)
    for row in tie:
        row["D_macro_f1"] = .25
    if any(row["selected_learning_rate"] != .001 for row in select(tie)[0]):
        raise ValueError("exact tie did not select lower LR")
    results.append({"case": "exact_tie_lower_common_LR", "passed": True})
    inadequate = copy.deepcopy(candidates)
    for row in inadequate:
        if row["arm"] == "hcsn" and row["learning_rate"] == .003:
            row["adequate"] = False
    h = next(r for r in select(inadequate)[0] if r["arm"] == "hcsn")
    if h["selected_learning_rate"] != .003 or h["selected_all_three_adequate"]:
        raise ValueError("inadequate winning LR was replaced or admitted")
    results.append({"case": "higher_mean_inadequate_LR_remains_winner_and_blocked", "passed": True})
    bindings = [{"name": r["name"], "model_binding_sha256": r["model_binding_sha256"]} for r in ledger["roster"]]
    fixture = {"schema": "isolated-confirmation-features-v1", "subject": "E", "rows": 8,
        "order_sha256": "a" * 64, "contains_activity_labels": False,
        "artifacts": {name: {"sha256": "a" * 64, "bytes": 8} for name in FEATURE_ROLES}}
    predictions = [{**r, "feature_manifest_sha256": content_hash(fixture), "order_sha256": "a" * 64,
        "logits": {"sha256": "b" * 64, "bytes": 704}, "rows": 8, "classes": 11, "dtype": "float64",
        "completed_before_label_access": True} for r in bindings]
    signature = freeze_prediction_metadata(bindings, fixture, predictions)
    if signature["execution_authorization"] or signature["label_data_opened"]:
        raise ValueError("metadata validation must not authorize or access E")
    results.append({"case": "complete_synthetic_metadata_has_no_execution_authority", "passed": True})
    reject("missing_prediction", lambda: freeze_prediction_metadata(bindings, fixture, predictions[:-1]))
    reject("duplicate_prediction", lambda: freeze_prediction_metadata(bindings, fixture, predictions[:-1] + [predictions[0]]))
    changed = copy.deepcopy(predictions); changed[0]["model_binding_sha256"] = "c" * 64
    reject("changed_selected_model", lambda: freeze_prediction_metadata(bindings, fixture, changed))
    changed_order = copy.deepcopy(predictions); changed_order[0]["order_sha256"] = "c" * 64
    reject("changed_feature_order", lambda: freeze_prediction_metadata(bindings, fixture, changed_order))
    exposed = copy.deepcopy(fixture); exposed["artifacts"]["activity_labels"] = {"sha256": "d" * 64, "bytes": 8}
    reject("labels_in_feature_roles", lambda: freeze_prediction_metadata(bindings, exposed, predictions))
    early = copy.deepcopy(predictions); early[0]["completed_before_label_access"] = False
    reject("prediction_after_label_access", lambda: freeze_prediction_metadata(bindings, fixture, early))
    bool_count = copy.deepcopy(predictions); bool_count[0]["logits"]["bytes"] = True
    reject("boolean_artifact_size", lambda: freeze_prediction_metadata(bindings, fixture, bool_count))
    result = {"schema": "hcsn-D-selection-contract-controls-v1", "cases": results, "passed": len(results),
        "source_sha256": {name: __import__("hashlib").sha256((HERE / name).read_bytes()).hexdigest()
                          for name in ["build_selection.py", "scorer_contract.py", "controls.py"]},
        "scope": "Actual D selection plus synthetic metadata rejection; no E features, labels, logits or model results generated.",
        "body_wall_seconds": time.monotonic() - started, "body_cpu_seconds": time.process_time() - cpu,
        "model_forward_backward_optimizer_calls": 0, "E_payload_or_labels_accessed": False}
    with (HERE / "evidence/CONTROLS.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write("\n")
    print(json.dumps({"passed": len(results), "E_payload_or_labels_accessed": False, "model_operations": 0}))


if __name__ == "__main__":
    main()
