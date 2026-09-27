#!/usr/bin/env python3
"""Read-only, commit-bound runtime.fleet qualification; never repairs source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def digest(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def qualify(root: Path, output: Path, kind: str, source: str, base: str) -> int:
    root = root.resolve()
    output = output.resolve()
    if output == root or root in output.parents:
        raise ValueError("evidence must be outside the qualified source tree")
    output.mkdir(parents=True, exist_ok=True)
    tested = git(root, "rev-parse", "HEAD")
    source = git(root, "rev-parse", f"{source}^{{commit}}")
    base = git(root, "rev-parse", f"{base}^{{commit}}")
    if kind == "exact-source" and tested != source:
        raise ValueError("exact-source checkout does not match the pinned source")
    if kind == "synthetic-merge":
        parents = git(root, "show", "-s", "--format=%P", tested).split()
        if parents != [base, source]:
            raise ValueError("synthetic merge must have the pinned base/source parents")
    receipt = {
        "schema": "hepta.runtime-fleet.qualification.v2",
        "kind": kind,
        "source_commit": source,
        "source_tree": git(root, "rev-parse", f"{source}^{{tree}}"),
        "base_commit": base,
        "base_tree": git(root, "rev-parse", f"{base}^{{tree}}"),
        "tested_commit": tested,
        "tested_tree": git(root, "rev-parse", "HEAD^{tree}"),
        "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner_image": os.environ.get("ImageOS"),
        "runner_image_version": os.environ.get("ImageVersion"),
        "platform": platform.platform(),
        "commands": [],
        "outcome": "incomplete",
        "passed": False,
        "product_deployment": False,
        "independent_acceptance": False,
    }
    receipt_path = output / "receipt.json"

    def save() -> None:
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    save()
    archive = output / "runtime-fleet-source.tgz"
    # git archive exports tracked bytes, never post-test or generated working files.
    subprocess.run(
        ["git", "archive", "--format=tar.gz", f"--output={archive}", tested,
         "codex-rs/hepta-fleet", "codex-rs/hepta-supervisor", "codex-rs/Cargo.toml",
         "codex-rs/Cargo.lock", "docs/modules/runtime.fleet",
         ".github/workflows/runtime-fleet-focused.yml", "scripts/runtime_fleet_qualify.py"],
        cwd=root, check=True,
    )
    receipt["source_archive_sha256"] = digest(archive)
    commands = [
        ("rustc", root, ["rustc", "-Vv"]),
        ("cargo", root, ["cargo", "-V"]),
        ("diff-check", root, ["git", "diff", "--check"]),
        ("fmt", root / "codex-rs", ["cargo", "fmt", "--all", "--", "--check"]),
        ("fleet-test", root / "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-fleet", "--all-targets"]),
        ("supervisor-test", root / "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-supervisor", "--all-targets"]),
        ("supervisor-product-check", root / "codex-rs", ["cargo", "check", "--locked", "-p", "codex-hepta-supervisor", "--bin", "hepta-supervisord"]),
        ("fleet-clippy", root / "codex-rs", ["cargo", "clippy", "--locked", "--no-deps", "-p", "codex-hepta-fleet", "--all-targets", "--all-features", "--", "-D", "warnings"]),
        ("supervisor-clippy", root / "codex-rs", ["cargo", "clippy", "--locked", "--no-deps", "-p", "codex-hepta-supervisor", "--all-targets", "--all-features", "--", "-D", "warnings"]),
        ("clean-tree", root, ["git", "status", "--porcelain=v1", "--untracked-files=all"]),
    ]
    invalid = False
    failed = False
    for name, cwd, argv in commands:
        log = output / f"{name}.log"
        start = time.monotonic()
        print(f"::group::{name}: {' '.join(argv)}", flush=True)
        try:
            with log.open("wb") as stream:
                result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            with log.open("ab") as stream:
                stream.write((f"\ninfrastructure_invalid: {exc}\n").encode())
            code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 127
            invalid = True
        # git status is zero even for dirty trees; classify that explicitly.
        if name == "clean-tree" and log.read_bytes().strip():
            code = code or 1
        failed |= code != 0
        record = {
            "name": name, "argv": argv, "cwd": str(cwd.relative_to(root)),
            "exit_code": code, "duration_seconds": round(time.monotonic() - start, 3),
            "log": log.name, "log_sha256": digest(log),
        }
        receipt["commands"].append(record)
        save()
        print(log.read_text(errors="replace"), end="", flush=True)
        print(f"::endgroup::\n{name}: exit={code}", flush=True)
    receipt["outcome"] = "infrastructure_invalid" if invalid else "failed" if failed else "passed"
    receipt["passed"] = not failed
    save()
    (output / "receipt.sha256").write_text(f"{digest(receipt_path)}  receipt.json\n")
    print(json.dumps(receipt, indent=2, sort_keys=True), flush=True)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=("exact-source", "synthetic-merge"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    return qualify(root, options.output, options.kind, options.source, options.base)


if __name__ == "__main__":
    sys.exit(main())
