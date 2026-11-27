#!/usr/bin/env python3
"""Run every B4 test module from one clean, immutable checkout.

Each module has its own Python process and durable log/result. This is a
qualification runner; it does not change the repository's gates or tests.
"""

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    def git(*argv):
        return subprocess.check_output(
            ["git", *argv], cwd=checkout, text=True
        ).strip()

    if git("status", "--porcelain=v1"):
        raise SystemExit("qualification checkout must be clean")
    source = {"commit": git("rev-parse", "HEAD"), "tree": git("write-tree")}
    test_directory = checkout / "qa/b4-no-bypass"
    modules = [p.stem for p in sorted(test_directory.glob("test_*.py"))]
    if not modules:
        raise SystemExit("empty B4 module inventory")
    started = time.time()
    inventory = {
        "source": source,
        "modules": modules,
        "workers": args.workers,
        "test_directory": str(test_directory),
        "python": sys.version,
    }
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")

    def run_module(module):
        command = [sys.executable, "-B", "-m", "unittest", module, "-v"]
        log_path = output / (module + ".log")
        module_start = time.time()
        with log_path.open("wb") as log:
            result = subprocess.run(
                command, cwd=test_directory, stdout=log, stderr=subprocess.STDOUT
            )
        raw = log_path.read_bytes()
        matches = re.findall(rb"Ran (\d+) tests? in", raw)
        tests_run = int(matches[-1]) if matches else None
        skipped = len(re.findall(rb" \.\.\. skipped ", raw))
        receipt = {
            "module": module,
            "source": source,
            "command": command,
            "exit_code": result.returncode,
            "tests_run": tests_run,
            "skipped": skipped,
            "elapsed_seconds": time.time() - module_start,
            "log_bytes": len(raw),
            "log_sha256": hashlib.sha256(raw).hexdigest(),
        }
        (output / (module + ".result.json")).write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        print(json.dumps(receipt), flush=True)
        return receipt

    receipts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for receipt in pool.map(run_module, modules):
            receipts.append(receipt)

    unchanged = not git("status", "--porcelain=v1") and source == {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("write-tree"),
    }
    failed = [
        r["module"] for r in receipts
        if r["exit_code"] != 0 or r["tests_run"] is None
    ]
    summary = {
        "source": source,
        "status": "passed" if not failed and unchanged else "failed",
        "modules_expected": len(modules),
        "modules_completed": len(receipts),
        "tests_run": sum(r["tests_run"] or 0 for r in receipts),
        "skipped": sum(r["skipped"] for r in receipts),
        "failed_modules": failed,
        "checkout_unchanged": unchanged,
        "elapsed_seconds": time.time() - started,
        "scope": "All B4 modules, each in a separate process; no native Rust qualification inferred.",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
