"""Linux research-process accounting; nested receipts are never summed twice."""

import json
import os
from pathlib import Path
import resource
import subprocess
import time


class Ledger:
    def __init__(self, output):
        self.output = Path(output)
        self.rows = []

    def run(self, label, command):
        environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
        start, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
        with (self.output / f"{label}.stdout").open("wb") as out, (self.output / f"{label}.stderr").open("wb") as err:
            completed = subprocess.run(command, env=environment, stdout=out, stderr=err, check=False)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.rows.append({"label": label, "command": command, "exit_code": completed.returncode,
                          "wall_seconds": time.perf_counter() - start,
                          "child_user_cpu_seconds": after.ru_utime - before.ru_utime,
                          "child_system_cpu_seconds": after.ru_stime - before.ru_stime,
                          "cumulative_child_maxrss_kib": after.ru_maxrss,
                          "rss_scope": "Linux RUSAGE_CHILDREN high-water mark, not per-stage allocation"})
        (self.output / "PROCESSES.json").write_text(json.dumps(self.rows, indent=2) + "\n")
        if completed.returncode:
            raise RuntimeError(f"{label} failed; stdout/stderr and failed receipt retained")


def inventory(directory):
    return [{"path": str(path.relative_to(directory)), "bytes": path.stat().st_size}
            for path in sorted(Path(directory).rglob("*")) if path.is_file()]
