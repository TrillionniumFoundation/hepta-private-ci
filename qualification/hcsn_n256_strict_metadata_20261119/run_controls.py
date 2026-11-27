"""Run the two predeclared metadata processes and retain complete child costs."""

import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parent
    freeze = json.loads((root / "SOURCE_FREEZE.json").read_text())
    for name, digest in freeze["source_sha256"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"source changed after freeze: {name}")
    output = root / "evidence" / "attempt001"
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for mode, flags in (("normal", []), ("optimized", ["-O"])):
        command = [sys.executable, *flags, "-m", "qualification.hcsn_n256_strict_metadata_20261119.controls"]
        cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        child = subprocess.run(command, cwd=root.parents[1], capture_output=True, timeout=30, check=False)
        wall = time.perf_counter() - start
        cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        (output / f"{mode}.stdout").write_bytes(child.stdout)
        (output / f"{mode}.stderr").write_bytes(child.stderr)
        rows.append({"mode": mode, "command": command, "exit_code": child.returncode,
                     "child_wall_seconds": wall,
                     "child_cpu_seconds": cpu_after.ru_utime + cpu_after.ru_stime - cpu_before.ru_utime - cpu_before.ru_stime})
    terminal = {"status": "PASS" if all(r["exit_code"] == 0 for r in rows) else "FAIL",
                "processes": rows, "model_calls": 0, "optimizer_steps": 0,
                "source_freeze_sha256": hashlib.sha256((root / "SOURCE_FREEZE.json").read_bytes()).hexdigest()}
    (output / "TERMINAL.json").write_text(json.dumps(terminal, sort_keys=True, indent=2) + "\n")
    print(json.dumps(terminal, sort_keys=True))
    if terminal["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
