"""Recover one unacknowledged PTY launch through an exclusive source directory."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import time
import zipfile


archive = Path("/home/qq/hepta-cell-experiments-v3-source-01-20261116-0c078a.zip")
expected = "7d822083fd95b790a3d39196fe960f7e2848b9b971b2463622703d4ec316a95f"
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise ValueError("source archive identity mismatch")
root = Path("/home/qq/hepta-cell-experiments-v3-20261116-0c078a")
candidate = root / "candidate-smol-01"
# The original launch uses this same exclusive creation before any model call.
# Even a delayed original acknowledgement cannot create a duplicate model run.
candidate.mkdir(parents=True, exist_ok=False)
with zipfile.ZipFile(archive) as package:
    for name in package.namelist():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("archive member escapes the exclusive source directory")
    package.extractall(candidate)
runtime = "/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python"
artifacts = Path("/home/qq/hepta-cell-experiments-20261116-0c078a/run-v2-01")
environment = dict(os.environ, PYTHONPATH=str(candidate / "scripts"),
                   OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")
os.nice(10)
for arm in ("parent", "trajectory"):
    output = root / ("probe-smol-" + arm + "-01")
    manifest = artifacts / ("parent.json" if arm == "parent" else "models/trajectory/manifest.json")
    command = [runtime, "-B", "-m", "cell_experiments.development_readiness_v3",
               "--records", str(candidate / "qualification/cell-experiments-v3-20261116/development-old-open.records.jsonl"),
               "--manifest", str(manifest), "--artifact-root", str(artifacts), "--output", str(output)]
    with (root / (arm + "-probe-command.json")).open("x") as stream:
        json.dump({"argv": command, "source_archive_sha256": expected,
                   "started_at_ns": time.time_ns(),
                   "original_pty_unit_observed": "not-found/inactive/dead/MainPID=0",
                   "duplicate_guard": "exclusive candidate-smol-01 mkdir before model calls"}, stream)
    with (root / (arm + "-probe.log")).open("xb") as stream:
        result = subprocess.run(command, cwd=candidate, env=environment,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
    print(json.dumps({"arm": arm, "exit_code": result.returncode, "output": str(output)}), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
print("SMOL_DEVELOPMENT_READINESS_COMPLETE", flush=True)
