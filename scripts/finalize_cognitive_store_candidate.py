#!/usr/bin/env python3
"""Bind the final cognitive.store source map and remove ordinary bootstrap scripts.

Workflow files are managed through the repository connection, not by the
GitHub Actions token. This one-shot runner only mutates ordinary repository
files, verifies the exact candidate, commits the resulting map, and pushes it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/cognitive-store-full-closure-20260927"
MAP = ROOT / "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"
BOUNDARY = ROOT / "scripts/verify_cognitive_store_boundary.py"

TEMPORARY_PATHS = (
    Path("scripts/finalize_cognitive_store_candidate.py"),
    Path("scripts/cognitive_store_macos_preflight_marker.py"),
    Path("scripts/cognitive_store_qualification_manifest.py"),
)


def stage(message: str) -> None:
    print(f"FINALIZER_STAGE: {message}", flush=True)


def command_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run(*args: str, cwd: Path = ROOT, capture: bool = False) -> str:
    stage("run " + " ".join(args))
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        env=command_environment(),
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def git(*args: str, capture: bool = True) -> str:
    return run("git", *args, capture=capture)


def normalize_boundary_verifier() -> None:
    stage("normalize boundary paths for cross-platform verification")
    text = BOUNDARY.read_text(encoding="utf-8")
    replacements = {
        'host.get("sourcePath") == str(CANONICAL_HOST_PATH)':
            'host.get("sourcePath") == CANONICAL_HOST_PATH.as_posix()',
        '"canonicalProductFacadePath": str(CANONICAL_HOST_PATH),':
            '"canonicalProductFacadePath": CANONICAL_HOST_PATH.as_posix(),',
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            raise RuntimeError(f"boundary verifier marker is missing: {old}")
    BOUNDARY.write_text(text, encoding="utf-8")


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


def remove_temporary_scripts() -> None:
    stage("remove ordinary bootstrap scripts")
    for relative in TEMPORARY_PATHS:
        (ROOT / relative).unlink(missing_ok=True)


def clean_python_artifacts() -> None:
    stage("remove Python cache artifacts")
    for cache in sorted(ROOT.rglob("__pycache__"), reverse=True):
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
    for suffix in ("*.pyc", "*.pyo"):
        for compiled in ROOT.rglob(suffix):
            compiled.unlink(missing_ok=True)
    shutil.rmtree(ROOT / ".pytest_cache", ignore_errors=True)


def rebind_implementation_map() -> None:
    stage("rebind IMPLEMENTATION_MAP source objects")
    mapping: dict[str, Any] = json.loads(MAP.read_text(encoding="utf-8"))
    expected = [{
        "sourcePath": "codex-rs/hepta-agentd/src/production_writer_host.rs",
        "nativeSymbol": "AgentdProductionWriterHost",
        "state": "canonical_production_write_facade",
    }]
    if mapping.get("productCallers") != expected:
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


def commit_candidate() -> str:
    stage("commit exact source-object map")
    run("git", "config", "user.name", "Hepta Cognitive CI")
    run("git", "config", "user.email", "hepta-cognitive-ci@users.noreply.github.com")
    run("git", "diff", "--cached", "--check")
    if subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
        env=command_environment(),
    ).returncode != 0:
        run(
            "git",
            "commit",
            "-m",
            "docs(cognitive-store): bind final source objects and remove bootstrap scripts",
        )
    return git("rev-parse", "HEAD")


def require_clean(label: str) -> None:
    clean_python_artifacts()
    status = git("status", "--porcelain", "--untracked-files=all")
    if status:
        print(f"FINALIZER_DIRTY_{label}:\n{status}", flush=True)
        raise RuntimeError(f"candidate is not clean at {label}")


def verify_candidate(sha: str) -> None:
    stage("verify exact final candidate")
    tree = git("rev-parse", "HEAD^{tree}")

    # The exact-map verifier requires a pristine candidate; run it before any
    # other helper that could create a local cache or diagnostic file.
    require_clean("BEFORE_MAP")
    run(
        "python",
        "scripts/cognitive_store_map_verify.py",
        "--expected-sha",
        sha,
        "--expected-tree",
        tree,
    )
    run(
        "python",
        "scripts/check-rust-module-inventory.py",
        "codex-rs/hepta-cognitive-store/src",
    )
    run("python", "scripts/verify_cognitive_store_boundary.py")
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
    require_clean("AFTER_VERIFY")


def main() -> int:
    if git("branch", "--show-current") != BRANCH:
        raise RuntimeError("finalizer is running on the wrong branch")
    normalize_boundary_verifier()
    remove_temporary_scripts()
    clean_python_artifacts()
    rebind_implementation_map()
    sha = commit_candidate()
    verify_candidate(sha)
    stage("push exact candidate")
    run("git", "push", "origin", f"{sha}:refs/heads/{BRANCH}")
    print(json.dumps({"branch": BRANCH, "finalSha": sha}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
