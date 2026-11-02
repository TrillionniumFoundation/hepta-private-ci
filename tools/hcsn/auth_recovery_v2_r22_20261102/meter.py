"""Outer wait4 accounts for verifier startup, native actors and witness children."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = args.output.resolve()
    command = [sys.executable, "-m", "tools.hcsn.auth_recovery_v2_r22_20261102.verify", "--output", str(path)]
    started = time.monotonic()
    with path.with_suffix(".stdout").open("xb") as out, path.with_suffix(".stderr").open("xb") as err:
        process = subprocess.Popen(command, stdout=out, stderr=err)
        _, status, use = os.wait4(process.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        process.returncode = code
    receipt = {"command": command, "exit_code": code, "child_family_cpu_seconds": use.ru_utime+use.ru_stime,
               "wall_seconds": time.monotonic()-started, "max_child_process_rss_kib": use.ru_maxrss,
               "scope": "Complete verifier worker including imports and waited native/witness descendants; inner native CPU is nested and not added.",
               "prior_unmetered_development_cpu_seconds": None, "production_activation": False}
    path.with_suffix(".process.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(json.dumps(receipt, sort_keys=True))
    sys.exit(code)


if __name__ == "__main__":
    main()
