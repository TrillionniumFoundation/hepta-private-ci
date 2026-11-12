"""Run separate-process native PERC owner/readback qualification on supplied bytes.

Raw inputs are preserved, but their real-source provenance must be established by
the capture owner. The hand-authored diagnostic head has no training/quality claim.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def qualify(binary, wire, raster, expected, output, input_classification):
    output.mkdir(parents=True, exist_ok=False)
    spec = json.loads(expected.read_bytes())
    dimension, q = spec["feature_dimension"], 1 << 24
    weights = [[0] * dimension for _ in range(10)]
    weights[0][0], weights[1][0] = q // 4, -q // 4
    head = {
        "schema": "perc1.diagnostic-q24-linear-head.v1",
        "provenance": "hand_authored_diagnostic_no_training_claim",
        "weights_q24": weights,
        "bias_q24": [q // 4] + [0] * 9,
    }
    head_path = output / "diagnostic-head.json"
    head_path.write_text(json.dumps(head, separators=(",", ":")) + "\n")
    invocations = []

    def invoke(label, args, success=True):
        result = output / (label + ".json")
        command = [str(binary), *map(str, args), str(result)]
        started = time.perf_counter_ns()
        completed = subprocess.run(command, capture_output=True, timeout=30)
        elapsed = time.perf_counter_ns() - started
        (output / (label + ".stdout")).write_bytes(completed.stdout)
        (output / (label + ".stderr")).write_bytes(completed.stderr)
        invocations.append(
            {
                "label": label,
                "command": command,
                "returncode": completed.returncode,
                "wall_ns": elapsed,
                "stdout_sha256": sha(completed.stdout),
                "stderr_sha256": sha(completed.stderr),
            }
        )
        (output / "invocations.json").write_text(
            json.dumps(invocations, indent=2) + "\n"
        )
        if (completed.returncode == 0) != success:
            raise AssertionError(
                label + ": " + completed.stderr.decode(errors="replace")
            )
        return json.loads(result.read_bytes()) if success else completed.stderr.decode()

    first_root = output / "owner-complete"
    first = invoke("first", ["start", first_root, wire, raster, expected, head_path])
    if not (first["status"] == "COMMITTED" and first["owner_revision"] == 1):
        raise AssertionError(
            'qualification failed: first["status"] == "COMMITTED" and first["owner_revision"] == 1'
        )
    if not (first["diagnostic_head_inference_executions"] == 1):
        raise AssertionError(
            'qualification failed: first["diagnostic_head_inference_executions"] == 1'
        )
    if not (first["decision"]["consumed_input_bytes"] == len(wire.read_bytes())):
        raise AssertionError(
            'qualification failed: first["decision"]["consumed_input_bytes"] == len(wire.read_bytes())'
        )
    if not (first["decision"]["truncated_input_bytes"] == 0):
        raise AssertionError(
            'qualification failed: first["decision"]["truncated_input_bytes"] == 0'
        )
    original = json.loads(wire.read_bytes())
    values = [v for latent in original["latents"] for v in latent["values_q24"]]
    native_head = json.loads((first_root / "head-receipt.json").read_bytes())
    expected_head = []
    for row, bias in zip(weights, head["bias_q24"]):
        dot = sum(a * b for a, b in zip(row, values))
        rounded = (abs(dot) // q) * (1 if dot >= 0 else -1)
        expected_head.append(min(8 * q, max(-8 * q, rounded + bias)))
    if not (native_head["drive_q24"] + native_head["prediction_q24"] == expected_head):
        raise AssertionError(
            'qualification failed: native_head["drive_q24"] + native_head["prediction_q24"] == expected_head'
        )
    for label in ("cold-read-1", "cold-read-2"):
        cold = invoke(label, ["read", first_root])
        if not (cold["decision"] == first["decision"] and cold["owner_revision"] == 1):
            raise AssertionError(
                'qualification failed: cold["decision"] == first["decision"] and cold["owner_revision"] == 1'
            )
        if not (cold["status"] == "REPLAYED" and not cold["pending"]):
            raise AssertionError(
                'qualification failed: cold["status"] == "REPLAYED" and not cold["pending"]'
            )
        if not (
            (
                cold["encoder_calls"],
                cold["diagnostic_head_inference_executions"],
                cold["inference_readbacks"],
            )
            == (0, 0, 0)
        ):
            raise AssertionError(
                'qualification failed: (cold["encoder_calls"], cold["diagnostic_head_inference_executions"], cold["inference_readbacks"]) == (0, 0, 0)'
            )

    pending_root = output / "owner-pending"
    pending = invoke(
        "lost-ack", ["lose-ack", pending_root, wire, raster, expected, head_path]
    )
    if not (pending["status"] == "PENDING_ORIGINAL_READBACK" and pending["pending"]):
        raise AssertionError(
            'qualification failed: pending["status"] == "PENDING_ORIGINAL_READBACK" and pending["pending"]'
        )
    if not (
        pending["owner_revision"] == 0
        and pending["diagnostic_head_inference_executions"] == 1
    ):
        raise AssertionError(
            'qualification failed: pending["owner_revision"] == 0 and pending["diagnostic_head_inference_executions"] == 1'
        )
    missing_root = output / "owner-missing-original"
    shutil.copytree(pending_root, missing_root)
    (missing_root / "head-receipt.json").unlink()
    missing = invoke("missing-original", ["read", missing_root])
    if not (missing["status"] == "PENDING_ORIGINAL_READBACK" and missing["pending"]):
        raise AssertionError(
            'qualification failed: missing["status"] == "PENDING_ORIGINAL_READBACK" and missing["pending"]'
        )
    if not (
        missing["owner_revision"] == 0
        and missing["diagnostic_head_inference_executions"] == 0
    ):
        raise AssertionError(
            'qualification failed: missing["owner_revision"] == 0 and missing["diagnostic_head_inference_executions"] == 0'
        )
    corrupted_root = output / "owner-corrupt-original"
    shutil.copytree(pending_root, corrupted_root)
    corrupt = json.loads((corrupted_root / "head-receipt.json").read_bytes())
    corrupt["request_sha256"][0] ^= 1
    (corrupted_root / "head-receipt.json").write_text(json.dumps(corrupt))
    corrupt_read = invoke("corrupt-original", ["read", corrupted_root])
    if not (
        corrupt_read["status"] == "PENDING_ORIGINAL_READBACK"
        and corrupt_read["pending"]
    ):
        raise AssertionError(
            'qualification failed: corrupt_read["status"] == "PENDING_ORIGINAL_READBACK" and corrupt_read["pending"]'
        )
    if not (
        corrupt_read["owner_revision"] == 0
        and corrupt_read["diagnostic_head_inference_executions"] == 0
    ):
        raise AssertionError(
            'qualification failed: corrupt_read["owner_revision"] == 0 and corrupt_read["diagnostic_head_inference_executions"] == 0'
        )

    recovered = invoke("recover-original", ["read", pending_root])
    if not (recovered["status"] == "COMMITTED" and recovered["owner_revision"] == 1):
        raise AssertionError(
            'qualification failed: recovered["status"] == "COMMITTED" and recovered["owner_revision"] == 1'
        )
    if not (
        (
            recovered["diagnostic_head_inference_executions"],
            recovered["inference_readbacks"],
        )
        == (0, 1)
    ):
        raise AssertionError(
            'qualification failed: (recovered["diagnostic_head_inference_executions"], recovered["inference_readbacks"]) == (0, 1)'
        )
    replayed = invoke("recovered-cold-read", ["read", pending_root])
    if not (
        replayed["decision"] == recovered["decision"]
        and replayed["owner_revision"] == 1
    ):
        raise AssertionError(
            'qualification failed: replayed["decision"] == recovered["decision"] and replayed["owner_revision"] == 1'
        )
    if not (
        (
            replayed["encoder_calls"],
            replayed["diagnostic_head_inference_executions"],
            replayed["inference_readbacks"],
        )
        == (0, 0, 0)
    ):
        raise AssertionError(
            'qualification failed: (replayed["encoder_calls"], replayed["diagnostic_head_inference_executions"], replayed["inference_readbacks"]) == (0, 0, 0)'
        )

    negative = {}
    for label, changed in (("source-drift", "wire.json"), ("head-drift", "head.json")):
        root = output / label
        shutil.copytree(first_root, root)
        raw = bytearray((root / changed).read_bytes())
        raw[0] ^= 1
        (root / changed).write_bytes(raw)
        negative[label] = invoke(label, ["read", root], success=False)
        if not ("retained source changed" in negative[label]):
            raise AssertionError(
                'qualification failed: "retained source changed" in negative[label]'
            )
    root = output / "source-rebound"
    shutil.copytree(first_root, root)
    changed = json.loads((root / "expected.json").read_bytes())
    changed["source_frontier"][0] ^= 1
    raw = json.dumps(changed).encode()
    (root / "expected.json").write_bytes(raw)
    manifest = json.loads((root / "manifest.json").read_bytes())
    manifest["files"]["expected.json"] = list(hashlib.sha256(raw).digest())
    (root / "manifest.json").write_text(json.dumps(manifest))
    negative["source-rebound"] = invoke("source-rebound", ["read", root], success=False)
    if not ("JournalCorrupt" in negative["source-rebound"]):
        raise AssertionError(
            'qualification failed: "JournalCorrupt" in negative["source-rebound"]'
        )
    root = output / "journal-rollback"
    shutil.copytree(first_root, root)
    (root / "cell.journal").write_bytes((root / "cell.journal").read_bytes()[:40])
    negative["journal-rollback"] = invoke(
        "journal-rollback", ["read", root], success=False
    )
    if not ("AcknowledgedHistoryMissing" in negative["journal-rollback"]):
        raise AssertionError(
            'qualification failed: "AcknowledgedHistoryMissing" in negative["journal-rollback"]'
        )
    root = output / "no-original-admission"
    shutil.copytree(first_root, root)
    for name in ("cell.journal", "witness.journal"):
        (root / name).write_bytes(b"")
    (root / "head-claim.bin").unlink()
    (root / "head-receipt.json").unlink()
    negative["no-original-admission"] = invoke(
        "no-original-admission", ["read", root], success=False
    )
    if not (
        "read-only request has no original admission"
        in negative["no-original-admission"]
    ):
        raise AssertionError(
            'qualification failed: "read-only request has no original admission" in negative["no-original-admission"]'
        )
    if not (not (root / "head-claim.bin").exists()):
        raise AssertionError(
            'qualification failed: not (root / "head-claim.bin").exists()'
        )

    report = {
        "schema": "perc1.native-owner-qualification-report.v1",
        "status": "PASS_LOCAL_MECHANISM_ONLY",
        "scientific_status": "HOLD",
        "input_classification": input_classification,
        "classification_scope": "caller declaration; capture provenance must be checked separately",
        "binary_sha256": sha(binary.read_bytes()),
        "inputs_sha256": {
            str(path): sha(path.read_bytes())
            for path in (wire, raster, expected, head_path)
        },
        "native_library_owner": "CellOwnerJournalV1<FileAnchorWitnessStore>",
        "actual_head_executions": 2,
        "head_provenance": head["provenance"],
        "head_outputs_match_independent_integer_oracle": True,
        "completed_cold_replays_without_encoder_or_inference": 3,
        "lost_ack_recovered_from_original_without_new_compute": True,
        "missing_or_changed_original_keeps_pending_without_new_compute": True,
        "negative_controls": {name: True for name in negative},
        "native_cell_owner_exercised": True,
        "daemon_admission_exercised": False,
        "trained_semantic_model_executed": False,
        "production_owner_enrolled": False,
        "independent_real_task_benefit_established": False,
        "measurements": "child command wall; native head wall/vector capacity; no CPU/RSS/energy/billing qualification",
        "invocations": len(invocations),
    }
    (output / "REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "wire", "raster", "expected", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--input-classification",
        choices=("captured_source", "hand_authored_interoperability"),
        required=True,
    )
    args = parser.parse_args()
    print(
        json.dumps(
            qualify(
                args.binary,
                args.wire,
                args.raster,
                args.expected,
                args.output,
                args.input_classification,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
