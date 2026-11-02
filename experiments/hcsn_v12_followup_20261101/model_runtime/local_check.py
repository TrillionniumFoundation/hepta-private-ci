"""Fresh NumPy-only model workers followed by separate standard-library audits.

This local campaign is not a cgroup memory measurement. Its parent deliberately
imports neither NumPy nor Torch, keeping model and audit process scopes apart.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
PREFIX = "experiments.hcsn_v12_followup_20261101.model_runtime."


def write(path, payload):
    with path.open("x") as stream:
        json.dump(payload, stream, indent=2); stream.write("\n")


def run(command, destination, environment):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    began = time.monotonic()
    with (destination / "stdout.log").open("x") as stdout, (destination / "stderr.log").open("x") as stderr:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr, timeout=1800)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"command": command, "returncode": result.returncode,
        "complete_direct_child_cpu_seconds": (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime),
        "wall_seconds": time.monotonic() - began, "cpu_scope": "Nested in enclosing local campaign CPU"}
    write(destination / "CHILD_RECEIPT.json", receipt)
    if result.returncode:
        raise RuntimeError("Fresh model/audit process failed: " + str(destination))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    bundle = args.bundle.resolve()
    manifest = json.loads((bundle / "CI_MANIFEST.json").read_text())
    environment = dict(os.environ)
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    write(args.output / "PROTOCOL.json", {"source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "ci_manifest_sha256": hashlib.sha256((bundle / "CI_MANIFEST.json").read_bytes()).hexdigest(),
        "python": sys.executable, "threads": {k: environment[k] for k in (
            "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
        "scope": "Actual single fresh NumPy model then separate waited stdlib verifier; no local cgroup memory claim"})
    probe = args.output / "dependency_probe"; probe.mkdir()
    run([sys.executable, "-c", "import importlib.util,numpy,scipy,json; print(json.dumps({'numpy':numpy.__version__,'scipy':scipy.__version__,'torch_available':importlib.util.find_spec('torch') is not None})); assert importlib.util.find_spec('torch') is None"], probe, environment)
    rows = []
    for item in manifest["models"]:
        for implementation in (("expm", "uniformization") if item["family"] == "filter" else ("expm",)):
            name = f"{item['task']}-{item['family']}-{item['seed']}-{implementation}"
            work = args.output / name; work.mkdir()
            model_cost = work / "model_cost"; model_cost.mkdir()
            worker = work / "worker"
            command = [sys.executable, "-m", PREFIX + "numpy_runtime", "--bundle", str(bundle), "--out", str(worker),
                "--task", item["task"], "--family", item["family"], "--seed", str(item["seed"]),
                "--implementation", implementation]
            model_receipt = run(command, model_cost, environment)
            audit_cost = work / "audit_cost"; audit_cost.mkdir()
            audit_receipt = run([sys.executable, "-m", PREFIX + "verify_runtime", "--bundle", str(bundle),
                "--run", str(worker.resolve()), "--out", str((work / "VERIFY.json").resolve())], audit_cost, environment)
            rows.append({"model": item, "implementation": implementation, "worker": str(worker),
                "model_cpu_nested": model_receipt["complete_direct_child_cpu_seconds"],
                "audit_cpu_nested": audit_receipt["complete_direct_child_cpu_seconds"]})
    write(args.output / "SUMMARY.json", {"status": "passed", "model_tasks": len(rows), "rows": rows,
        "scope": "NumPy-only real inference and independent post-exit semantic checks; cgroup/GPU/energy unmeasured"})


if __name__ == "__main__":
    main()
