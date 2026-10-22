"""Check presence rejection using the fixed real multimodal experiment.

This is a post-experiment input-contract regression, not another quality trial.
It restores the externally pinned evidence, never retrains or changes the
original report, and records each new wrapper result separately.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import torch

from cell_head_training import _state_digest, load_head_artifact
from feature_bundle import FeatureBundleV1
from multimodal_evidence import restore_evidence
from multimodal_features import load_bank, pair_features
from research_presence_guard import predict_text_image_required

ARCHIVE_PIN = "2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e"
REPORT_PIN = "26c74e604c9404f93677d64687603f50afbf0414e7773c07a4237f5f9cbe0211"


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _write(path, value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode() + b"\n"
    if len(payload) >= 512000:
        raise ValueError("presence result exceeds the repository blob budget")
    path.write_bytes(payload)
    return _sha(payload)


def check_retained_experiment(archive_directory, output):
    target = Path(output).absolute()
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        raise ValueError("new output directory required")
    target.mkdir(mode=0o700)
    restored = target / "restored"
    archive = restore_evidence(archive_directory,
        expected_manifest_sha256=ARCHIVE_PIN, output=restored)
    raw_report = (restored / "results/report.json").read_bytes()
    if _sha(raw_report) != REPORT_PIN:
        raise ValueError("this check only applies to the fixed original experiment")
    report = json.loads(raw_report)
    for name, digest in report["plan"]["code_file_sha256"].items():
        if _sha(Path(__file__).with_name(name).read_bytes()) != digest:
            raise ValueError("original experiment source changed: " + name)
    torch.set_num_threads(report["plan"]["threads"])
    bank, features = load_bank(restored / "bank",
        expected_manifest_sha256=report["bank_manifest_sha256"],
        expected_data_sha256=report["data_manifest_sha256"])
    source_rows = [json.loads(line) for line in
                   (restored / "cohorts/test.jsonl").read_text().splitlines()]
    cases = {name: pair_features(source_rows, bank, features,
                arm="text_image", intervention=name)
             for name in ("paired", "missing_text", "missing_image", "shuffled_image")}
    # Mix existing, integrity-bound rows; do not infer presence from tensor values.
    variants = [cases[name] for name in ("paired", "missing_text", "missing_image")]
    snapshots = [bundle.snapshot() for bundle in variants]
    mixed = {key: torch.stack([snapshots[i % 3][key][i]
                             for i in range(len(source_rows))])
             for key in snapshots[0]}
    cases["mixed_presence"] = FeatureBundleV1.from_tensors(**mixed,
        source_record_digests=tuple(variants[i % 3].source_record_digests[i]
                                   for i in range(len(source_rows))),
        identity=variants[0].identity)
    retained = target / "guard-results"
    retained.mkdir(mode=0o700)
    observations, files = {}, {}
    for mode in ("gated", "linear"):
        record = report["head_artifacts"]["text_image-" + mode]
        head = load_head_artifact(restored / "results" / record["directory"],
            expected_manifest_sha256=record["manifest_sha256"],
            expected_identity=cases["paired"].identity)
        head_before = _state_digest(head._head)
        for case_name, bundle in cases.items():
            snapshot = bundle.snapshot()
            valid = ~snapshot["missing_mask"][:, :2].any(dim=1)
            indices = valid.nonzero(as_tuple=False).flatten().tolist()
            expected = None
            if indices:
                subset = FeatureBundleV1.from_tensors(
                    **{key: value[indices] for key, value in snapshot.items()},
                    source_record_digests=tuple(bundle.source_record_digests[i] for i in indices),
                    identity=bundle.identity)
                expected = head.predict_task(subset)
            calls = []
            hook = head._head.register_forward_hook(
                lambda _module, inputs, _output: calls.append(len(inputs[0])))
            try:
                result = predict_text_image_required(head, bundle)
            finally:
                hook.remove()
            if (calls != ([len(indices)] if indices else [])
                    or result["scored_row_indices"] != indices
                    or result["head_prediction_calls"] != len(calls)
                    or len(result["rows"]) != len(source_rows)
                    or result["parent_feature_bundle_sha256"] != bundle.bundle_digest
                    or result["head_tensor_sha256"] != head_before):
                raise ValueError("presence partition, identity or observed forward differs")
            for i, row in enumerate(result["rows"]):
                if (row["row_index"] != i
                        or row["source_record_digest"] != bundle.source_record_digests[i]
                        or row["authority"] != "DENY_ALL"
                        or row["task_admission_allowed"] is not False
                        or row["action_execution_allowed"] is not False):
                    raise ValueError("row provenance or authority mismatch")
                if not bool(valid[i]):
                    if (row["accepted"] is not False or row["prediction"] is not None
                            or row["task_logits"] is not None
                            or row["task_probabilities"] is not None):
                        raise ValueError("missing evidence produced a task result")
            if indices:
                kept = [result["rows"][i] for i in indices]
                logits = torch.tensor([row["task_logits"] for row in kept])
                probabilities = torch.tensor([row["task_probabilities"] for row in kept])
                accepted = torch.tensor([row["accepted"] for row in kept])
                predictions = torch.tensor([row["prediction"] for row in kept])
                if (not torch.equal(logits, expected["task_logits"])
                        or not torch.equal(probabilities, expected["task_probabilities"])
                        or not torch.equal(accepted, expected["accepted"])
                        or not torch.equal(predictions, expected["task_probabilities"].argmax(dim=1))):
                    raise ValueError("present-row predictions changed")
            bundle.verify_integrity()
            if _state_digest(head._head) != head_before:
                raise ValueError("Head changed during presence check")
            name = mode + "-" + case_name + ".json"
            files[name] = _write(retained / name, result)
            observations[mode + "-" + case_name] = {
                "rows": len(source_rows), "scored_rows": len(indices),
                "rejected_missing_rows": len(source_rows) - len(indices),
                "confidence_accepted_rows": sum(row["accepted"] for row in result["rows"]),
                "observed_head_forward_batch_sizes": calls,
                "present_row_predictions_exactly_match_original_api": True if indices else None,
                "head_weights_unchanged": True, "original_feature_bundle_unchanged": True}
    receipt = {"schema": "hepta.real-presence-guard-replay.v1", "status": "PASS",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_source_sha": archive["source_sha"],
        "archive_manifest_sha256": ARCHIVE_PIN, "original_report_sha256": REPORT_PIN,
        "guard_source_sha256": _sha(Path(__file__).with_name("research_presence_guard.py").read_bytes()),
        "replay_script_sha256": _sha(Path(__file__).read_bytes()),
        "retained_case_files": files, "cases": observations,
        "new_training_or_calibration": False, "original_research_report_changed": False,
        "new_independent_quality_trial": False, "semantic_pairing_verified_by_presence": False,
        "presence_source_independently_attested": False, "native_runtime_integrated": False,
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
        "production_activation_allowed": False,
        "task_admission_allowed": False, "action_execution_allowed": False}
    _write(retained / "report.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-directory", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(check_retained_experiment(args.archive_directory, args.output), indent=2))


if __name__ == "__main__":
    main()
