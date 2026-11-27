"""Fresh-process resource binding before importing any task/model module."""

import ctypes
import json
import math
import os
from pathlib import Path
import resource
import signal
import sys
import time


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    if sys.platform != "linux":
        raise RuntimeError("measured wait4 and parent-death enforcement require Linux")
    parent = request["parent_pid"]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_PDEATHSIG failed")
    if os.getppid() != parent:
        raise RuntimeError("budget controller disappeared before child binding")
    cpu = max(1, math.ceil(request["cpu_ns"] / 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    size = request["file_size_limit"]
    resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))
    print(
        json.dumps(
            dict(
                stage="budget-child-bound",
                pid=os.getpid(),
                parent_pid=parent,
                parent_death_signal="SIGKILL",
                cpu_limit_seconds=cpu,
                per_file_write_limit=size,
                bound_at_ns=time.time_ns(),
            )
        ),
        file=sys.stderr,
        flush=True,
    )
    os.execv(request["argv"][0], request["argv"])


if __name__ == "__main__":
    main()
