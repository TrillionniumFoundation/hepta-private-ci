"""Retain logs, source identity and full child resource use for select/score."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


REPOSITORY = Path(__file__).resolve().parents[3]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("select", "score"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--supporting-file", type=Path, action="append", default=[])
    args = parser.parse_args()
    output = args.output.resolve()
    name = args.phase + "_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = output / "phase_execution" / name
    folder.mkdir(parents=True, exist_ok=False)
    command = [str(args.python.absolute()), "-m", "experiments.call_put_stable_flow.study",
               args.phase, "--output", str(output)]
    environment = os.environ.copy()
    settings = {name: "1" for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                       "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")}
    settings.update({"PYTHONHASHSEED": "0", "PYTHONUNBUFFERED": "1"})
    environment.update(settings)
    supporting = []
    for index, path in enumerate(args.supporting_file):
        path = path.resolve()
        retained = folder / f"support_{index:02d}_{path.name}"
        shutil.copy2(path, retained)
        supporting.append({"source": str(path), "sha256": digest(path), "snapshot": retained.name})
    shutil.copy2(__file__, folder / "phase_runner_source.py")
    write_json(folder / "start.json", {"phase": args.phase, "command": command,
                                       "protocol_sha256": digest(output / "protocol.json"),
                                       "runner_source_sha256": digest(Path(__file__)),
                                       "thread_environment": settings, "supporting": supporting,
                                       "unix_time": time.time()})
    began = time.monotonic()
    with (folder / "stdout.log").open("x") as stdout, (folder / "stderr.log").open("x") as stderr:
        process = subprocess.Popen(command, cwd=REPOSITORY, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    expected = (["all_training_complete_seal.json", "selection.json", "selection_seal.json"]
                if args.phase == "select" else ["results.json"])
    result = {"phase": args.phase, "returncode": process.returncode,
              "external_wall_seconds": time.monotonic() - began,
              "child_user_cpu_seconds": usage.ru_utime, "child_system_cpu_seconds": usage.ru_stime,
              "child_total_cpu_seconds": usage.ru_utime + usage.ru_stime,
              "peak_rss_bytes": usage.ru_maxrss * (1 if platform.system() == "Darwin" else 1024),
              "outputs": {name: digest(output / name) for name in expected if (output / name).exists()},
              "stdout_sha256": digest(folder / "stdout.log"),
              "stderr_sha256": digest(folder / "stderr.log")}
    write_json(folder / "finish.json", result)
    print(json.dumps({"phase": args.phase, "receipt": str(folder / "finish.json"), **result}), flush=True)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
