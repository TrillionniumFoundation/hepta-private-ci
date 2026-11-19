"""Record ordinary and optimized synthetic controls, with full child costs."""

import json
import os
from pathlib import Path
import sys
import time


HERE = Path(__file__).resolve().parent


def main():
    output = HERE / "development" / "controls001"
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for mode in ("normal", "optimized"):
        command = [sys.executable] + (["-O"] if mode == "optimized" else []) + [str(HERE / "controls.py")]
        start = time.perf_counter()
        pid = os.fork()
        if not pid:
            for suffix, fd in (("stdout", 1), ("stderr", 2)):
                handle = os.open(output / f"{mode}.{suffix}", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                os.dup2(handle, fd)
                os.close(handle)
            os.execve(sys.executable, command, os.environ.copy())
        _, status, usage = os.wait4(pid, 0)
        rows.append({"mode": mode, "command": command,
                     "exit_code": os.waitstatus_to_exitcode(status),
                     "whole_child_wall_upper_seconds": time.perf_counter() - start,
                     "child_user_seconds": usage.ru_utime,
                     "child_system_seconds": usage.ru_stime,
                     "child_peak_rss_kib": usage.ru_maxrss})
    (output / "COST.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows))
    return 0 if all(row["exit_code"] == 0 for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
