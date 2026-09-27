#!/usr/bin/env python3
"""Finalize the cognitive.store remediation branch and remove bootstrap scaffolding.

The script runs once from the temporary finalizer workflow. It:
1. upgrades the canonical qualification workflow to run source-head and deterministic
   base-merge lanes on both pull-request and branch pushes;
2. removes temporary repair/finalizer files and the obsolete duplicate manifest builder;
3. rebinds IMPLEMENTATION_MAP source-object identities to the staged tree;
4. commits, verifies, and pushes one clean final candidate.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/cognitive-store-full-closure-20260927"
WORKFLOW = ROOT / ".github/workflows/cognitive-store-qualification.yml"
MAP = ROOT / "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"

TEMPORARY_PATHS = (
    Path(".github/workflows/cognitive-store-finalizer-windows.yml"),
    Path(".github/workflows/cognitive-store-lock-repair.yml"),
    Path(".github/workflows/cognitive-store-macos-preflight.yml"),
    Path("scripts/finalize_cognitive_store_candidate.py"),
    Path("scripts/cognitive_store_macos_preflight_marker.py"),
    Path("scripts/cognitive_store_qualification_manifest.py"),
)


def run(*args: str, cwd: Path = ROOT, capture: bool = False) -> str:
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def git(*args: str, capture: bool = True) -> str:
    return run("git", *args, capture=capture)


def patch_qualification_workflow() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    old_matrix = (
        "        lane: ${{ fromJSON(github.event_name == 'pull_request' "
        "&& '[\"source-head\",\"base-merge\"]' || '[\"source-head\"]') }}"
    )
    new_matrix = "        lane: ${{ fromJSON('[\"source-head\",\"base-merge\"]') }}"
    if old_matrix in text:
        text = text.replace(old_matrix, new_matrix, 1)
    elif new_matrix not in text:
        raise RuntimeError("qualification matrix marker is missing")

    old_base = """      - name: Resolve current pull-request base
        id: current-base
        if: github.event_name == 'pull_request'
        env:
          EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}
          BASE_REF: ${{ github.base_ref }}
        shell: bash
        run: |
          set -euo pipefail
          test -n "$EVENT_BASE_SHA"
          test -n "$BASE_REF"
          CURRENT_BASE="$(git rev-parse "refs/remotes/origin/${BASE_REF}^{commit}")"
          [[ "$CURRENT_BASE" =~ ^[0-9a-f]{40}$ ]]
          git cat-file -e "$CURRENT_BASE^{commit}"
          printf 'sha=%s\\n' "$CURRENT_BASE" >> "$GITHUB_OUTPUT"
          printf 'BASE_SHA=%s\\n' "$CURRENT_BASE" >> "$GITHUB_ENV"
"""
    new_base = """      - name: Resolve current base
        id: current-base
        env:
          BASE_REF: ${{ github.base_ref || 'main' }}
        shell: bash
        run: |
          set -euo pipefail
          test -n "$BASE_REF"
          git fetch --no-tags origin "$BASE_REF"
          CURRENT_BASE="$(git rev-parse "refs/remotes/origin/${BASE_REF}^{commit}")"
          [[ "$CURRENT_BASE" =~ ^[0-9a-f]{40}$ ]]
          git cat-file -e "$CURRENT_BASE^{commit}"
          printf 'sha=%s\\n' "$CURRENT_BASE" >> "$GITHUB_OUTPUT"
          printf 'BASE_SHA=%s\\n' "$CURRENT_BASE" >> "$GITHUB_ENV"
