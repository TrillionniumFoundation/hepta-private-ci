"""Linux resource bounds and receipts for trusted development candidates."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def digest(path):
    checksum, size = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            checksum.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": checksum.hexdigest()}


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def run(argv, cwd, directory, limits):
    """Reap our child and kill its remaining process group; not an OS sandbox."""
    directory.mkdir()
    started = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    record = {
        "argv": argv,
        "cwd": str(cwd),
        "limits": limits,
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "returncode": None,
        "timeout": False,
        "spawn_error": None,
    }
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "RAYON_NUM_THREADS": "1",
    }
    record["environment"] = environment
    record["cpu_affinity"] = [min(os.sched_getaffinity(0))]
    save(directory / "request.json", record)

    def restrict():
        os.sched_setaffinity(0, record["cpu_affinity"])
        resource.setrlimit(
            resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"] + 1)
        )
        resource.setrlimit(
            resource.RLIMIT_AS, (limits["address_bytes"], limits["address_bytes"])
        )
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (limits["output_file_bytes"], limits["output_file_bytes"]),
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    child = None
    try:
        with (
            (directory / "stdout").open("xb") as out,
            (directory / "stderr").open("xb") as err,
        ):
            child = subprocess.Popen(
                argv,
                cwd=cwd,
                env=environment,
                stdout=out,
                stderr=err,
                start_new_session=True,
                preexec_fn=restrict,
            )
            record["pid"] = child.pid
            try:
                record["returncode"] = child.wait(timeout=limits["wall_seconds"])
            except subprocess.TimeoutExpired:
                record["timeout"] = True
    except Exception as error:
        record["spawn_error"] = repr(error)
    finally:
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            record["returncode"] = child.wait()
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record.update(
            wall_seconds=time.monotonic() - started,
            child_cpu_seconds=after.ru_utime
            + after.ru_stime
            - before.ru_utime
            - before.ru_stime,
            cumulative_child_maxrss_kib=after.ru_maxrss,
        )
        for name in ("stdout", "stderr"):
            try:
                record[name] = digest(directory / name)
            except OSError as error:
                record[name] = {"error": repr(error)}
        save(directory / "process.json", record)
    return record
