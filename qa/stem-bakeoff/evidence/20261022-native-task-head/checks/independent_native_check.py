#!/usr/bin/env python3
"""Read-only audit of retained native outputs against the original study ledger.

This does not run an Encoder/Head, train, calibrate, select a model, or infer
production authority. A caller-supplied report pin binds this observation; it is
not a signature or independent compiler attestation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

SCIENTIFIC_REPORT_PIN = "26c74e604c9404f93677d64687603f50afbf0414e7773c07a4237f5f9cbe0211"
ABSOLUTE_TOLERANCE = 2e-5
CASES = ("paired", "missing_text", "missing_image", "shuffled_image", "mixed_presence")
MODES = ("gated", "linear")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_file(path, expected, *, limit=2 * 1024 * 1024):
    require(not path.is_symlink() and path.is_file(), "regular retained file required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit and sha(raw) == expected, "retained file digest/budget differs: " + str(path))
    return raw


def audit(directory, report_pin, repository, binary=None):
    root = Path(directory).resolve(strict=True)
    source = Path(repository).resolve(strict=True) / "qa/stem-bakeoff"
    native, restored = root / "native-results", root / "restored"
    report_raw = checked_file(native / "report.json", report_pin)
    report = json.loads(report_raw)
    require(report["schema"] == "hepta.native-task-head-replay.v1" and report["status"] == "PASS",
            "native report schema/status differs")
    require(report["source_identity"]["numeric_tolerance_absolute"] == ABSOLUTE_TOLERANCE,
            "predeclared numeric tolerance differs")
    require(report["original_report_sha256"] == SCIENTIFIC_REPORT_PIN, "original science pin differs")
    require(report["authority"] == "DENY_ALL" and report["mode"] == "SHADOW_ONLY"
            and report["production_activation_allowed"] is False
            and report["target_device_qualified"] is False, "research authority differs")
    expected_names = {f"{mode}-{case}.jsonl" for mode in MODES for case in CASES}
    expected_names |= {f"{mode}-head/{name}" for mode in MODES for name in ("manifest.json", "weights.f32le")}
    if report["head_cost_measured"]:
        expected_names |= {f"{mode}-cost.json" for mode in MODES}
    require(set(report["retained_file_sha256"]) == expected_names, "retained file inventory differs")
    retained = {}
    for name in sorted(expected_names):
        expected = report["retained_file_sha256"][name]
        raw = checked_file(native / name, expected)
        retained[name] = {"expected_sha256": expected, "observed_sha256": sha(raw), "bytes": len(raw)}
    original_raw = checked_file(restored / "results/report.json", SCIENTIFIC_REPORT_PIN)
    original = json.loads(original_raw)
    science_sources = {}
    for name, expected in original["plan"]["code_file_sha256"].items():
        require(Path(name).name == name, "single scientific source filename required")
        raw = checked_file(source / name, expected)
        science_sources[name] = sha(raw)
    sys.path.insert(0, str(source))
    from prediction_ledger import LedgerIdentityV1, load_prediction_ledger
    bank_raw = checked_file(restored / "bank/manifest.json", original["bank_manifest_sha256"])
    bank = json.loads(bank_raw)
    data_raw = checked_file(restored / "cohorts/manifest.json", original["data_manifest_sha256"])
    data = json.loads(data_raw)
    row_raw = checked_file(restored / "cohorts/test.jsonl", data["splits"]["test"]["jsonl_sha256"])
    rows = [json.loads(line) for line in row_raw.splitlines()]
    require(len(rows) == 256, "fixed test inventory differs")
    image_index = {image_id: i for i, image_id in enumerate(bank["image_ids"])}
    blocks, partner = {}, {}
    for row in rows:
        blocks.setdefault(row["pair_block_id"], set()).add(row["image_id"])
    for ids in blocks.values():
        require(len(ids) == 2, "pair block endpoints differ")
        a, b = sorted(ids)
        partner[a], partner[b] = b, a
    results, original_ledgers, manifests = {}, {}, {}
    max_logit = max_prob = 0.0
    total = 0
    for mode in MODES:
        manifest = json.loads((native / f"{mode}-head/manifest.json").read_bytes())
        require(manifest["confidence_threshold"] == .7 and manifest["temperature"] == .25
                and manifest["required_present_mask"] == 3, "fixed confidence or presence contract differs")
        require(manifest["state_contract"] == "zero_state_only", "state contract differs")
        source_head = original["head_artifacts"]["text_image-" + mode]
        require(manifest["source_head_manifest_sha256"] == source_head["manifest_sha256"], "source Head differs")
        checked_file(restored / "results" / source_head["directory"] / "manifest.json", source_head["manifest_sha256"])
        manifests[mode] = {k: manifest[k] for k in ("confidence_threshold", "temperature", "required_present_mask",
                                                   "weights_sha256", "weights_bytes", "source_head_manifest_sha256")}
        expected = {}
        for case in ("paired", "shuffled_image"):
            key = "text_image-" + mode + ("" if case == "paired" else "-shuffled_image")
            ref = original["ledgers"][key]
            location = restored / "results" / ref["directory"]
            raw = checked_file(location / "manifest.json", ref["manifest_sha256"])
            meta = json.loads(raw)["metadata"]
            arrays_raw = checked_file(location / "predictions.npz", ref["arrays_sha256"])
            ledger = load_prediction_ledger(location, expected_manifest_sha256=ref["manifest_sha256"],
                expected_identity=LedgerIdentityV1(**meta["identity"]))
            expected[case] = ledger.rows()
            require(meta["temperature"] == manifest["temperature"] and meta["confidence_threshold"] == .7,
                    "calibration changed from the original ledger")
            original_ledgers[key] = {"manifest_sha256": sha(raw), "arrays_sha256": sha(arrays_raw),
                "ledger_sha256": ledger.ledger_sha256, "rows": len(expected[case])}
        for case in CASES:
            actual = [json.loads(line) for line in (native / f"{mode}-{case}.jsonl").read_bytes().splitlines()]
            require(len(actual) == len(rows), "native row count differs")
            scored = accepted = correct = 0
            for i, (value, row) in enumerate(zip(actual, rows, strict=True)):
                variant = ("paired", "missing_text", "missing_image")[i % 3] if case == "mixed_presence" else case
                image_id = partner[row["image_id"]] if variant == "shuffled_image" else row["image_id"]
                source_digest = sha(canonical({"row": row, "arm": "text_image", "intervention": variant,
                    "text_feature_source": bank["provenance"]["text"][image_index[row["source_caption_image_id"]]],
                    "image_feature_source": bank["provenance"]["image"][image_index[image_id]],
                    "bank_feature_sha256": bank["features_sha256"]}))
                require(type(value["row_index"]) is int and value["row_index"] == i
                        and value["source_record_digest"] == source_digest, "independent source reconstruction differs")
                require(value["artifact_sha256"] == report["exported_heads"][mode]["manifest_sha256"], "artifact differs")
                require(value["task_admission_allowed"] is False and value["action_execution_allowed"] is False,
                        "native row acquired task/action authority")
                prediction = value["prediction"]
                if variant.startswith("missing_"):
                    require(prediction is None and value["status"] == "REJECTED_MISSING_REQUIRED_MODALITY",
                            "missing modality produced a prediction")
                    continue
                require(value["status"] == "SCORED_RESEARCH_ONLY" and prediction["mode"] == "SHADOW_ONLY"
                        and prediction["authority"] == "DENY_ALL", "scored posture differs")
                require(all(math.isfinite(v) for v in prediction["task_logits"] + prediction["task_probabilities"]),
                        "nonfinite native output")
                require(prediction["accepted"] == (max(prediction["task_probabilities"]) >= .7), "confidence decision differs")
                reference = expected[variant][i]
                require(prediction["accepted"] is reference["accepted"]
                        and prediction["predicted_class"] == reference["prediction"], "original class/acceptance differs")
                logit = max(abs(a - b) for a, b in zip(prediction["task_logits"], reference["logits"], strict=True))
                prob = max(abs(a - b) for a, b in zip(prediction["task_probabilities"], reference["probabilities"], strict=True))
                require(logit <= ABSOLUTE_TOLERANCE and prob <= ABSOLUTE_TOLERANCE, "fixed numerical tolerance exceeded")
                max_logit, max_prob = max(max_logit, logit), max(max_prob, prob)
                scored += 1
                accepted += prediction["accepted"]
                correct += prediction["predicted_class"] == row["label"]
            results[f"{mode}-{case}"] = {"rows": len(actual), "scored": scored,
                "null_missing": len(actual) - scored, "accepted": accepted, "correct_scored": correct}
            total += len(actual)
    probes = [probe for group in report["invalid_input_rejections"].values() for probe in group.values()]
    require(len(probes) == 14 and all(p["exit_code"] != 0 and p["stdout_bytes"] == 0 for p in probes),
            "reported invalid-input rejection inventory differs")
    binary_observed = None
    if binary is not None:
        binary_path = Path(binary).resolve(strict=True)
        raw = checked_file(binary_path, report["binary_sha256"], limit=512 * 1024 * 1024)
        binary_observed = {"path": str(binary_path), "sha256": sha(raw), "bytes": len(raw)}
    require(sha((native / "report.json").read_bytes()) == report_pin, "report changed during audit")
    return {"schema": "hepta.native-task-independent-observation.v1", "status": "PASS",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(), "read_only": True,
        "new_model_execution": False, "new_training_or_calibration": False, "new_quality_trial": False,
        "original_scientific_report_sha256": SCIENTIFIC_REPORT_PIN,
        "native_report_sha256": report_pin, "native_report_directory": str(native),
        "native_binary_sha256_reported": report["binary_sha256"], "native_binary_independently_hashed": binary_observed,
        "observed_source_identity_from_report": report["source_identity"],
        "fixed_scientific_source_sha256_verified": science_sources,
        "retained_files_actual_digest": retained, "retained_file_count": len(retained),
        "original_npz_ledgers_verified": original_ledgers, "native_head_contracts": manifests,
        "source_record_digests_independently_rebuilt": total, "response_rows_verified": total,
        "fixed_absolute_tolerance": ABSOLUTE_TOLERANCE,
        "max_logit_error_vs_original_ledgers": max_logit,
        "max_probability_error_vs_original_ledgers": max_prob,
        "present_classes_and_acceptance_match_original_ledgers": True,
        "missing_rows_have_null_prediction": True, "all_task_action_admission_false": True,
        "invalid_cli_rejections_reported": len(probes), "invalid_cli_rejections_reexecuted_by_checker": False,
        "request_stream_bytes_independently_reconstructed": False,
        "compiler_attestation_independently_verified": False,
        "cases": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("directory", "expected-report-sha256", "repository", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--binary")
    args = parser.parse_args()
    before = sha(Path(__file__).read_bytes())
    receipt = audit(args.directory, args.expected_report_sha256, args.repository, args.binary)
    require(before == sha(Path(__file__).read_bytes()), "checker source changed during audit")
    receipt.update({"checker_source_sha256": before, "checker_path": str(Path(__file__).resolve()),
                    "command_argv": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
                    "python_version": sys.version.split()[0]})
    raw = canonical(receipt) + b"\n"
    with Path(args.output).open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": receipt["status"], "receipt_path": args.output,
        "receipt_sha256": sha(raw), "checker_source_sha256": before,
        "native_report_sha256": receipt["native_report_sha256"],
        "retained_files": receipt["retained_file_count"], "rows": receipt["response_rows_verified"]}))


if __name__ == "__main__":
    main()
