"""Retain UTC boundaries and process outcomes without changing frozen audit code."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
stage = sys.argv[1]
path = root / f"{stage}-launch.json"
if path.exists() or (root / f"{stage}-receipt.json").exists():
    raise SystemExit("Retained stage exists; refuse overwrite")
record = {"stage": stage, "started_utc": datetime.now(timezone.utc).isoformat(),
    "command": ["/workspace/scratch/c385a7439f8e/hcsn-study-env/bin/python", str(root / "runner.py"), stage],
    "concurrency_disclosure": "May overlap the training agent's one-worker PLIF fixed-update diagnostic. Compare per-process UTC intervals; this audit wall time is not a fair-training metric."}
path.write_text(json.dumps(record, indent=2) + "\n")
started = time.perf_counter()
with (root / f"{stage}.stdout").open("x") as out, (root / f"{stage}.stderr").open("x") as err:
    result = subprocess.run(record["command"], stdout=out, stderr=err,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
record.update(exit_code=result.returncode, ended_utc=datetime.now(timezone.utc).isoformat(),
              outer_wall_seconds=time.perf_counter() - started)
path.write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record))
raise SystemExit(result.returncode)
