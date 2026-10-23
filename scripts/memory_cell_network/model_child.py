"""Bind one fresh Python process to its parent before importing model code.

Linux parent death sends SIGKILL, including while this child is stopped. Other
platforms report an unsupported binding; they do not claim equivalent cleanup.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import runpy
import signal
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("script", type=Path)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    protection = {"platform": sys.platform, "status": "unsupported"}
    if sys.platform == "linux":
        library = ctypes.CDLL(None, use_errno=True)
        library.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
        library.prctl.restype = ctypes.c_int
        if library.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_SET_PDEATHSIG failed")
        protection = {
            "platform": sys.platform,
            "status": "bound",
            "mechanism": "PR_SET_PDEATHSIG",
            "signal": "SIGKILL",
            "binding_scope": "creating_parent_thread",
        }
    receipt = {
        "schema": "hepta.memory-process.started.v1",
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "expected_parent_pid": args.parent_pid,
        "parent_death": protection,
        "cwd": str(Path.cwd()),
        "script": str(args.script.resolve()),
    }
    print(json.dumps(receipt, sort_keys=True), file=sys.stderr, flush=True)
    # Close the race where the parent died before the kernel binding was set.
    if os.getppid() != args.parent_pid:
        raise SystemExit("parent exited before model bootstrap")
    sys.argv = [str(args.script), *args.arguments]
    sys.path[0] = str(args.script.resolve().parent)
    runpy.run_path(str(args.script), run_name="__main__")


if __name__ == "__main__":
    main()
