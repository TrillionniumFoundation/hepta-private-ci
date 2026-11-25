#!/usr/bin/env python3
"""Run the six reproducible probes in a new, immutable output directory."""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=["full", "smoke"], default="full")
    args = parser.parse_args()
    source, output = Path(__file__).resolve().parent, args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
           "MKL_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    full = args.profile == "full"
    sizes, seeds = ("8,16,32,64", "0,1,2") if full else ("8", "0")
    nseeds = "3" if full else "1"
    started = time.perf_counter()
    write(output / "run_protocol.json", {
        "created_utc": datetime.now(timezone.utc).isoformat(), "profile": args.profile,
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob("*.py")},
        "python": platform.python_version(), "platform": platform.platform(),
        "widths": sizes, "base_seed_identifiability": 731, "seeds_other": seeds,
        "threads": 1, "scope": "exploratory controlled probes; not global scientific preregistration",
        "label_isolation": "PFT5 labels open only in evaluator after freeze; other probes use audited code separation"})
    common = ["--sizes", sizes, "--num-seeds", nseeds]
    commands = [
        ["identifiability.py", *common, "--output", str(output / "pft1.json")],
        ["distributed.py", *common, "--output", str(output / "pft2.json")],
        ["transport.py", *common, "--output", str(output / "pft2_transport.json")],
        ["structure_circuit.py", "--widths", *sizes.split(","), "--seeds", *seeds.split(","),
         "--steps", "180" if full else "30", "--output", str(output)],
        ["-c", "import sys; from pathlib import Path; from pft34_verify import verify; verify(Path(sys.argv[1]))", str(output)],
        ["cross_user.py", "suite", "--widths", sizes, "--seeds", seeds,
         "--root", str(output / "pft5_final_artifacts"), "--out", str(output / "pft5.json")],
        ["cross_user.py", "check-isolation", "--root", str(output / "pft5_isolation_artifacts"),
         "--out", str(output / "pft5_protocol_checks.json")],
        ["costs.py", "--widths", sizes, "--seeds", seeds,
         "--root", str(output / "pft6_final_artifacts"), "--out", str(output / "pft6.json")],
        ["verify_receipts.py", "--results", str(output), "--output", str(output / "receipt_audit.json")],
    ]
    receipts = []
    for index, argv in enumerate(commands):
        start = time.perf_counter()
        with (output / f"command_{index:02d}.log").open("x") as log:
            completed = subprocess.run([sys.executable, *argv], cwd=source, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
        receipt = {"index": index, "argv": argv, "exit_code": completed.returncode,
                   "wall_seconds": time.perf_counter() - start}
        write(output / f"command_{index:02d}.json", receipt)
        receipts.append(receipt)
        print(json.dumps(receipt), flush=True)
        if completed.returncode:
            raise SystemExit(completed.returncode)
    write(output / "run_complete.json", {"status": "COMPLETED", "commands": receipts,
                                         "wall_seconds": time.perf_counter() - started})


if __name__ == "__main__":
    main()
