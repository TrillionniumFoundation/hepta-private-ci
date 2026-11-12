#!/usr/bin/env python3
"""Scoped original QA run; no full source closure or runtime coverage claim."""

import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE / "proof-source"
PHASE = sys.argv[1]
if PHASE not in {"old-markers", "synchronized-markers"}:
    raise SystemExit("unknown phase")
RECORDS = HERE / "records" / PHASE
RECORDS.mkdir(parents=True, exist_ok=False)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob_sha": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def inventory():
    return {
        path.relative_to(ROOT).as_posix(): identity(path.read_bytes())
        for path in sorted(ROOT.rglob("*"))
        if path.is_file()
    }


def save(name, data):
    (RECORDS / name).write_text(json.dumps(data, indent=2) + "\n")


before = inventory()
save("source-before.json", before)
command = [
    sys.executable,
    "-B",
    "-m",
    "unittest",
    "discover",
    "-s",
    "qa/b4-no-bypass",
    "-p",
    "test_original_evaluation_retention_guard_source_closure.py",
    "-v",
]
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
save("execution-start.json", {
    "phase": PHASE,
    "scope": "three original source-mutation QA methods in partial isolated projection",
    "not_full_source_gate": True,
    "not_runtime_guard_coverage": True,
    "command": command,
    "cwd": str(ROOT),
    "timeout_seconds": 600,
    "started_at": started,
    "execution_attempted": True,
})
start = time.monotonic()
timed_out = False
exception = None
returncode = None
with (RECORDS / "raw.log").open("wb") as log:
    try:
        process = subprocess.run(
            command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=600
        )
        returncode = process.returncode
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exception = repr(error)
    except BaseException as error:
        exception = repr(error)
elapsed = time.monotonic() - start
after = inventory()
save("source-after.json", after)
result = {
    "phase": PHASE,
    "scope": "three original source-mutation QA methods in partial isolated projection",
    "not_full_source_gate": True,
    "not_runtime_guard_coverage": True,
    "command": command,
    "cwd": str(ROOT),
    "timeout_seconds": 600,
    "started_at": started,
    "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "elapsed_seconds": elapsed,
    "returncode": returncode,
    "timed_out": timed_out,
    "exception": exception,
    "source_unchanged": before == after,
    "source_files": len(before),
    "raw_log": identity((RECORDS / "raw.log").read_bytes()),
    "status": "unknown" if exception else (
        "passed_scoped_qa" if returncode == 0 and before == after
        else "failed_scoped_qa"
    ),
}
save("result.json", result)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] == "passed_scoped_qa" else 1)
