"""Materialize the immutable, create-only D-calibration stage and execute it once."""

import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

stage_started = time.monotonic()
payload = json.load(sys.stdin)
request = json.loads(payload["files"]["REQUEST.json"])
resource.setrlimit(resource.RLIMIT_AS, (request["budget"]["address_space_bytes"],) * 2)
resource.setrlimit(resource.RLIMIT_CPU, (request["budget"]["whole_seconds"],) * 2)
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
root = Path(request["output_root"])
root.mkdir(exist_ok=False)
for name, contents in payload["files"].items():
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("bounded source path")
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())
freeze = hashlib.sha256((root / "SOURCE_FREEZE.json").read_bytes()).hexdigest()
if freeze != payload["dispatch"]["source_freeze_sha256"]:
    raise ValueError("dispatch source freeze changed")
with (root / "DISPATCH.json").open("x") as stream:
    json.dump(payload["dispatch"], stream, sort_keys=True, indent=2)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
os.chdir(root)
print(json.dumps({"status": "SOURCE_MATERIALIZED", "source_freeze_sha256": freeze,
                  "source_commit": payload["dispatch"]["source_commit"]}), flush=True)
os.execv(sys.executable, [sys.executable, "-B", str(root / "supervisor.py"), str(root), str(stage_started)])
