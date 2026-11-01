"""Fresh-process wall/CPU/RSS receipts, including imports and output writes."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def measured(command, destination, cwd):
    """Waited descendants are included by Linux wait4; no peak sums are claimed."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    start = time.perf_counter()
    with destination.with_suffix(".log").open("xb") as log:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    receipt = dict(command=command, returncode=child.returncode,
        wall_seconds=time.perf_counter() - start,
        cpu_seconds=usage.ru_utime + usage.ru_stime, peak_rss_bytes=usage.ru_maxrss * 1024,
        input_blocks=usage.ru_inblock, output_blocks=usage.ru_oublock,
        voluntary_context_switches=usage.ru_nvcsw, involuntary_context_switches=usage.ru_nivcsw,
        scope="Linux wait4 fresh process and waited descendants; imports/loading/evaluation/output included",
        timing_environment="Single thread, shared host; other tenants cannot be excluded",
        device_energy_joules=None, energy_sensor_available=False,
        log_sha256=digest(destination.with_suffix(".log")))
    write_json(destination, receipt)
    if child.returncode:
        raise RuntimeError(f"Worker failed; retained receipt: {destination}")
    return receipt
