"""Join frozen D selection, all actual byte inventories and exact source aliases."""

import argparse
import hashlib
import json
from pathlib import Path

from scorer_contract import content_hash


HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def identity(path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(HERE)), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def publish_or_verify(path, value, verify_existing):
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if verify_existing:
        require(path.read_bytes() == data, "existing artifact differs from exact metadata recomposition")
    else:
        with path.open("xb") as stream:
            stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-existing", action="store_true", help="Compare existing ledger bytes; write no artifacts.")
    args = parser.parse_args()
    selection_path = HERE / "evidence/SELECTION.json"
    selection = read(selection_path)
    for name in ["SOURCE_FREEZE.json", "SUPPLEMENT_FREEZE.json", "PARENT_TARGET_FREEZE.json"]:
        freeze = read(HERE / name)
        for path, expected in freeze["files"].items():
            require(identity(HERE / path)["sha256"] == expected, "frozen preparation input changed")
    artifacts, measurements = {}, []
    readers = [("inventory", "inventory.py", "INVENTORY_REQUEST.json"),
               ("supplement", "inventory_supplement.py", "SUPPLEMENT_REQUEST.json"),
               ("parent-target", "inventory_parent_target.py", "PARENT_TARGET_REQUEST.json")]
    for directory, reader_name, request_name in readers:
        index = read(HERE / "evidence" / directory / "INVENTORY.json")
        require(index["selection_sha256"] == identity(selection_path)["sha256"], "one selection identity")
        require(index["source_sha256"] == identity(HERE / reader_name)["sha256"]
                and index["request_sha256"] == identity(HERE / request_name)["sha256"], "native reader and request identities")
        require(index["source_bytes_record_sha256"] == identity(HERE / "evidence" / directory / "SOURCE_BYTES.json")["sha256"],
                "native source-byte record identity")
        for row in index["outputs"]:
            path = HERE / "evidence" / directory / Path(row["file"]).name
            require(identity(path)["sha256"] == row["sha256"] and path.stat().st_size == row["bytes"], "exact native observation bytes")
            data = read(path)
            if data["status"] == "MATCHED":
                require(row["name"] not in artifacts, "matched model was unnecessarily repeated")
                artifacts[row["name"]] = (data, identity(path))
        measurements.append({"scope": directory, "body_wall_seconds": index["body_wall_seconds"],
                             "body_cpu_seconds": index["body_cpu_seconds"], "peak_rss_kib": index["peak_rss_kib"],
                             "cost_scope": index["cost_scope"]})
    require(len(artifacts) == 21, "all 21 actual selected model artifacts")
    sources = read(HERE / "evidence/inventory/SOURCE_BYTES.json")
    missing = {r["path"]: r["expected_sha256"] for r in sources if r["status"] != "MATCHED"}
    aliases = read(HERE / "evidence/recovered-source/ALIASES.json")["aliases"]
    require({r["original_path"]: r["sha256"] for r in aliases} == missing, "exact closure of original missing source paths")
    for row in aliases:
        local = HERE.parents[1] / row["local_file"]
        require(hashlib.sha256(local.read_bytes()).hexdigest() == row["sha256"], "recovered exact source bytes")
    roster = []
    for selected in selection["roster"]:
        actual, receipt = artifacts[selected["name"]]
        require(actual["checkpoint"]["sha256"] == selected["checkpoint"]["sha256"]
                and actual["D_logits"]["sha256"] == selected["D_logits"]["sha256"], "no selected model substitution")
        binding = {"name": selected["name"], "arm": selected["arm"], "seed": selected["seed"],
            "learning_rate": selected["learning_rate"], "selected_epoch": selected["strict_history"]["best_epoch"],
            "checkpoint": actual["checkpoint"], "D_logits": actual["D_logits"], "report": actual["report"],
            "model_tensor_manifest_sha256": actual["model_tensor_manifest_sha256"],
            "configuration_canonical_sha256": actual["configuration_canonical_sha256"],
            "source_map_canonical_sha256": content_hash(selected["source_file_sha256"]),
            "D_manifest_sha256": selection["D_manifest_sha256"],
            "D_episode_order_sha256": actual["D_episode_order_sha256"],
            "D_label_array_sha256": actual["D_label_array_sha256"], "D_logits_array_sha256": actual["D_logits_array_sha256"],
            "D_macro_f1_recorded": selected["D_macro_f1"], "D_macro_f1_recomputed": actual["D_macro_f1_recomputed"],
            "recorded_training_adequacy": selected["adequate"], "independent_complete_training_replay": False,
            "producer_runtime_recorded_fields": actual["producer_runtime_fields"], "inventory_receipt": receipt}
        roster.append({**binding, "model_binding_sha256": content_hash(binding)})
    require(len({r["D_episode_order_sha256"] for r in roster}) == 1
            and len({r["D_label_array_sha256"] for r in roster}) == 1, "same exact saved D order and labels")
    ledger = {"schema": "hcsn-21-model-D-only-selection-ledger-v1", "source_parent_commit": selection["source_parent_commit"],
        "selection": identity(selection_path), "families": selection["families"], "roster": roster,
        "source_aliases": identity(HERE / "evidence/recovered-source/ALIASES.json"),
        "source_python_bytes_bound": 88, "original_path_matches": 80, "exact_recovered_aliases": 8,
        "current_readable_selected_artifacts": 21, "all_selected_recorded_adequacy": all(r["adequate"] for r in selection["roster"]),
        "native_inventory_measurements": measurements,
        "source_custody": "Three absent Python files from PR6214 original archive; five existing local installed copies match the original historical SHA exactly. No original path or environment modified.",
        "runtime_limit": "Original cu128 compiled runtime was not restored or inferred from matching Python source. Actual inventory used 2.8.0+cpu without inference. Future evaluation runtime still needs binding and admission.",
        "C1_limit": "ssm_s4d seed211 selected C1 checkpoint retains the prior absent direct resume-start witness limitation.",
        "cost_limit": "All original42/C1 observation costs and source receipts are retained; prior UNKNOWN intervals and full lifetime cost remain incomplete. No inner/outer timer double count or historical refunds.",
        "original_controller_terminal": "UNKNOWN", "independent_original_full_training_replays": "0/6",
        "scientific_admission": "HOLD", "confirmation_E_payload_or_labels_accessed": False,
        "automatic_trigger": False, "training_forward_backward_optimizer_calls": 0,
        "status": "D_SELECTION_AND_ACTUAL_BYTE_BINDINGS_COMPLETE_E_BLOCKED"}
    path = HERE / "evidence/LEDGER.json"
    publish_or_verify(path, ledger, args.verify_existing)
    contract = {"schema": "hcsn-E-scorer-input-contract-unexecuted-v1", "selection_ledger": identity(path),
        "model_bindings": [{"name": r["name"], "model_binding_sha256": r["model_binding_sha256"]} for r in roster],
        "feature_role_allowlist": ["features", "delta_ticks", "lengths", "valid_mask", "episode_order", "row_order"],
        "feature_manifest": None, "D_temperature_receipts": None, "prediction_receipts": None,
        "isolated_labels_artifact": None, "label_access_requires_all_21_frozen_predictions": True,
        "metadata_validator": identity(HERE / "scorer_contract.py"), "execution_authorized": False,
        "automatic_trigger": False, "E_data_opened": False, "status": "BLOCKED_NO_E_ARTIFACTS_OR_LABEL_ACCESS",
        "remaining_exact_artifacts": ["21 D temperature optimization receipts under the original bounds and solver", "separate hashed E-only feature and label artifacts plus row order", "all 21 complete immutable prediction receipts before label access", "separate final source/runtime/checkpoint/selection/budget admission satisfying the original E plan"],
        "scope": "Hash bindings and metadata-only rejection contract; no E feature preparation, inference, calibration or scoring performed."}
    publish_or_verify(HERE / "evidence/SCORER_INPUT.json", contract, args.verify_existing)
    print(json.dumps({"status": ledger["status"], "models": len(roster), "ledger_sha256": identity(path)["sha256"],
                      "postprocessing_body_wall_seconds": sum(r["body_wall_seconds"] for r in measurements),
                      "postprocessing_body_cpu_seconds": sum(r["body_cpu_seconds"] for r in measurements)}, sort_keys=True))


if __name__ == "__main__":
    main()
