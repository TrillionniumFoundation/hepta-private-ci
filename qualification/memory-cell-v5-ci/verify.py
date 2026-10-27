"""Verify the actual repository checks, format the fix, and preserve research bytes."""

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time


ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    "scripts/hepta-docs.py",
    "scripts/test_hepta_workflow_references.py",
    "qualification/memory-cell-v5-ci/verify.py",
    "qualification/memory-cell-v5-ci/probe_dependency.py",
)


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def syntax(path):
    value = ast.dump(ast.parse(path.read_bytes()), include_attributes=False)
    return hashlib.sha256(value.encode()).hexdigest()


def frozen_snapshot():
    base = ROOT / "qualification/memory-cell-v5"
    return {path.relative_to(base).as_posix(): identity(path) for path in sorted(base.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


def main():
    output = ROOT / "memory-ci-output"
    output.mkdir(exist_ok=False)
    before = {name: identity(ROOT / name) for name in SOURCES}
    trees = {name: syntax(ROOT / name) for name in SOURCES}
    frozen = frozen_snapshot()
    commands = [
        ([sys.executable, "-B", "scripts/test_hepta_workflow_references.py", "-v"], ROOT),
        ([sys.executable, "-B", "-m", "unittest", "test_hepta_cleanup_consumers.CleanupConsumerTests.test_exact_workflow_reference_must_exist",
          "test_hepta_cleanup_consumers.CleanupConsumerTests.test_exact_workflow_reference_accepts_existing_file", "-v"], ROOT / "scripts"),
        ([sys.executable, "scripts/hepta-docs.py", "verify", "--profile", "development"], ROOT),
        (["just", "fmt", "--base", "332d8156d081e22405450dd607023689f68f03e1"], ROOT / "codex-rs"),
        (["uv", "run", "--frozen", "--project", "scripts", "ruff", "format", *SOURCES[2:]], ROOT),
        (["uv", "run", "--frozen", "--project", "scripts", "ruff", "format", "--check", *SOURCES], ROOT),
        (["uv", "run", "--frozen", "--project", "scripts", "ruff", "check", *SOURCES], ROOT),
    ]
    records = []
    for command, directory in commands:
        started = time.perf_counter()
        process = subprocess.run(command, cwd=directory, capture_output=True, text=True)
        records.append({"command": command, "cwd": str(directory), "exit_code": process.returncode,
                        "wall_seconds": time.perf_counter() - started, "stdout": process.stdout, "stderr": process.stderr})
    after = {name: identity(ROOT / name) for name in SOURCES}
    ast_equal = all(trees[name] == syntax(ROOT / name) for name in SOURCES)
    preserved = frozen_snapshot() == frozen
    changed = subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT, text=True).splitlines()
    scope_ok = set(changed) <= set(SOURCES)
    report = {"schema": "hepta.memory.v5.ci-fix-verification.v1", "commit": os.environ["GITHUB_SHA"],
              "commands": records, "before": before, "after": after, "ast_sha256": trees,
              "all_ast_equal": ast_equal, "all_v5_files_before": frozen,
              "all_v5_files_unchanged": preserved, "changed_paths": changed,
              "changes_limited_to_formatter_sources": scope_ok, "tests_before_format_only": True,
              "passed": ast_equal and preserved and scope_ok and all(row["exit_code"] == 0 for row in records)}
    (output / "VERIFY.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    with tarfile.open(output / "formatted-ci-source.tar.gz", "w:gz") as archive:
        for name in SOURCES:
            archive.add(ROOT / name, arcname=name, recursive=False)
    print(json.dumps({key: report[key] for key in ("commit", "passed", "all_ast_equal", "all_v5_files_unchanged", "changed_paths")}))
    for row in records:
        if row["exit_code"]:
            print(json.dumps(row))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
