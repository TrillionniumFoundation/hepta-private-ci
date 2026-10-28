#!/usr/bin/env python3
"""Read-only stdlib audit of recorded v3 calibration arithmetic and provenance.

No repository modules, NumPy, Torch, models, media decoders, owner, network, or
reserved policy/qualification media are invoked. This does not reproduce model
inference or authenticate how the recorded predictions were produced.
"""
import argparse
import ast
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import resource
import sys


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_identity(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def equivalent(actual, expected, path="value"):
    if isinstance(expected, float):
        require(isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12), path)
    elif isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), path + " keys")
        for key, value in expected.items():
            equivalent(actual[key], value, path + "." + key)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), path + " length")
        for index, value in enumerate(expected):
            equivalent(actual[index], value, f"{path}[{index}]")
    else:
        require(actual == expected, path)


def interval95(k, n):
    def solve(first, last, target, increasing):
        low, high = 0.0, 1.0
        for _ in range(80):
            p = (low + high) / 2
            value = math.fsum(math.comb(n, j) * p**j * (1-p)**(n-j) for j in range(first, last+1))
            if (value < target) == increasing:
                low = p
            else:
                high = p
        return (low + high) / 2
    return [solve(k, n, .025, True) if k else 0.0,
            solve(0, k, .025, False) if k < n else 1.0]


def metrics(predictions, rows, kind):
    require(len(predictions) == len(rows), kind + " prediction length")
    correct = [prediction == row[kind + "_id"] for prediction, row in zip(predictions, rows)]
    counts = Counter(row["source_id"] for row in rows)
    source_uniform = sum((Fraction(int(ok), len(counts) * counts[row["source_id"]])
                          for ok, row in zip(correct, rows)), Fraction())
    labels = sorted({row[kind + "_id"] for row in rows})
    recalls = {str(label): sum(ok for ok, row in zip(correct, rows) if row[kind + "_id"] == label)
               / sum(row[kind + "_id"] == label for row in rows) for label in labels}
    return {"correct_by_event": correct, "event_accuracy": sum(correct) / len(correct),
            "source_uniform_accuracy": float(source_uniform), "sources": len(counts),
            "events": len(rows), "class_recalls": recalls, "present_class_count": len(labels),
            "macro_recall_present_classes": math.fsum(recalls.values()) / len(labels)}


