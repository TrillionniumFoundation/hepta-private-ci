"""Execute a real retained model through the bounded resident process profile.

The existing head artifacts are synthetic-corpus training evidence. This proves
process/model consumption, reply reuse, restart lookup and physical cancellation,
not a selected Agentd deployment, genuine future-window efficacy or action success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

import decision_cell_bakeoff as panel

WORKER = Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python"
sys.path.insert(0, str(WORKER))
from decision_cell_process import FrozenEncoderProcess, WorkerCancelled, build_request, canonical


def probe(receipt_path: Path, model_path: Path) -> dict:
    source = panel.repository_source()
    receipt, receipt_digest = panel.verified_receipt(receipt_path)
    if receipt["model_name"] != "mdeberta-v3-base":
        raise ValueError("this explicit runtime profile only admits mDeBERTa")
    artifact = receipt["head_artifact"]
    manifest = panel._tensor_module.strict_json(panel._tensor_module.checked_bytes(
        Path(artifact["manifest_path"]), artifact["manifest_sha256"], 256 * 1024))
    expected = {"schema": "hepta.frozen-encoder-ready.v1", "session_id": "probe." + uuid.uuid4().hex,
        "head_manifest_sha256": artifact["manifest_sha256"],
        "base_snapshot_digest": receipt["base_model"]["snapshot_digest"],
        "runtime_profile_sha256": hashlib.sha256(canonical(manifest["runtime_profile"])).hexdigest(),
        "device": "cpu", "advisory_only": True, "external_effect": False}
    # Explicit CPU dependency environment; no credentials or provider variables.
    environment = {name: os.environ[name] for name in ("PATH", "PYTHONPATH", "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "TOKENIZERS_PARALLELISM") if name in os.environ}
    environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONNOUSERSITE": "1"})
    def launch():
        command = [sys.executable, "-u", str(WORKER / "frozen_decision_cell_worker.py"),
            "--session-id", expected["session_id"], "--model-path", str(model_path),
            "--manifest", artifact["manifest_path"], "--manifest-sha256", artifact["manifest_sha256"],
            "--weights", artifact["weights_path"], "--weights-sha256", artifact["weights_sha256"],
            "--base-snapshot-sha256", expected["base_snapshot_digest"],
            "--runtime-profile-sha256", expected["runtime_profile_sha256"]]
        return FrozenEncoderProcess(command, expected, environment=environment)
    examples = [row for row in panel.build_dataset() if row.split == "test"][:2]
    recorded = []
    startup = time.monotonic_ns()
    child = launch()
    startup = time.monotonic_ns() - startup
    try:
        for index, example in enumerate(examples):
            request = build_request(f"probe.{index}", example.text, example.candidates,
                                    deadline_ns=time.monotonic_ns() + 120 * 10**9)
            # Qualification-only invocation identity. It is not a signed product grant.
            identity = hashlib.sha256(canonical({"request": request, "source": source})).hexdigest()
            observed = child.exchange(request, identity, timeout_seconds=120)
            if observed["status"] != "observed":
                raise ValueError("real model did not return a terminal inference observation")
            lookup = child.exchange(request, identity, kind="lookup")
            duplicate = child.exchange(request, identity, timeout_seconds=120)
            if observed != lookup or observed != duplicate:
                raise ValueError("duplicate request or lost-reply lookup changed retained output")
            recorded.append({"request_sha256": observed["request_sha256"],
                "projection_sha256": observed["projection_sha256"], "invocation_sha256": identity,
                "reply_sha256": hashlib.sha256(canonical(observed)).hexdigest(),
                "base_forward_passes": observed["observation"]["base_forward_passes"],
                "latency_ns": observed["observation"]["latency_ns"]})
        first_pid = child.pid
    finally:
        child.close()
    if child._process.poll() is None:
        raise ValueError("first model child not reaped")
    # A fresh process cannot report the previous invocation absent or recompute it.
    child = launch()
    try:
        lookup = child.exchange(request, identity, kind="lookup")
        if lookup["status"] != "unknown" or lookup["observation"] is not None:
            raise ValueError("fresh worker fabricated historical completion/absence")
        request = build_request("probe.cancel", examples[0].text, examples[0].candidates,
                                deadline_ns=time.monotonic_ns() + 120 * 10**9)
        event = threading.Event()
        timer = threading.Timer(0.05, event.set)
        timer.start()
        started = time.monotonic_ns()
        try:
            child.exchange(request, "c" * 64, timeout_seconds=120, cancel=event)
        except WorkerCancelled:
            cancellation_ns = time.monotonic_ns() - started
        else:
            raise ValueError("cancellation did not interrupt the model process")
        finally:
            timer.join()
        if child._process.poll() is None:
            raise ValueError("cancelled model process was not reaped")
        cancelled_pid = child.pid
    finally:
        child.close()
    if panel.repository_source() != source:
        raise ValueError("source changed during qualification")
    return {"schema": "hepta.frozen-encoder-process-probe.v1", "source": source,
        "training_receipt_sha256": receipt_digest, "head_manifest_sha256": artifact["manifest_sha256"],
        "base_snapshot_digest": expected["base_snapshot_digest"],
        "runtime_profile_sha256": expected["runtime_profile_sha256"],
        "source_sha256": {p.name: panel.sha256_file(p) for p in WORKER.glob("*.py")},
        "model_loads": 2, "first_pid": first_pid, "cancelled_pid": cancelled_pid,
        "first_startup_ns": startup, "observations": recorded, "duplicate_reply_reused": True,
        "restart_lookup": "unknown_without_inference", "cancelled_process_reaped": True,
        "cancellation_ns": cancellation_ns, "runtime_selection_eligible": False,
        "production_activation": False, "operator_acceptance": False, "external_effect": False,
        "prospective_future_window_evidence": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = probe(args.receipt.resolve(strict=True), args.model_path.resolve(strict=True))
    data = canonical(report)
    with args.output.open("xb") as stream:
        stream.write(data)
    print(json.dumps({"status": "PASS_REAL_FROZEN_ENCODER_PROCESS", "receipt": str(args.output),
        "sha256": hashlib.sha256(data).hexdigest(), "model_loads": report["model_loads"],
        "cancellation_ms": report["cancellation_ns"] / 1e6,
        "production_activation": False}, sort_keys=True))
