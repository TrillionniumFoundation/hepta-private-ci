"""Dedicated bounded split-mesh evidence; never re-label the common manifest."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import numpy as np
import scipy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((Path(__file__).parent / "MANIFEST.json").read_text())
    def identities():
        return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in manifest["sources"]}
    before = identities()
    (args.output / "SOURCE_BEFORE.json").write_text(json.dumps(before, indent=2)+"\n")
    if before != manifest["sources"]:
        raise RuntimeError("split source differs from its dedicated manifest")
    command = [sys.executable, "-B", "-m", "unittest", "qualification.hcsn_split_mesh.test_split", "-v"]
    start = time.perf_counter()
    with (args.output / "TEST.stdout").open("wb") as stdout, (args.output / "TEST.stderr").open("wb") as stderr:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=180)
    after = identities()
    (args.output / "SOURCE_AFTER.json").write_text(json.dumps(after, indent=2)+"\n")
    stdout, stderr = [(args.output / name).read_text() for name in ("TEST.stdout", "TEST.stderr")]
    if completed.returncode or re.findall(r"Ran (\d+) tests", stderr) != ["4"] or "skipped=" in stderr or before != after:
        raise RuntimeError("four unchanged-source split checks must pass without skips")
    line = next(line for line in stdout.splitlines() if line.startswith("SPLIT_EVIDENCE "))
    report = dict(schema="hcsn-split-exploratory-evidence-v1", status="PASS_DISCRETE_CHECKS_ONLY",
        source=before, tests_passed=4, skips=0, elapsed_seconds=time.perf_counter()-start,
        python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
        evidence=json.loads(line.split(" ", 1)[1]))
    (args.output / "RESULT.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(report, allow_nan=False))


if __name__ == "__main__":
    main()
