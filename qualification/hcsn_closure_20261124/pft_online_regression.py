"""Explicit synthetic PFT regression gate with source and runtime evidence."""

import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
import unittest

import numpy as np


SUITES = (
    ("pft_statistics_tests", "LedgerTests", 4),
    ("pft_statistics_codec_tests", "CodecTests", 5),
    ("pft_online_peer_tests", "PeerTests", 4),
    ("pft_binary_peer_tests", "BinaryPeerTests", 4),
)
CORE = (
    "__init__.py", "pft_linear.py", "pft_statistics.py", "pft_statistics_codec.py",
    "pft_online_peer.py", "pft_binary_peer.py", "pft_online_regression.py",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-python", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.is_relative_to(root):
        raise ValueError("evidence output must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)

    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write(name, value):
        with (output / name).open("x") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")

    started = time.perf_counter()
    result = dict(schema="pft-online-regression-v1", suites=[], passed=False, error=None)
    try:
        if re.fullmatch(r"[0-9a-f]{40}", args.expected_head) is None or git("rev-parse", "HEAD") != args.expected_head:
            raise ValueError("checkout is not the exact requested head")
        if git("status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("source checkout is not clean")
        if platform.python_version() != args.expected_python or np.__version__ != "2.3.5":
            raise ValueError("runtime does not match its declared profile")
        if any(os.environ.get(k) != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")):
            raise ValueError("one BLAS thread is required")
        prefix = "qualification/hcsn_closure_20261124/"
        names = [prefix + n for n in CORE] + [prefix + n + ".py" for n, _, _ in SUITES]
        names += [".github/workflows/pft-online-regression.yml", prefix + "pft_online_regression/PROTOCOL.md"]
        if (root / "qualification/__init__.py").exists():
            names.append("qualification/__init__.py")
        git("ls-files", "--error-unmatch", "--", *names)
        source = {name: sha(root / name) for name in names}
        for name in names:
            target = output / "source" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, target)
        config = io.StringIO()
        with contextlib.redirect_stdout(config):
            np.show_config()
        write("FROZEN.json", dict(
            head=args.expected_head, source=source, python=sys.version, executable=sys.executable,
            executable_sha256=sha(Path(sys.executable)), numpy=np.__version__, sqlite=sqlite3.sqlite_version,
            platform=platform.platform(), numpy_configuration=config.getvalue(),
            expected_python=args.expected_python, format_base=os.environ.get("PFT_FORMAT_BASE"), github_actions=os.environ.get("GITHUB_ACTIONS") == "true",
            github={k:os.environ.get(k) for k in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_EVENT_NAME", "GITHUB_SHA")},
            threads={k:os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")},
            historical_science_budget_used=False))
        for name, class_name, expected_count in SUITES:
            module = importlib.import_module("qualification.hcsn_closure_20261124." + name)
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(getattr(module, class_name))
            if suite.countTestCases() != expected_count:
                raise ValueError("explicit suite count differs: " + name)
            records = getattr(module, "RECORDS", [])
            first = len(records)
            suite_started = time.perf_counter()
            with (output / (name + ".log")).open("x") as log:
                observed = unittest.TextTestRunner(stream=log, verbosity=2, failfast=True).run(suite)
            row = dict(module=name, expected=expected_count, tests=observed.testsRun,
                       failures=[(str(test), message) for test, message in observed.failures],
                       errors=[(str(test), message) for test, message in observed.errors],
                       skipped=[(str(test), reason) for test, reason in observed.skipped],
                       seconds=time.perf_counter()-suite_started, records=records[first:])
            row["passed"] = observed.wasSuccessful() and not observed.skipped and observed.testsRun == expected_count
            write(name + ".json", row)
            result["suites"].append({k:v for k,v in row.items() if k != "records"})
            print(json.dumps({k:row[k] for k in ("module", "tests", "passed", "seconds")}), flush=True)
            if not row["passed"]:
                break
        if source != {name: sha(root / name) for name in names} or git("rev-parse", "HEAD") != args.expected_head or git("status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("source checkout changed during regression")
        result["passed"] = len(result["suites"]) == len(SUITES) and all(row["passed"] for row in result["suites"])
    except Exception:
        result["error"] = traceback.format_exc()
    result["seconds"] = time.perf_counter() - started
    write("RESULT.json", result)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
