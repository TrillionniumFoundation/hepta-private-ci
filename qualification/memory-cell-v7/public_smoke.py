"""Run eight frozen public wiring examples through the real language worker.

This Linux diagnostic uses a synthetic address registry, supplies no memory
values, and grants no authority. It is neither an owner integration test nor
independent language evaluation. Rejections are retained without tuning.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

from prepare_language_ci import MANIFEST_SHA256, checked_bytes, safe_path


PROJECT = Path(__file__).resolve().parent
CASES = (
    ("meter:agentd-cell", "current", "Retrieve Orion's latest unprocessed sample."),
    ("meter:language-vega", "history", "For Vega, recall the reading on file by the supplied cutoff."),
    ("meter:agentd-cell", "semantic", "Recall Orion's stored multiplier itself."),
    ("meter:language-vega", "procedure", "Describe only the saved steps for Vega, without executing them."),
    ("meter:agentd-cell", "change", "Read Orion's current and earlier values, then return current minus earlier."),
    ("meter:language-vega", "apply", "Use Vega's saved recipe to produce a result from its latest observation."),
    ("meter:unregistered-sirius", None, "Retrieve Sirius's latest unprocessed sample."),
    ("meter:agentd-cell", None, "Square Orion's stored factor."),
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output, model, encoder = map(safe_path, (args.output, args.model, args.encoder))
    if output.exists():
        parser.error("diagnostic evidence is create-only; output already exists")
    manifest = json.loads(checked_bytes(model / "manifest.json", MANIFEST_SHA256))
    checked_bytes(model / "weights.npz", manifest["weights_sha256"], manifest["weights_bytes"])
    scope = "memory:public-worker-smoke"
    source_cut = sha256(b"synthetic-registry-for-public-worker-diagnostic-no-owner-authority")
    registry = {
        "schema": "hepta.memory.v7.owner-registry.v1", "scope": scope, "source_cut": source_cut,
        "entities": [
            {"entity": "meter:agentd-cell", "aliases": ["Orion"]},
            {"entity": "meter:language-vega", "aliases": ["Vega"]},
        ],
    }
    frames = []
    for index, (entity, _, text) in enumerate(CASES):
        request = {"query_id": f"query:public-worker-smoke-{index}", "scope": scope,
                   "entity": entity, "text": text, "at": 15, "since": 10,
                   "max_hops": 3, "max_cells": 3, "source_cut": source_cut}
        frames.append({"schema": "hepta.memory.v7.address-worker-request.v1",
                       "request": request, "registry": registry})
    payload = b"".join(canonical(frame) + b"\n" for frame in frames)
    code_files = [Path(__file__).resolve(), PROJECT / "prepare_language_ci.py",
                  *sorted((PROJECT / "addressing").glob("*.py")),
                  PROJECT.parent / "memory-cell-v6/v6/__init__.py",
                  PROJECT.parent / "memory-cell-v6/v6/encoder.py"]
    code = {str(path.relative_to(PROJECT.parent.parent)): sha256(path.read_bytes()) for path in code_files}
    command = [str(Path(sys.executable).absolute()), "-I", "-u", "-B", str(PROJECT / "addressing/worker.py"),
               "--model", str(model), "--model-digest", MANIFEST_SHA256, "--encoder", str(encoder)]
    environment = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter_ns()
    failure = None
    try:
        result = subprocess.run(command, input=payload, capture_output=True, env=environment, timeout=60, check=False)
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, returncode = error.stdout or b"", error.stderr or b"", None
        failure = "worker-exceeded-60-second-deadline"
    wall_ns = time.perf_counter_ns() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    responses = []
    try:
        if len(stdout) > 8 * 32_768 or len(stderr) > 65_536:
            raise ValueError("worker output exceeded declared frame bounds")
        ready = json.loads(stderr)
        if (ready.get("schema"), ready.get("model_digest"), ready.get("policy_digest")) != (
                "hepta.memory.v7.address-worker-ready.v1", MANIFEST_SHA256, manifest["policy_digest"]):
            raise ValueError("worker readiness differs")
        responses = [json.loads(line) for line in stdout.splitlines()]
        if returncode != 0 or len(responses) != len(CASES):
            raise ValueError("worker exit status or response count differs")
    except (ValueError, TypeError) as error:
        ready = None
        failure = failure or str(error)
    observations, failed = [], []
    for index, (_, expected, _) in enumerate(CASES):
        response = responses[index] if index < len(responses) else None
        matches = response is not None and (
            (response.get("status"), (response.get("plan") or {}).get("operation")) ==
            (("accepted", expected) if expected is not None else ("rejected", None)))
        if response is not None:
            matches = matches and response.get("authority") is False and response.get("model_digest") == MANIFEST_SHA256
            matches = matches and response.get("query_id") == frames[index]["request"]["query_id"]
            matches = matches and response.get("source_cut") == source_cut and response.get("registry_digest") == sha256(canonical(registry))
            matches = matches and response.get("request_digest") == sha256(canonical(frames[index]["request"]))
        if not matches:
            failed.append(index)
        observations.append({"expected_operation": expected, "expected_status": "accepted" if expected else "rejected",
                             "matches_fixed_expectation": matches, "frame": frames[index], "response": response})
    report = {
        "schema": "hepta.memory.v7.public-worker-smoke.v1", "model_digest": MANIFEST_SHA256,
        "weights_sha256": manifest["weights_sha256"], "policy_digest": manifest["policy_digest"],
        "frozen_threshold": manifest["threshold"], "frozen_margin": manifest["margin"],
        "script_sha256": code[str(Path(__file__).resolve().relative_to(PROJECT.parent.parent))],
        "code_sha256": code, "invocation": command, "python": platform.python_version(),
        "packages": {name: importlib.metadata.version(name) for name in
                     ("numpy", "scipy", "scikit-learn", "onnxruntime", "tokenizers")},
        "case_digest": sha256(canonical(CASES)), "registry_is_synthetic": True, "owner_authority_verified": False,
        "positive_phrases_from_public_fit_examples": True, "held_reads": 0, "calibration_inputs_read": 0,
        "fitting_performed": False, "threshold_or_case_changes": 0, "independent_language_evaluation": False,
        "worker_ready": ready, "exit_code": returncode, "failure": failure, "observations": observations,
        "failed_fixed_expectation_indices": failed, "accepted_supported": sum(
            item["matches_fixed_expectation"] for item in observations[:6]),
        "rejected_unsupported": sum(item["matches_fixed_expectation"] for item in observations[6:]),
        "cost": {"child_user_cpu_seconds": after.ru_utime - before.ru_utime,
                 "child_system_cpu_seconds": after.ru_stime - before.ru_stime,
                 "process_wall_ns": wall_ns, "stdin_bytes": len(payload), "stdout_bytes": len(stdout), "stderr_bytes": len(stderr)},
        "worker_stderr": stderr[:65536].decode(errors="replace"),
        "limitation": "Eight fixed public examples through a real worker; no SQLite owner/native readback or independent quality claim.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(canonical(report) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"evidence": str(output), "supported_accepted": report["accepted_supported"],
                      "unsupported_rejected": report["rejected_unsupported"], "failed_indices": failed,
                      "failure": failure, "cost": report["cost"]}), flush=True)
    raise SystemExit(1 if failure or failed else 0)


if __name__ == "__main__":
    main()