def audit(args):
    result_path = args.repository / "natural_results/NATURAL_V3_RESULT.json"
    result = read(result_path)
    calibration_path = args.observers / "OBSERVER_CALIBRATION.json"
    freeze_path = args.observers / "OBSERVER_FREEZE.json"
    protocol_path = args.observers / "PROTOCOL.json"
    source_path = args.assets / "SOURCE_PROTOCOL.json"
    calibration, freeze, protocol, source = map(read, [calibration_path, freeze_path, protocol_path, source_path])
    freeze_identity = file_identity(freeze_path)
    source_body = dict(source)
    source_pin = source_body.pop("protocol_sha256")
    require(canonical_sha(source_body) == source_pin, "source canonical hash")
    require(source_pin == "ad58bf5529af473f722c8e48a44f34ae07e364356b664a3a79458fecf1405b9d", "approved allocation")
    for document in [result, calibration, freeze, protocol]:
        require(document["source_protocol_sha256"] == source_pin, "source identity chain")
    require(result["frozen_observer_file_sha256"] == freeze_identity["sha256"], "result freeze file identity")
    require(calibration["observer_freeze_sha256"] == canonical_sha(freeze), "calibration canonical freeze identity")
    require(freeze["protocol_sha256"] == canonical_sha(protocol), "observer protocol identity")
    observer_source = args.repository / "semantic_observer.py"
    require(freeze["implementation_sha256"] == protocol["implementation_sha256"] == file_identity(observer_source)["sha256"], "observer source identity")
    thresholds = {"action_accuracy": .6, "sound_accuracy": .6,
                  "both_modalities_must_exceed_own_training_majority_accuracy": True}
    syntax = ast.parse(observer_source.read_text())
    spec = next(item.value for item in syntax.body if isinstance(item, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "SPEC" for target in item.targets))
    source_thresholds = ast.literal_eval(next(value for key, value in zip(spec.keys, spec.values)
                                               if isinstance(key, ast.Constant) and key.value == "adequacy"))
    for actual in [protocol["adequacy"], calibration["thresholds_unchanged"], result["thresholds_unchanged"], source_thresholds]:
        equivalent(actual, thresholds, "unchanged adequacy")
    feature_path = args.assets / "FEATURE_PROTOCOL.json"
    feature = read(feature_path)
    require(feature["source_protocol_sha256"] == source_pin, "feature source binding")
    require(canonical_sha(feature) == freeze["feature_protocol_sha256"], "feature freeze identity")
    for name, pin in feature["source_hashes"].items():
        require(file_identity(args.repository / name)["sha256"] == pin, "feature source " + name)
    require(feature["weights"] == protocol["weights"], "pretrained weight identities")
    selected = {item["source_id"]: item for item in source["selected"]}
    require(len(selected) == len(source["selected"]) == 1024, "unique allocated source IDs")
    parent_path = args.assets / "PARENT_SOURCE_PROTOCOL.json"
    parent = read(parent_path)
    parent_body = dict(parent)
    parent_pin = parent_body.pop("protocol_sha256")
    require(canonical_sha(parent_body) == parent_pin == source["coverage_amendment"]["parent_source_protocol_sha256"], "parent allocation")
    require(len(parent["selected"]) == 768, "original allocation size")
    for row in parent["selected"]:
        equivalent(selected[row["source_id"]], row, "original allocation " + row["source_id"])
    expected = {sid: row for sid, row in selected.items() if row["role"] == "observer_calibration"}
    root = args.assets / "prepared/observer_calibration"
    directories = {p.name: p for p in root.iterdir() if p.is_dir()}
    require(set(directories) == set(expected) and len(directories) == 64, "complete calibration source cohort")
    rows, source_evidence, unique_hashes = [], [], set()
    retained_count = 0
    for sid, directory in sorted(directories.items()):
        receipt_path = directory / "RECEIPT.json"
        receipt, original = read(receipt_path), expected[sid]
        require(receipt["heldout_freeze_sha256"] == freeze_identity["sha256"], "heldout freeze " + sid)
        require(receipt["source_protocol_sha256"] == source_pin and receipt["feature_protocol_sha256"] == canonical_sha(feature), "receipt identities " + sid)
        require(receipt["source_hashes"] == feature["source_hashes"], "receipt extraction source " + sid)
        require(receipt["source_id"] == sid and receipt["role"] == "observer_calibration", "receipt role " + sid)
        require(receipt["original_source_bytes"] == original["source_bytes"] and receipt["original_member"] == original["member"]
                and receipt["original_url"] == source["archive"][original["official_split"]]["url"], "original source identity " + sid)
        original_sha = receipt["original_source_sha256"]
        require(len(original_sha) == 64 and original_sha not in unique_hashes, "unique original bytes " + sid)
        require(original_sha not in freeze["consumed_training_development_source_sha256"], "calibration overlaps fitting/selection " + sid)
        unique_hashes.add(original_sha)
        events = original["events"][:original["retained_event_count"]]
        require(len(events) == len(receipt["events"]) == 1, "one event per calibration source " + sid)
        row = receipt["events"][0]
        equivalent(row, {"event_id": sid + "-closure-0", "source_id": sid, "source_sha256": original_sha,
                         "role": "observer_calibration", **events[0]}, "frozen labels/window " + sid)
        for name, pin in receipt["retained_files"].items():
            require(name in {"EVENT.npz", "FEATURES.npz"}, "unexpected retained file")
            require(file_identity(directory / name)["sha256"] == pin, "retained bytes " + sid + "/" + name)
            retained_count += 1
        rows.append(row)
        source_evidence.append({"source_id": sid, "event_id": row["event_id"], "reference_action": row["action_id"],
                                "reference_sound": row["sound_id"], "original_source_sha256": original_sha,
                                "receipt": file_identity(receipt_path), "retained_files": receipt["retained_files"]})
    training = [item for item in source["selected"] if item["role"] == "observer_train"]
    require(len(training) == 512, "observer training source count")
    training_events = sum(item["retained_event_count"] for item in training)
    require(training_events == result["observer_training_events"] == 2517, "observer training event count")
    reports, checkpoint_evidence = {}, {}
    for kind in ("action", "sound"):
        chosen = freeze["selected"][kind]
        mass, present = defaultdict(Fraction), set()
        for item in training:
            events = item["events"][:item["retained_event_count"]]
            for event in events:
                label = event[kind + "_id"]
                mass[label] += Fraction(1, len(training) * len(events))
                present.add(label)
        majority = max(sorted(mass), key=mass.get)
        require(majority == chosen["training_majority_label"], kind + " training-majority reconstruction")
        require(sorted(present) == chosen["training_present_classes"], kind + " training class coverage")
        require(chosen["all_ontology_classes"] == sorted(map(int, source["ontology"][kind])), kind + " full ontology")
        report = calibration["observers"][kind]
        actual = metrics(report["predictions"], rows, kind)
        for key, value in actual.items():
            equivalent(report[key], value, kind + "." + key)
        baseline = metrics([majority] * len(rows), rows, kind)
        equivalent(report["majority_control"], baseline, kind + ".majority")
        unseen = sum(row[kind + "_id"] not in present for row in rows) / len(rows)
        equivalent(report["unseen_training_class_fraction"], unseen, kind + ".unseen")
        passed = actual["source_uniform_accuracy"] >= thresholds[kind + "_accuracy"] and actual["source_uniform_accuracy"] > baseline["source_uniform_accuracy"]
        require(report["passed_empirical_adequacy"] == passed, kind + " gate")
        interval = interval95(sum(actual["correct_by_event"]), len(rows))
        equivalent(report["source_binomial_interval_95"], interval, kind + ".interval")
        compact = {"accuracy": actual["source_uniform_accuracy"], "correct": sum(actual["correct_by_event"]),
                   "majority_accuracy": baseline["source_uniform_accuracy"], "majority_correct": sum(baseline["correct_by_event"]),
                   "sources": len(directories), "passed_original_gate": passed, "unseen_training_class_fraction": unseen,
                   "binomial95_interval": interval}
        equivalent(result["independent_calibration"][kind], compact, "final result " + kind)
        require(result["selected_models"][kind] == chosen["selected_candidate"], kind + " selected model")
        reports[kind] = {**compact, "training_majority_label": majority, "training_present_class_count": len(present)}
        checkpoint_evidence[kind] = file_identity(args.observers / chosen["checkpoint_file"])
        require(checkpoint_evidence[kind]["sha256"] == chosen["checkpoint_sha256"], kind + " checkpoint byte binding")
        for index, item in enumerate(source_evidence):
            item[kind + "_prediction"] = report["predictions"][index]
            item[kind + "_correct"] = actual["correct_by_event"][index]
    joint = sum(a["action_correct"] and a["sound_correct"] for a in source_evidence)
    require(result["original_media_joint_observer_correctness"] == {"correct": joint, "sources": 64, "is_generator_quality_measurement": False}, "joint observer result")
    require(not calibration["adequate"] and not result["independent_observer_adequate"] and not any(x["passed_original_gate"] for x in reports.values()), "inadequate gate propagated")
    require(not calibration["future_population_accuracy_certified"] and not calibration["qualification_access"], "no future qualification claim")
    require(not calibration["policy_or_model_changed_after_calibration"], "no recorded post-calibration adaptation")
    for key in ["new_actual_ndu_generator_updates", "new_policy_calibration_sources_accessed", "new_qualification_sources_accessed", "warmstart003_updates"]:
        require(result[key] == 0, "downstream counter " + key)
    require(result["new_generator_efficacy_measured"] is False, "no efficacy claim")
    require(result["mechanism_validation"]["scope"] == "fixed zero public-feature test provider; no semantic or native execution claim", "mechanism scope")
    reserved = {role: (args.assets / "prepared" / role).exists() for role in ("policy_calibration", "qualification")}
    require(not any(reserved.values()), "reserved prepared directories exist")
    directory_names = {str(root): sorted(p.name for p in root.iterdir() if p.is_dir()) for root in [args.assets.parent, args.repository / "natural_results"]}
    suspicious = [name for names in directory_names.values() for name in names if "warm003" in name.lower() or "warmstart003" in name.lower() or "natural_study_v3" in name.lower()]
    require(not suspicious, "unexpected downstream v3 directory")
    entry_path = args.repository / "natural_results/FAILED_ADEQUACY_ENTRY_CHECK.json"
    entry = read(entry_path)
    require(file_identity(entry_path)["sha256"] == result["evidence_sha256"][entry_path.name], "entry rejection receipt identity")
    require(entry["checks_passed"] and not entry["native_owner_or_generator_executed"] and all(item["rejected"] for item in entry["actual_production_entries_tested"]), "recorded production rejection")
    for name, pin in entry["source_sha256"].items():
        require(file_identity(args.repository / name)["sha256"] == pin, "entry guard implementation binding")
    for name, pin in result["evidence_sha256"].items():
        require(file_identity(args.repository / "natural_results" / name)["sha256"] == pin, "final evidence binding " + name)
    inputs = [result_path, calibration_path, freeze_path, protocol_path, source_path, parent_path, feature_path, observer_source, entry_path]
    require(not ({"torch", "numpy", "scipy"} & sys.modules.keys()), "non-stdlib model/scoring dependency loaded")
    process_memory = {line.split(":", 1)[0]: int(line.split()[1])
                      for line in Path("/proc/self/status").read_text().splitlines()
                      if line.startswith(("VmRSS:", "VmHWM:"))}
    return {"schema": "hepta.independent.natural-v3-recorded-result-audit.v1", "status": "PASS",
            "scope": "Independent arithmetic, source/receipt/hash and visible filesystem audit of already-recorded calibration results; no model inference reproduced.",
            "inputs": {str(p): file_identity(p) for p in inputs}, "auditor_source": file_identity(Path(__file__)),
            "observer_freeze_raw_file_sha256": freeze_identity["sha256"], "observer_freeze_canonical_sha256": canonical_sha(freeze),
            "source_protocol_canonical_sha256": source_pin, "source_id_order": "lexicographic directory/source_id order, matching load_role; retained events retain original order",
            "calibration_sources": 64, "calibration_events": len(rows), "all_64_heldout_freeze_bindings_match": True,
            "original_768_allocated_entries_equal_parent": True, "retained_files_stream_hash_verified": retained_count,
            "unique_calibration_original_source_sha256": len(unique_hashes), "no_overlap_with_frozen_training_development_original_hashes": True,
            "training_source_count": len(training), "training_event_count": training_events, "modalities": reports,
            "joint_original_media_observer_correct": joint, "independent_observer_adequate": False,
            "selected_checkpoint_byte_bindings": checkpoint_evidence, "unchanged_thresholds": thresholds,
            "reserved_prepared_directory_exists": reserved, "visible_directory_names": directory_names,
            "recorded_production_entry_rejections_consistent": True, "downstream_counters_zero": True,
            "generator_efficacy_or_native_capability_claimed": False,
            "limitations": ["Recorded predictions were compared with frozen labels; inference from selected checkpoint tensors was not reproduced or authenticated.",
                            "Checkpoint files and retained NPZ bytes were stream-hashed, never unpickled, decoded or fed into any model.",
                            "Original MP4 identity is checked against allocation and receipts; original deleted MP4 bytes and annotation semantics were not re-downloaded or independently decoded.",
                            "Unique original-video identities do not establish participant independence or future population accuracy.",
                            "Visible directory absence plus zero counters and bound rejection receipts is not proof no process ever ran elsewhere; no global execution-history claim is made.",
                            "The separate 960-source history audit is bound by its reported file hash but not independently re-executed here."],
            "torch_imported": False, "numpy_imported": False, "model_forward_calls": 0, "native_owner_calls": 0,
            "new_source_media_accesses": 0, "reserved_policy_or_qualification_files_read": 0,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "linux_process_memory_kib": process_memory,
            "source_rows": source_evidence}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path("/dev/shm/hepta-ndu-unified-20261028/repo/experiments/multimodal_output_portfolio/closure_20261028"))
    parser.add_argument("--assets", type=Path, default=Path("/dev/shm/hepta-ndu-closure-20261028/natural_assets_v3"))
    parser.add_argument("--observers", type=Path, default=Path("/dev/shm/hepta-ndu-closure-20261028/natural_observer_v3_001"))
    parser.add_argument("--output", type=Path, default=Path("/workspace/scratch/627fa3bea56c/natural-v3-independent-result-audit.json"))
    args = parser.parse_args()
    report = audit(args)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "modalities": report["modalities"], "joint_correct": report["joint_original_media_observer_correct"], "peak_rss_kib": report["peak_rss_kib"], "report": file_identity(args.output), "source": report["auditor_source"]}, indent=2))


if __name__ == "__main__":
    main()
