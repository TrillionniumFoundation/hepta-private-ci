"""Replay the exact Python integration controls; no research model is invoked."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest_path = HERE / "SOURCE_MANIFEST.complete.json"
    manifest = json.loads(manifest_path.read_bytes())
    for item in manifest["files"]:
        raw = (ROOT / item["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("frozen source differs: " + item["path"])
    original = json.loads((HERE / "integrated-controls/RESULT.json").read_bytes())
    modules = original["command"][4:-1]
    command = [sys.executable, "-B", "-m", "unittest", *modules, "-v"]
    env = os.environ.copy()
    env.update(PYTHONPATH="scripts", PYTHONDONTWRITEBYTECODE="1",
               OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    run = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=240)
    wall = time.monotonic() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    (out / "stdout.log").write_bytes(run.stdout)
    (out / "stderr.log").write_bytes(run.stderr)
    match = re.search(rb"Ran (\d+) tests? in ([\d.]+)s", run.stderr)
    unchanged = all(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
                    == item["sha256"] for item in manifest["files"])
    result = {
        "command": command,
        "base_commit": manifest["base_commit"],
        "fix_commit": manifest["fix_commit"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "exit_code": run.returncode,
        "test_count": int(match[1]) if match else None,
        "unittest_seconds": float(match[2]) if match else None,
        "module_count": len(modules),
        "wall_seconds": wall,
        "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
        "source_unchanged": unchanged,
        "python": sys.version,
        "platform": platform.platform(),
        "research_model_calls": 0,
        "research_training_updates": 0,
        "original_native_e6_executions": 0,
        "stdout_sha256": hashlib.sha256(run.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(run.stderr).hexdigest(),
    }
    (out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if run.returncode:
        print(run.stderr.decode(errors="replace"))
    return run.returncode if unchanged else 2


if __name__ == "__main__":
    raise SystemExit(main())
