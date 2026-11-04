#!/usr/bin/env python3
"""Generate only the original failing YAML files with the repository formatter."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qualification/fleet-private-registration-current"))
from common import identity, require, snapshot

TARGETS = (
    ".github/workflows/complete-source-generation.yml",
    ".github/workflows/fleet-private-registration-qualification.yml",
)
HARNESS = ".github/workflows/complete-source-prettier-qualification.yml"

def main():
    require(__debug__, "optimized Python is not accepted")
    output = Path(os.environ["RUNNER_TEMP"]) / "original-prettier-qualification"
    output.mkdir(exist_ok=False)
    before = snapshot(verify_index=True)
    head = subprocess.check_output(["git", "--no-replace-objects", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(head == os.environ["GITHUB_SHA"], "unexpected source commit")
    receipt = {"source_commit": head, "status": "failed", "commands": [], "targets": {}, "run_id": os.environ["GITHUB_RUN_ID"]}
    (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")

    def run(name, argv):
        started = time.monotonic()
        result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / (name + ".log")).write_bytes(result.stdout)
        row = {"name": name, "argv": argv, "exit_code": result.returncode, "seconds": time.monotonic() - started, **identity(result.stdout)}
        receipt["commands"].append(row)
        print(json.dumps(row), flush=True)
        print(result.stdout.decode("utf-8", errors="replace"), flush=True)
        require(result.returncode == 0, "original command failed: " + name)

    try:
        for path in TARGETS:
            (output / (Path(path).name + ".original")).write_bytes((ROOT / path).read_bytes())
        run("node-version", ["node", "--version"])
        run("pnpm-version", ["pnpm", "--version"])
        run("frozen-install", ["pnpm", "install", "--frozen-lockfile"])
        run("prettier-version", ["pnpm", "exec", "prettier", "--version"])
        run("actual-formatter", ["pnpm", "exec", "prettier", "--write", *TARGETS, HARNESS])
        run("original-format-check", ["pnpm", "run", "format"])
        run("formatter-debug-check", ["pnpm", "exec", "prettier", "--debug-check", *TARGETS])
        after = snapshot()
        changes = sorted(path for path in before if before[path] != after.get(path))
        require(set(before) == set(after), "tracked source inventory changed")
        require(set(changes) <= set(TARGETS) | {HARNESS}, "formatter changed an unreviewed input")
        require(before["pnpm-lock.yaml"] == after["pnpm-lock.yaml"], "frozen pnpm lock changed")
        receipt["changed_paths"] = changes
        receipt["other_inputs_unchanged"] = True
        for path in TARGETS:
            raw = (ROOT / path).read_bytes()
            row = {"path": path, **identity(raw)}
            receipt["targets"][path] = {"before": before[path], "after": row}
            (output / Path(path).name).write_bytes(raw)
            print("ORIGINAL_PRETTIER_BEGIN=" + json.dumps(row), flush=True)
            for offset in range(0, len(raw), 32768):
                part = raw[offset:offset + 32768]
                print("ORIGINAL_PRETTIER_PART=" + json.dumps({"path": path, "offset": offset, "bytes": len(part), "base64": base64.b64encode(part).decode("ascii")}), flush=True)
            print("ORIGINAL_PRETTIER_END=" + json.dumps({"path": path}), flush=True)
        receipt["status"] = "generated-and-original-format-check-passed"
    finally:
        after = snapshot()
        (output / "source-after.json").write_text(json.dumps(after, indent=2) + "\n")
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("ORIGINAL_PRETTIER_RESULT=" + json.dumps(receipt), flush=True)

if __name__ == "__main__":
    main()
