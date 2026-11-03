#!/usr/bin/env python3
"""Read-only exact-tree fleet qualification. Receipts are never written to source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

COMMANDS = (
    ("format", ("cargo", "fmt", "-p", "codex-hepta-fleet", "-p", "codex-hepta-supervisor", "--", "--check")),
    ("fleet", ("cargo", "test", "--locked", "-p", "codex-hepta-fleet", "--all-targets")),
    ("supervisor", ("cargo", "test", "--locked", "-p", "codex-hepta-supervisor", "--lib")),
    ("supervisord", ("cargo", "check", "--locked", "-p", "codex-hepta-supervisor", "--bin", "hepta-supervisord")),
    ("clippy", ("cargo", "clippy", "--locked", "-p", "codex-hepta-fleet", "-p", "codex-hepta-supervisor", "--all-targets", "--", "-D", "warnings")),
)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def run(name: str, command: tuple[str, ...], cwd: Path, output: Path) -> dict:
    path = output / (name + ".log")
    started = time.monotonic()
    with path.open("wb") as stream:
        try:
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            process = subprocess.run(command, cwd=cwd, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False)
            code = process.returncode
        except OSError as error:
            stream.write(str(error).encode("utf-8", errors="replace"))
            code = 127
    return {"name": name, "command": list(command), "cwd": str(cwd), "exit_code": code,
            "elapsed_seconds": time.monotonic() - started, "log": path.name, "sha256": digest(path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--lane", choices=("exact-source", "synthetic-merge"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output == root or root in output.parents:
        parser.error("qualification output must be outside the source checkout")
    for sha in (args.source, args.base):
        if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha):
            parser.error("source and base must be full immutable commit SHAs")
    head = git(root, "rev-parse", "HEAD")
    parents = git(root, "show", "-s", "--format=%P", "HEAD").split()
    if args.lane == "exact-source" and head != args.source:
        parser.error("exact-source checkout differs from requested commit")
    if args.lane == "synthetic-merge" and parents != [args.source, args.base]:
        parser.error("synthetic merge must have the exact ordered source/base parents")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        parser.error("source checkout is not clean before qualification")
    output.mkdir(parents=True, exist_ok=False)
    results = [run("python-regressions", (sys.executable, "scripts/test_runtime_fleet_status.py"), root, output),
               run("qualification-fault-regressions", (sys.executable, "scripts/test_runtime_fleet_qualify.py"), root, output)]
    results += [run(name, command, root / "codex-rs", output) for name, command in COMMANDS]
    results += [run("rustc-version", ("rustc", "-Vv"), root / "codex-rs", output),
                run("cargo-version", ("cargo", "-V"), root / "codex-rs", output),
                run("diff-check", ("git", "diff", "--check"), root, output)]
    dirty = git(root, "status", "--porcelain", "--untracked-files=all")
    receipt = {"schema_version": 1, "source_commit": args.source,
               "source_tree": git(root, "rev-parse", args.source + "^{tree}"),
               "base_commit": args.base, "base_tree": git(root, "rev-parse", args.base + "^{tree}"),
               "tested_commit": head, "tested_tree": git(root, "rev-parse", "HEAD^{tree}"),
               "lane": args.lane, "ordered_parents": parents,
               "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
               "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
               "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
               "runner_os": os.environ.get("RUNNER_OS"), "runner_image": os.environ.get("ImageOS"),
               "runner_image_version": os.environ.get("ImageVersion"),
               "qualification_script_sha256": digest(Path(__file__)),
               "commands": results, "clean_tree": not dirty, "remaining_changes": dirty,
               "passed": not dirty and all(result["exit_code"] == 0 for result in results),
               "product_execution_accepted": False, "production_release_approved": False}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    manifest = {path.name: digest(path) for path in sorted(output.iterdir()) if path.is_file()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt": str(output / "receipt.json"), "passed": receipt["passed"]}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
