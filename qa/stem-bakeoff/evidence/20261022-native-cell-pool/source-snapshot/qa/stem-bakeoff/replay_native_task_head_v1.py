"""Replay the fixed real paired-image study through the compiled Rust task Head.

No weights, temperatures, thresholds or research cohorts change. Numerical
tolerances are fixed before execution; classification and confidence decisions
must match exactly. This checks native task execution, not daemon admission,
Encoder execution, production episodes, target-device latency or energy.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

import torch

from cell_head_training import _state_digest, load_head_artifact
from export_native_task_head_v1 import export_native_head
from feature_bundle import FeatureBundleV1
from multimodal_evidence import restore_evidence
from multimodal_features import load_bank, pair_features
from replay_presence_guard_v1 import ARCHIVE_PIN, REPORT_PIN
from research_presence_guard import predict_text_image_required

ABSOLUTE_TOLERANCE = 2e-5
CASES = ("paired", "missing_text", "missing_image", "shuffled_image", "mixed_presence")
MAX_RESPONSE_BYTES = 1024 * 1024


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode() + b"\n"


def _write(path, value):
    raw = _json(value)
    if len(raw) >= 512000:
        raise ValueError("retained report exceeds repository blob budget")
    with path.open("xb") as stream:
        stream.write(raw)
    return _sha(raw)


def _source_identity():
    repository = Path(__file__).resolve().parents[2]
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(repository), *arguments],
                                       text=True).strip()
    names = ("src/task_head_native.rs", "src/task_head_native_tests.rs",
             "src/lib.rs", "examples/native_task_head.rs")
    return {"git_head_sha": git("rev-parse", "HEAD"),
        "git_tree_sha": git("rev-parse", "HEAD^{tree}"),
        "working_tree_clean": not bool(git("status", "--porcelain")),
        "native_source_sha256": {name: _sha((repository / "codex-rs/hepta-neuron" / name).read_bytes())
                                 for name in names},
        "exporter_source_sha256": _sha(Path(__file__).with_name("export_native_task_head_v1.py").read_bytes()),
        "replay_source_sha256": _sha(Path(__file__).read_bytes()),
        "numeric_tolerance_absolute": ABSOLUTE_TOLERANCE,
        "binary_source_attestation_independently_verified": False}


def _cases(rows, bank, features):
    cases = {name: pair_features(rows, bank, features, arm="text_image", intervention=name)
             for name in CASES[:-1]}
    variants = [cases[name] for name in CASES[:3]]
    snapshots = [bundle.snapshot() for bundle in variants]
    mixed = {key: torch.stack([snapshots[i % 3][key][i] for i in range(len(rows))])
             for key in snapshots[0]}
    cases["mixed_presence"] = FeatureBundleV1.from_tensors(**mixed,
        source_record_digests=tuple(variants[i % 3].source_record_digests[i] for i in range(len(rows))),
        identity=variants[0].identity)
    return cases


def _request_lines(bundle):
    bundle.require_identity(bundle.identity)
    snapshot = bundle.snapshot()
    values = snapshot["global_features"].float().tolist()
    missing = snapshot["missing_mask"].tolist()
    for index, vector in enumerate(values):
        raw = _json({"identity": asdict(bundle.identity), "features": vector,
            "present_mask": sum((not absent) << column for column, absent in enumerate(missing[index])),
            "source_record_digest": bundle.source_record_digests[index]})
        if len(raw) > 256 * 1024:
            raise ValueError("native input row exceeds byte bound")
        yield raw
    bundle.verify_integrity()


def _execute(binary, artifact, manifest_sha256, request_path, response_path):
    command = [str(binary), str(artifact / "manifest.json"),
               str(artifact / "weights.f32le"), manifest_sha256]
    with request_path.open("rb") as source, response_path.open("xb") as output:
        result = subprocess.run(command, stdin=source, stdout=output,
                                stderr=subprocess.PIPE, timeout=60, check=False)
    if result.returncode:
        raise ValueError("native task execution failed: " + result.stderr[:4096].decode(errors="replace"))
    if response_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ValueError("native response budget exceeded")
    raw = response_path.read_bytes()
    return [json.loads(line) for line in raw.splitlines()], _sha(raw)


def _compare(actual, expected, request_hashes, manifest_digest, labels):
    if len(actual) != len(expected["rows"]) or len(actual) != len(request_hashes):
        raise ValueError("native/Python row inventory differs")
    max_logits = max_probabilities = 0.0
    accepted = correct = scored = 0
    for index, (row, reference) in enumerate(zip(actual, expected["rows"], strict=True)):
        if (set(row) != {"row_index", "request_sha256", "source_record_digest", "artifact_sha256",
                         "status", "prediction", "task_admission_allowed", "action_execution_allowed"}
                or row["row_index"] != index or row["request_sha256"] != request_hashes[index]
                or row["source_record_digest"] != reference["source_record_digest"]
                or row["artifact_sha256"] != manifest_digest
                or row["task_admission_allowed"] is not False
                or row["action_execution_allowed"] is not False):
            raise ValueError("native row identity or authority differs")
        prediction = row["prediction"]
        if reference["prediction"] is None:
            if prediction is not None or row["status"] != "REJECTED_MISSING_REQUIRED_MODALITY":
                raise ValueError("native missing-modality request was scored")
            continue
        if (row["status"] != "SCORED_RESEARCH_ONLY" or not isinstance(prediction, dict)
                or set(prediction) != {"task_logits", "task_probabilities", "predicted_class",
                                      "accepted", "gate", "mode", "authority"}
                or prediction["mode"] != "SHADOW_ONLY" or prediction["authority"] != "DENY_ALL"
                or prediction["predicted_class"] != reference["prediction"]
                or prediction["accepted"] is not reference["accepted"]
                or type(prediction["gate"]) not in (float, int)
                or not 0 <= prediction["gate"] <= 1):
            raise ValueError("native task class, confidence decision or posture differs")
        for name in ("task_logits", "task_probabilities"):
            native = torch.tensor(prediction[name], dtype=torch.float64)
            python = torch.tensor(reference[name], dtype=torch.float64)
            if (native.shape != python.shape or not bool(torch.isfinite(native).all())
                    or float((native - python).abs().max()) > ABSOLUTE_TOLERANCE):
                raise ValueError("native numeric parity exceeds the fixed tolerance: " + name)
        max_logits = max(max_logits, max(abs(a - b) for a, b in
                                        zip(prediction["task_logits"], reference["task_logits"], strict=True)))
        max_probabilities = max(max_probabilities, max(abs(a - b) for a, b in
            zip(prediction["task_probabilities"], reference["task_probabilities"], strict=True)))
        scored += 1
        accepted += prediction["accepted"]
        correct += prediction["predicted_class"] == labels[index]
    return {"rows": len(actual), "scored_rows": scored, "missing_rejected_rows": len(actual) - scored,
        "confidence_accepted_rows": accepted, "correct_scored_rows": correct,
        "max_absolute_logit_error": max_logits if scored else None,
        "max_absolute_probability_error": max_probabilities if scored else None,
        "class_and_acceptance_exact": True if scored else None,
        "all_missing_rows_have_null_prediction": True}


def _reject_probes(binary, artifact, manifest_sha256, first_line):
    base = json.loads(first_line)
    cases = {}
    wrong_identity = json.loads(first_line)
    wrong_identity["identity"]["preprocess_sha256"] = "0" * 64
    unknown_mask = {**base, "present_mask": 32}
    nonzero_state = {**base, "state": [1.0] * 8}
    short_features = {**base, "features": base["features"][:-1]}
    for name, request, digest in (
            ("wrong_manifest_pin", first_line, "0" * 64),
            ("wrong_feature_identity", _json(wrong_identity), manifest_sha256),
            ("unknown_presence_bits", _json(unknown_mask), manifest_sha256),
            ("unsupported_state", _json(nonzero_state), manifest_sha256),
            ("wrong_feature_width", _json(short_features), manifest_sha256),
            ("unterminated_request", first_line[:-1], manifest_sha256),
            ("oversized_request", b" " * (256 * 1024) + b"\n", manifest_sha256)):
        result = subprocess.run([str(binary), str(artifact / "manifest.json"),
            str(artifact / "weights.f32le"), digest], input=request, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=30, check=False)
        if result.returncode == 0 or result.stdout:
            raise ValueError("native invalid input did not fail closed: " + name)
        cases[name] = {"exit_code": result.returncode, "stdout_bytes": len(result.stdout),
                       "stderr_sha256": _sha(result.stderr)}
    return cases


def replay_native(archive_directory, output, binary, *, measure_cost=False):
    binary = Path(binary).resolve(strict=True)
    binary_digest = _sha(binary.read_bytes())
    source_identity = _source_identity()
    target = Path(output).absolute()
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        raise ValueError("new output directory with an existing parent required")
    target.mkdir(mode=0o700)
    restored = target / "restored"
    archive = restore_evidence(archive_directory, expected_manifest_sha256=ARCHIVE_PIN, output=restored)
    raw_report = (restored / "results/report.json").read_bytes()
    if _sha(raw_report) != REPORT_PIN:
        raise ValueError("only the fixed original experiment is supported")
    original = json.loads(raw_report)
    for name, expected in original["plan"]["code_file_sha256"].items():
        if _sha(Path(__file__).with_name(name).read_bytes()) != expected:
            raise ValueError("original scientific source changed: " + name)
    torch.set_num_threads(original["plan"]["threads"])
    bank, features = load_bank(restored / "bank",
        expected_manifest_sha256=original["bank_manifest_sha256"],
        expected_data_sha256=original["data_manifest_sha256"])
    rows = [json.loads(line) for line in (restored / "cohorts/test.jsonl").read_text().splitlines()]
    labels = [row["label"] for row in rows]
    cases = _cases(rows, bank, features)
    retained = target / "native-results"
    retained.mkdir(mode=0o700)
    files, exported, results, rejections, costs = {}, {}, {}, {}, {}
    started = time.perf_counter()
    for mode in ("gated", "linear"):
        record = original["head_artifacts"]["text_image-" + mode]
        source = restored / "results" / record["directory"]
        head = load_head_artifact(source, expected_manifest_sha256=record["manifest_sha256"],
                                  expected_identity=cases["paired"].identity)
        head_digest = _state_digest(head._head)
        artifact = retained / (mode + "-head")
        exported[mode] = export_native_head(source, expected_manifest_sha256=record["manifest_sha256"],
            expected_identity=head.identity, output=artifact)
        manifest_digest = exported[mode]["manifest_sha256"]
        files[mode + "-head/manifest.json"] = manifest_digest
        files[mode + "-head/weights.f32le"] = exported[mode]["weights_sha256"]
        for name, bundle in cases.items():
            request_path = target / "requests.jsonl"
            request_hashes, stream_hash = [], hashlib.sha256()
            with request_path.open("xb") as stream:
                for line in _request_lines(bundle):
                    stream.write(line)
                    stream_hash.update(line)
                    request_hashes.append(_sha(line))
                    if len(request_hashes) == 1:
                        first_line = line
            expected = predict_text_image_required(head, bundle)
            response_name = mode + "-" + name + ".jsonl"
            actual, response_sha = _execute(binary, artifact, manifest_digest,
                                           request_path, retained / response_name)
            result = _compare(actual, expected, request_hashes, manifest_digest, labels)
            result.update({"request_stream_sha256": stream_hash.hexdigest(),
                "request_stream_bytes": request_path.stat().st_size,
                "parent_feature_bundle_sha256": bundle.bundle_digest,
                "response_file": response_name, "response_sha256": response_sha,
                "reference_head_tensor_sha256": head_digest})
            results[mode + "-" + name] = result
            files[response_name] = response_sha
            if name == "paired":
                rejections[mode] = _reject_probes(binary, artifact, manifest_digest, first_line)
                if measure_cost:
                    from native_task_head_cost import run_cost
                    costs[mode] = run_cost(binary, artifact / "manifest.json", artifact / "weights.f32le",
                        request_path, manifest_digest, stream_hash.hexdigest(), source_identity=source_identity)
                    cost_name = mode + "-cost.json"
                    files[cost_name] = _write(retained / cost_name, costs[mode])
            request_path.unlink()
            bundle.verify_integrity()
        if _state_digest(head._head) != head_digest:
            raise ValueError("original Head changed during native replay")
    if _sha(binary.read_bytes()) != binary_digest or source_identity != _source_identity():
        raise ValueError("native binary or source changed during parity execution")
    receipt = {"schema": "hepta.native-task-head-replay.v1", "status": "PASS",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_source_sha": archive["source_sha"], "archive_manifest_sha256": ARCHIVE_PIN,
        "original_report_sha256": REPORT_PIN, "binary_sha256": binary_digest,
        "source_identity": source_identity, "exported_heads": exported,
        "cases": results, "invalid_input_rejections": rejections,
        "retained_file_sha256": files, "head_cost_measured": bool(costs),
        "execution_wall_ms": (time.perf_counter() - started) * 1000,
        "native_task_head_executed": True, "native_encoder_executed": False,
        "agentd_caller_integrated": False, "new_training_or_calibration": False,
        "new_independent_quality_trial": False, "full_policy_learning_qualified": False,
        "target_device_qualified": False, "energy_joules": None,
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
        "production_activation_allowed": False, "all_blockers_closed": False}
    _write(retained / "report.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-directory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--measure-cost", action="store_true")
    args = parser.parse_args()
    print(json.dumps(replay_native(args.archive_directory, args.output, args.binary,
                                  measure_cost=args.measure_cost), indent=2))


if __name__ == "__main__":
    main()
