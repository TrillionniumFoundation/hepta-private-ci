"""One-attempt parent, admission, pre-exec limits, originals, and terminal record."""

import json
import os
import resource
import subprocess
import sys
import time
import traceback
from pathlib import Path

from . import audit, resource_guard


def write(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n")


def child_limits():
    resource.setrlimit(resource.RLIMIT_AS, (resource_guard.AS_BYTES, resource_guard.AS_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))


def main():
    output = Path(os.environ["RUN_OUTPUT"])
    output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    status, detail, child_code = "RED", "not started", None
    try:
        write(output / "START.json", {
            "identity": resource_guard.KEY, "source_sha": os.environ.get("GITHUB_SHA"),
            "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "started_unix": started, "maximum_attempts": 1,
        })
        pre = resource_guard.capture()
        write(output / "PRE_RESOURCE.json", pre)
        admission = resource_guard.admit()
        write(output / "ADMISSION.json", admission)
        command = [sys.executable, "-m", "qualification.hcsn_currentstate_n256_dense_compatible_firststep_execution.child", str(output)]
        completed = subprocess.run(command, capture_output=True, timeout=600, check=False, preexec_fn=child_limits)
        child_code = completed.returncode
        (output / "CHILD_STDOUT.bin").write_bytes(completed.stdout)
        (output / "CHILD_STDERR.bin").write_bytes(completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"child exit {completed.returncode}")
        audit.run(output)
        status, detail = "PASS", "strict boundary and final bitwise gates passed"
    except BaseException as error:
        detail = f"{type(error).__name__}: {error}"
        write(output / "PARENT_ERROR.json", {"detail": detail, "traceback": traceback.format_exc()})
    finally:
        try:
            write(output / "POST_RESOURCE.json", resource_guard.capture())
        except BaseException as error:
            write(output / "POST_RESOURCE_ERROR.json", {"type": type(error).__name__, "message": str(error)})
        write(output / "TERMINAL.json", {
            "schema": "hcsn-n256-dense-compatible-firststep-terminal-v1",
            "status": status, "detail": detail, "child_exit_code": child_code,
            "elapsed_seconds": time.time() - started,
            "historical_sparse_red_preserved": True,
            "c2_full_replay_completed_fits": 0, "hpca_status": "NoUpdate",
            "production_adoption": False, "all_closed": False,
        })
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
