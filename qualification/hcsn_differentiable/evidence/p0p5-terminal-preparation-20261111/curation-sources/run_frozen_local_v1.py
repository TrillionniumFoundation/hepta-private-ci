"""Record one complete local child exit; no automatic retry or scientific gate."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    output, source = map(Path, sys.argv[1:3])
    command = sys.argv[3:]
    assert command and source.is_file()
    before = source.read_bytes()
    output.mkdir(exist_ok=False)
    with (output / "stdout").open("xb") as stdout, (output / "stderr").open("xb") as stderr:
        started = time.monotonic()
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        pid, status, usage = os.wait4(process.pid, 0)
        elapsed = time.monotonic() - started
        process.returncode = os.waitstatus_to_exitcode(status)
    result = {
        "schema": "hcsn-local-complete-child-receipt-v1", "command": command,
        "pid": pid, "returncode": process.returncode,
        "source": str(source), "source_sha256": hashlib.sha256(before).hexdigest(),
        "source_unchanged": source.read_bytes() == before,
        "complete_child_wall_seconds": elapsed,
        "complete_child_wait4_CPU_seconds": usage.ru_utime + usage.ru_stime,
        "wait4_peak_RSS_KiB": usage.ru_maxrss,
        "scope": "Local Linux child pre-spawn through wait4 reap. The wrapper's final hashing, receipt write and exit are outside this measurement. No grand total or scientific pass inferred.",
        "output_files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                         for name in ("stdout", "stderr") for raw in [(output / name).read_bytes()]},
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result))
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
