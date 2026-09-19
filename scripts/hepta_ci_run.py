#!/usr/bin/env python3
"""Execute scoped commands through the existing exact-source command recorder.

Never interprets a package name, changed filename or plan field as shell code.
An empty selection is an explicit no-op, not an empty `cargo -p` invocation
(which would accidentally test the whole workspace).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from hepta_ci_scope import ScopeError, WorkspaceGraph, git

FLAGS = ("full_workspace", "engineering", "os_evidence", "ui_browser", "ui_native", "source_owner")
STAGES = ("source-owner", "ui", "engineering", "os", "format", "native")


def validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != "hepta.ci-test-plan.v1":
        raise ScopeError("invalid test-plan schema")
    for flag in FLAGS:
        if type(value.get(flag)) is not bool:
            raise ScopeError(f"invalid plan boolean: {flag}")
    packages = value.get("rust_packages")
    if (not isinstance(packages, list) or
            any(not isinstance(p, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", p) for p in packages) or
            packages != sorted(set(packages))):
        raise ScopeError("invalid or duplicate package names")
    for key in ("tested_commit", "tested_tree"):
        if not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value[key]):
            raise ScopeError(f"invalid {key}")
    if value["full_workspace"] and not packages:
        raise ScopeError("a full-workspace plan cannot have zero packages")
    return value


def check_cargo_graph(root: Path, metadata: dict[str, Any]) -> None:
    """Refuse a scope if static ownership disagrees with Cargo membership/edges.

    This is run only for native checks; document/Python-only edits do not need a
    Rust installation. Static extra dependency edges are conservative and allowed.
    """
    graph = WorkspaceGraph.load(root)
    try:
        rows = {row["id"]: row for row in metadata["packages"]}
        members = [rows[identity] for identity in metadata["workspace_members"]]
        actual = {Path(row["manifest_path"]).resolve().relative_to(root.resolve()).as_posix(): row
                  for row in members}
    except (KeyError, TypeError, ValueError) as exc:
        raise ScopeError("invalid cargo metadata") from exc
    if set(actual) != graph.members:
        raise ScopeError("static workspace membership differs from Cargo; scoped checks refused")
    for manifest, row in actual.items():
        if graph.packages[manifest].name != row["name"]:
            raise ScopeError(f"package identity differs from Cargo: {manifest}")
        for dependency in row.get("dependencies", []):
            path = dependency.get("path")
            if path:
                try:
                    target = (Path(path) / "Cargo.toml").resolve().relative_to(root.resolve()).as_posix()
                except ValueError as exc:
                    raise ScopeError("Cargo dependency escapes repository") from exc
                if manifest not in graph.consumers.get(target, set()):
                    raise ScopeError(f"missing local dependency edge in scope: {manifest} -> {target}")


def commands(root: Path, plan: dict[str, Any], stage: str) -> list[tuple[str, Path, list[str]]]:
    plan = validate_plan(plan)
    if stage not in STAGES:
        raise ScopeError(f"unknown stage: {stage}")
    packages = plan["rust_packages"]
    args = [item for name in packages for item in ("-p", name)]
    if stage == "source-owner":
        return [("source-owner", root, [sys.executable, "scripts/hepta-gap-closure.py", "verify"])] if plan["source_owner"] else []
    if stage == "engineering":
        return [("engineering-test", root, [sys.executable, "-m", "unittest", "discover", "-v", "-s", "tools/hepta-engineering-control", "-p", "test_*.py"])] if plan["engineering"] else []
    if stage == "os":
        return [("os-test", root / "tools/hepta-os-evidence", [sys.executable, "run_native_tests.py"])] if plan["os_evidence"] else []
    if stage == "ui":
        result = []
        for flag, app in (("ui_browser", "hepta-browser"), ("ui_native", "hepta-native")):
            if plan[flag]:
                tests = sorted((root / "apps" / app / "test").glob("*.js"))
                if not tests:
                    raise ScopeError(f"selected UI owner has no test files: {app}")
                result.append((app + "-test", root, ["node", "--test", *(str(p) for p in tests)]))
        return result
    if not packages:
        return []
    if stage == "format":
        return [("format", root / "codex-rs", ["cargo", "fmt", *args, "--", "--check"])]
    test_args = ["--workspace"] if plan["full_workspace"] else args
    result = [
        ("owner-test", root / "codex-rs", ["just", "test", "--locked", *test_args]),
        ("clippy", root / "codex-rs", ["cargo", "clippy", "--locked", *args, "--all-targets", "--", "-D", "warnings"]),
    ]
    if "codex-hepta-supervisor" in packages:
        result.insert(0, ("supervisor-default-library", root / "codex-rs", ["cargo", "check", "--locked", "-p", "codex-hepta-supervisor", "--lib", "--no-default-features"]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        plan = validate_plan(json.loads(args.plan.read_text(encoding="utf-8")))
        if git(root, "rev-parse", "HEAD").stdout.decode().strip() != plan["tested_commit"]:
            raise ScopeError("plan is for a different checked-out commit")
        if git(root, "rev-parse", "HEAD^{tree}").stdout.decode().strip() != plan["tested_tree"]:
            raise ScopeError("plan is for a different tree")
        if git(root, "diff", "--quiet", check=False).returncode or git(root, "diff", "--cached", "--quiet", check=False).returncode:
            raise ScopeError("tracked source changed after planning")
        selected = commands(root, plan, args.stage)
        if selected and args.stage in {"format", "native"}:
            raw = subprocess.check_output(["cargo", "metadata", "--no-deps", "--format-version=1", "--locked"], cwd=root / "codex-rs")
            check_cargo_graph(root, json.loads(raw))
        args.records.mkdir(parents=True, exist_ok=True)
        recorder = root / "scripts/hepta_ci_exec.py"
        if not selected:
            print(f"{args.stage}: no affected owner (not a test-success receipt)")
        for name, cwd, command in selected:
            subprocess.run([sys.executable, str(recorder), "--output", str(args.records.resolve() / (name + ".json")), "--", *command], cwd=cwd, check=True)
        return 0
    except (OSError, ScopeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"HEPTA_SCOPED_TEST_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
