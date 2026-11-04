#!/usr/bin/env python3
"""Execute the separately reviewed reproducer, never code from an artifact."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path.cwd()
output = Path(os.environ["EVIDENCE_DIRECTORY"])
script = root / "dylint-proof/qualification/dylint-20261103/hosted-30ad34/verify.py"
base = [str(script), "--repository", str(root / "source"),
        "--artifact", str(output / "original.zip")]
runs = []
for optimized in (False, True):
    destination = output / ("root-optimized.json" if optimized else "root-reproducer.json")
    if destination.exists():
        raise RuntimeError("stale reproducer output")
    argv = [sys.executable, *(["-O"] if optimized else []), *base, "--output", str(destination)]
    result = subprocess.run(argv, capture_output=True)
    raw = result.stdout + result.stderr
    (output / ("root-optimized.log" if optimized else "root-reproducer.log")).write_bytes(raw)
    runs.append({"optimized": optimized, "argv": argv, "exit": result.returncode,
                 "log_sha256": hashlib.sha256(raw).hexdigest()})
    print(raw.decode(errors="replace"), flush=True)
    if optimized:
        if result.returncode == 0 or destination.exists() or b"optimized Python is not accepted" not in raw:
            raise RuntimeError("optimized Python was not specifically rejected")
    elif result.returncode != 0 or not destination.is_file():
        raise RuntimeError("independent original reproducer failed")
report = {"reproducer_commit": "b744660a0ebd2b31726c38445cab810a8c3b1626",
          "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
          "runs": runs, "positive_passed": True, "optimized_rejected": True,
          "original_result": json.loads((output / "root-reproducer.json").read_bytes())}
(output / "ROOT_REPRODUCER_VERIFIED.json").write_text(json.dumps(report, indent=2) + "\n")
print("ROOT_REPRODUCER_VERIFIED_JSON=" + json.dumps(report, separators=(",", ":")))
