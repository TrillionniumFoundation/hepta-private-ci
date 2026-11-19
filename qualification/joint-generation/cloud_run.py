"""Run the experiment INSIDE an already selected Codex Cloud environment.

This runner neither provisions a cloud environment nor attests its provider.
The Codex task log and repository commit are the execution-location evidence.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_bundle(run, row):
    bundle = run / "bundles" / row["name"]
    bundle.mkdir(parents=True, exist_ok=False)
    for source, dest in ((row["model_file"], "model.npz"), (row["controller_file"], "controller.npz")):
        if Path(source).name != source or (run / source).is_symlink():
            raise ValueError("invalid artifact path")
        shutil.copyfile(run / source, bundle / dest)
    manifest = {"schema": "hepta.joint-generation.bundle.v1",
                "model_sha256": row["model_sha256"], "controller_sha256": row["controller_sha256"],
                "model_digest": row["artifact_sha256"], "input_profile": "rgb8-instruction10-v1",
                "utility_profile": {"rho": row["rho"], "compute_price": row["compute_price"],
                                    "behavior_policy": "independent-categorical-v1"}}
    for name in ("model", "controller"):
        if sha(bundle / (name + ".npz")) != manifest[name + "_sha256"]:
            raise ValueError("exported bytes do not match selection")
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return str(bundle.relative_to(run))


def run(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.time_ns()
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    results = []
    for name, args in (("unit", ["-W", "error", "-m", "unittest", "discover", "-p", "test_*.py", "-v"]),
                       ("train", ["train.py", "--out", str(out)]),
                       ("evaluate", ["evaluate.py", "--run", str(out)])):
        with (out / (name + ".log")).open("w") as stream:
            completed = subprocess.run([sys.executable, *args], cwd=ROOT, env=env,
                                       stdout=stream, stderr=subprocess.STDOUT)
        results.append({"step": name, "exit_code": completed.returncode,
                        "log_sha256": sha(out / (name + ".log"))})
        print(json.dumps(results[-1]), flush=True)
        if completed.returncode and name != "evaluate":
            break
    bundles = []
    selection = out / "selection.json"
    if selection.exists():
        for row in json.loads(selection.read_text())["selected"]:
            bundles.append(export_bundle(out, row))
    result = out / "test-result.json"
    receipt = {"schema": "hepta.joint-generation.cloud-run.v1", "source_commit": git,
               "runner_sha256": sha(__file__), "started_unix_ns": started, "ended_unix_ns": time.time_ns(),
               "steps": results, "bundles": bundles,
               "test_result_sha256": sha(result) if result.exists() else None,
               "benefit_verified": json.loads(result.read_text())["benefit_verified"] if result.exists() else False,
               "execution_location": "verify against the enclosing Codex Cloud task log; not self-attested",
               "production_activation": False}
    (out / "cloud-run.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    if len(results) != 3 or any(row["exit_code"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="new directory; never reuse an opened test run")
    run(parser.parse_args().out)