"""
    if old_base in text:
        text = text.replace(old_base, new_base, 1)
    elif new_base not in text:
        raise RuntimeError("qualification base-resolution block is missing")

    old_pr = "          pr-number: ${{ github.event.pull_request.number }}"
    new_pr = "          pr-number: ${{ github.event.pull_request.number || 0 }}"
    if old_pr in text:
        text = text.replace(old_pr, new_pr, 1)
    elif new_pr not in text:
        raise RuntimeError("qualification synthetic-merge PR marker is missing")

    WORKFLOW.write_text(text, encoding="utf-8")


def normalize_path(value: Any) -> str | None:
    if isinstance(value, str):
        path = value
    elif isinstance(value, dict):
        path = value.get("path", value.get("sourcePath"))
    else:
        return None
    if not isinstance(path, str) or not path:
        return None
    if ".rs::" in path:
        path = path.split(".rs::", 1)[0] + ".rs"
    return path.replace("\\", "/")


def mapped_paths(mapping: dict[str, Any]) -> set[str]:
    paths: set[str] = set(mapping.get("resolvedRoots", []))
    paths.add(mapping["technicalGuide"])
    for caller in mapping.get("productCallers", []):
        path = normalize_path(caller)
        if path:
            paths.add(path)
    for operation in mapping.get("operations", []):
        path = normalize_path(operation.get("sourcePath"))
        if path:
            paths.add(path)
        for key in ("tests", "delegatedCallees"):
            for entry in operation.get(key, []):
                path = normalize_path(entry)
                if path:
                    paths.add(path)
    return paths


def delete_temporary_paths() -> None:
    for relative in TEMPORARY_PATHS:
        (ROOT / relative).unlink(missing_ok=True)


def rebind_implementation_map() -> None:
    mapping: dict[str, Any] = json.loads(MAP.read_text(encoding="utf-8"))

    callers = mapping.get("productCallers", [])
    expected = [{
        "sourcePath": "codex-rs/hepta-agentd/src/production_writer_host.rs",
        "nativeSymbol": "AgentdProductionWriterHost",
        "state": "canonical_production_write_facade",
    }]
    if callers != expected:
        raise RuntimeError("implementation map no longer has the unique Agentd writer facade")

    mapping["sourceObjects"] = []
    MAP.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    run("git", "add", "-A")

    paths = mapped_paths(mapping)
    missing = [path for path in sorted(paths) if not (ROOT / path).exists()]
    if missing:
        raise RuntimeError("mapped paths are missing: " + ", ".join(missing))

    provisional_tree = git("write-tree")
    mapping["sourceObjects"] = [
        {"path": path, "object": git("rev-parse", f"{provisional_tree}:{path}")}
        for path in sorted(paths)
    ]
    MAP.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    run("git", "add", "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json")


def commit_and_verify() -> str:
    run("git", "config", "user.name", "Hepta Cognitive CI")
    run("git", "config", "user.email", "hepta-cognitive-ci@users.noreply.github.com")
    run("git", "diff", "--cached", "--check")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
        run(
            "git",
            "commit",
            "-m",
            "ci(cognitive-store): remove scaffolding and require dual-lane evidence",
        )

    sha = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    run(
        "python",
        "scripts/check-rust-module-inventory.py",
        "codex-rs/hepta-cognitive-store/src",
    )
    run("python", "scripts/verify_cognitive_store_boundary.py")
    run(
        "python",
        "scripts/cognitive_store_map_verify.py",
        "--expected-sha",
        sha,
        "--expected-tree",
        tree,
    )
    run("python", "tools/cognitive-store-host-bootstrap/test_bootstrap.py")
    run(
        "cargo",
        "metadata",
        "--locked",
        "--format-version",
        "1",
        "--no-deps",
        cwd=ROOT / "codex-rs",
    )
    run("git", "diff", "--check")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("final candidate is not clean")
    return sha


def main() -> int:
    if git("branch", "--show-current") != BRANCH:
        raise RuntimeError("finalizer is running on the wrong branch")
    patch_qualification_workflow()
    delete_temporary_paths()
    rebind_implementation_map()
    sha = commit_and_verify()
    run("git", "push", "origin", f"{sha}:refs/heads/{BRANCH}")
    print(json.dumps({"branch": BRANCH, "finalSha": sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
