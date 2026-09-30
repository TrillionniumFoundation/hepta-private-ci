"""Exercise real frozen encoder -> typed decision -> binary IR -> real X11.

Uses the existing resident inference process and existing native clipboard probe.
Inputs are held-out synthetic commands, not GUI observations or prospective
windows. The isolated OS effect is real; backend authorization remains a fixture.
No new product owner, automatic retry, production selection or teacher is created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

import decision_cell_bakeoff as panel
from native_probe_evidence import PROFILE as NATIVE_EVALUATION_PROFILE, evaluate_native_receipt

WORKER = Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKER))
from decision_cell_process import FrozenEncoderProcess, build_request, canonical


def write_new(path: Path, data: bytes) -> str:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def run_native(command: list[str], output_dir: Path, index: int) -> tuple[int, bool]:
    """Bound one existing native probe; kill only this created process group."""
    with (output_dir / f"native-{index}.stdout").open("xb") as stdout, (output_dir / f"native-{index}.stderr").open("xb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
            env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"}, start_new_session=True)
        try:
            return process.wait(timeout=20), False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            return process.returncode, True
        finally:
            # Interruption must not leave this probe's private actuator running.
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()


def probe(receipt_path: Path, model_path: Path, output: Path, count: int) -> dict:
    if not 1 <= count <= 12:
        raise ValueError("bounded number of positive cases required")
    source = panel.repository_source()
    receipt, digest = panel.verified_receipt(receipt_path)
    if receipt["model_name"] != "mdeberta-v3-base":
        raise ValueError("the existing resident profile only admits mDeBERTa")
    artifact = receipt["head_artifact"]
    manifest = panel._tensor_module.strict_json(panel._tensor_module.checked_bytes(
        Path(artifact["manifest_path"]), artifact["manifest_sha256"], 256 * 1024))
    expected = {"schema": "hepta.frozen-encoder-ready.v1", "session_id": "nativeprobe." + uuid.uuid4().hex,
        "head_manifest_sha256": artifact["manifest_sha256"],
        "base_snapshot_digest": receipt["base_model"]["snapshot_digest"],
        "runtime_profile_sha256": hashlib.sha256(canonical(manifest["runtime_profile"])).hexdigest(),
        "device": "cpu", "advisory_only": True, "external_effect": False}
    environment = {key: os.environ[key] for key in ("PATH", "PYTHONPATH", "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "TOKENIZERS_PARALLELISM") if key in os.environ}
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONNOUSERSITE="1",
                       PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-u", str(WORKER / "frozen_decision_cell_worker.py"),
        "--session-id", expected["session_id"], "--model-path", str(model_path),
        "--manifest", artifact["manifest_path"], "--manifest-sha256", artifact["manifest_sha256"],
        "--weights", artifact["weights_path"], "--weights-sha256", artifact["weights_sha256"],
        "--base-snapshot-sha256", expected["base_snapshot_digest"],
        "--runtime-profile-sha256", expected["runtime_profile_sha256"]]
    dataset = panel.build_dataset()
    positive = [row for row in dataset if row.split == "test" and row.action == 2][:count]
    negative = [row for row in dataset if row.ood == 1 and row.split == "ood_test"][:2]
    if len(positive) != count or len(negative) != 2:
        raise ValueError("required held-out positive and OOD cases are absent")
    output.mkdir(parents=True, exist_ok=False)
    selected = [*positive, *negative]
    records = [{"example_id": example.example_id, "expected_target_index": example.target,
                "expected_ood": bool(example.ood), "status": "not_started", "phase": "not_started",
                "task_passed": False, "external_effect": False} for example in selected]
    plan_digest = write_new(output / "plan.json", canonical({
        "schema": "hepta.model-native-probe-plan.v1", "source": source,
        "training_receipt_sha256": digest, "head_manifest_sha256": artifact["manifest_sha256"],
        "cases": records, "automatic_retry": False, "production_activation": False}))
    child = None
    failure = None
    active_index = None
    phase = "model_start"
    with (output / "progress.jsonl").open("xb") as progress:
        def append_event(event):
            progress.write(canonical(event))
            progress.flush()
            os.fsync(progress.fileno())

        try:
            append_event({"event": "model_start_attempt", "plan_sha256": plan_digest})
            child = FrozenEncoderProcess(command, expected, environment=environment,
                manifest_path=Path(artifact["manifest_path"]))
            with child:
                for index, example in enumerate(selected):
                    active_index = index
                    item = records[index]
                    item.update(status="in_progress", phase="source_check")
                    if panel.repository_source() != source:
                        raise ValueError("source changed before case execution")
                    request = build_request(f"nativeprobe.{index}", example.text, example.candidates,
                                            deadline_ns=time.monotonic_ns() + 120 * 10**9)
                    invocation = hashlib.sha256(canonical({"request": request, "source": source})).hexdigest()
                    item["phase"] = "model_dispatch"
                    append_event({"event": "model_dispatch_attempt", "index": index,
                                  "invocation_sha256": invocation})
                    reply = child.exchange(request, invocation, timeout_seconds=120)
                    item["phase"] = "model_reply_validation"
                    reply_digest = write_new(output / f"model-{index}.json", canonical(reply))
                    item["model_reply_sha256"] = reply_digest
                    if reply["status"] != "observed":
                        item.update(status="model_unresolved", task_passed=False, external_effect=False)
                        item["phase"] = "finished"
                        append_event({"event": "case_finished", "index": index, "record": item})
                        continue
                    observed = reply["observation"]
                    if observed["head_manifest_sha256"] != expected["head_manifest_sha256"] or observed["base_snapshot_digest"] != expected["base_snapshot_digest"]:
                        raise ValueError("model artifact binding drift")
                    probabilities = {}
                    for key in ("action", "target", "disposition", "postcondition", "ood"):
                        values = observed["probabilities"][key]
                        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], list):
                            raise ValueError("expected one typed probability row")
                        probabilities[key] = values[0]
                    support = observed["probabilities"].get("supported")
                    if type(support) is not list or len(support) != 1 or type(support[0]) is not bool:
                        raise ValueError("expected one explicit model support decision")
                    packet = {"schema": "hepta.model-native-probe-input.v2", "requestId": request["request_id"],
                        "replySha256": reply_digest, "projectionSha256": reply["projection_sha256"],
                        "headManifestSha256": expected["head_manifest_sha256"],
                        "baseSnapshotDigest": expected["base_snapshot_digest"], "modelSupported": support[0],
                        "probabilities": probabilities,
                        "targets": [{"referenceId": f"clipboard.reference.{target}", "generation": 1,
                            "text": f"Hepta nonsecret selected target {target}: {text}"}
                            for target, text in enumerate(example.candidates)]}
                    # Match the existing JS parser's canonical byte representation exactly.
                    encoded = subprocess.run(["node", "-e", "const fs=require('fs');process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8')))+'\\n')"],
                        input=canonical(packet), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=5).stdout
                    packet_path = output / f"decision-{index}.json"
                    packet_digest = write_new(packet_path, encoded)
                    native_path = output / f"native-{index}.json"
                    item["phase"] = "source_check"
                    if panel.repository_source() != source:
                        raise ValueError("source changed before native execution")
                    item["phase"] = "native_dispatch"
                    append_event({"event": "native_dispatch_attempt", "index": index,
                                  "packet_sha256": packet_digest})
                    item["external_effect"] = None
                    try:
                        code, timed_out = run_native(["node", str(ROOT / "apps/hepta-native/qualification/x11-clipboard.mjs"),
                            str(native_path), str(packet_path), packet_digest], output, index)
                    except (Exception, KeyboardInterrupt):
                        # A process-control failure does not erase an already retained effect.
                        # The nonzero sentinel is only evaluator input; it is not a child exit.
                        item.update(evaluate_native_receipt(native_path, exit_code=130, timed_out=False,
                            packet=packet, source=source, expected_target=example.target,
                            expected_ood=bool(example.ood)))
                        item["native_exit"] = None
                        raise
                    item.update(native_exit=code, timed_out=timed_out, packet_sha256=packet_digest,
                                base_forward_passes=observed["base_forward_passes"], model_latency_ns=observed["latency_ns"])
                    item.update(evaluate_native_receipt(native_path, exit_code=code, timed_out=timed_out,
                        packet=packet, source=source, expected_target=example.target,
                        expected_ood=bool(example.ood)))
                    item["phase"] = "finished"
                    append_event({"event": "case_finished", "index": index, "record": item})
                active_index = None
                phase = "model_cleanup"
        except (Exception, KeyboardInterrupt) as error:
            failure = {"phase": records[active_index]["phase"] if active_index is not None else phase,
                       "error_type": type(error).__name__, "interrupted": isinstance(error, KeyboardInterrupt)}
            if active_index is not None:
                if records[active_index]["status"] == "in_progress":
                    records[active_index]["status"] = "execution_failed"
                records[active_index]["task_passed"] = False
                records[active_index]["execution_error"] = failure
            # Keep later cases unstarted. Never restart the model or replace a failed case.
            append_event({"event": "execution_stopped", "failure": failure})
        try:
            source_unchanged = panel.repository_source() == source
        except Exception as error:
            source_unchanged = False
            if failure is None:
                failure = {"phase": "final_source_check", "error_type": type(error).__name__, "interrupted": False}
        append_event({"event": "execution_finished", "source_unchanged": source_unchanged,
                      "model_process_reaped": child._process.poll() is not None if child is not None else None})
    report = {"schema": "hepta.model-native-execution-probe.v3", "source": source,
        "native_evaluation_profile": NATIVE_EVALUATION_PROFILE,
        "native_evaluator_sha256": hashlib.sha256((Path(__file__).parent / "native_probe_evidence.py").read_bytes()).hexdigest(),
        "training_receipt_sha256": digest, "head_manifest_sha256": artifact["manifest_sha256"],
        "profile": "synthetic-heldout-command-to-isolated-real-X11-clipboard",
        "records": records, "plan_sha256": plan_digest,
        "progress_sha256": hashlib.sha256((output / "progress.jsonl").read_bytes()).hexdigest(),
        "execution_failure": failure, "source_unchanged": source_unchanged,
        "passed": failure is None and source_unchanged and child is not None and
                  child._process.poll() is not None and all(row["task_passed"] for row in records),
        "actual_native_effects": sum(row["external_effect"] is True for row in records),
        "indeterminate_native_effects": sum(row["external_effect"] is None for row in records),
        "model_process_reaped": child._process.poll() is not None if child is not None else None,
        "calibration_trust_granted": False, "backend_and_authority_are_fixtures": True,
        "general_gui_competence": False, "durable_cross_process_recovery": False,
        "teacher_output_used": False, "prospective_future_window_evidence": False,
        "runtime_selection_eligible": False, "production_activation": False, "operator_acceptance": False}
    write_new(output / "report.json", canonical(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()
    result = probe(args.receipt.resolve(strict=True), args.model_path.resolve(strict=True), args.output_dir.resolve(), args.count)
    print(json.dumps({"passed": result["passed"], "cases": len(result["records"]),
        "actual_native_effects": result["actual_native_effects"], "output": str(args.output_dir / "report.json"),
        "production_activation": False}))
    raise SystemExit(0 if result["passed"] else 2)
