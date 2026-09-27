#!/usr/bin/env python3
"""Bind the final cognitive.store source map and remove temporary convergence helpers.

Workflow files are managed through the repository connection, not by the
GitHub Actions token. This one-shot runner mutates ordinary repository files,
verifies the exact candidate, commits the resulting map, and pushes it.
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
QUALIFICATION_WORKFLOW = ROOT / ".github/workflows/cognitive-store-qualification.yml"
TECHNICAL = ROOT / "docs/modules/cognitive.store/TECHNICAL.md"
BOOTSTRAP_RUNBOOK = ROOT / "docs/modules/cognitive.store/BOOTSTRAP_RUNBOOK.md"

TEMPORARY_PATHS = (
    Path("scripts/finalize_cognitive_store_candidate.py"),
    Path("scripts/cognitive_store_architecture.py"),
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


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"{label} marker is missing in {path.relative_to(ROOT)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def harden_qualification_workflow() -> None:
    stage("set workflow-wide deny-all token permissions")
    replace_once(
        QUALIFICATION_WORKFLOW,
        "  workflow_dispatch:\n\nconcurrency:\n",
        "  workflow_dispatch:\n\npermissions: {}\n\nconcurrency:\n",
        "qualification workflow permissions",
    )


def synchronize_security_and_bootstrap_truth() -> None:
    stage("synchronize threat ownership and bootstrap claim boundaries")
    replace_once(
        TECHNICAL,
        "Owned threat entries:\n\nNone.\n",
        "Owned threat entries:\n\n"
        "- [cognitive.store threat model and test map](THREAT_MODEL.md) is the module-owned threat register.\n"
        "- Every listed threat remains a fail-closed source and qualification obligation; source references never substitute for exact-candidate or target-host evidence.\n",
        "technical threat ownership",
    )

    marker = (
        "The canonical schemas and signing-byte functions are in "
        "`codex_hepta_cognitive_store::bootstrap`.\n\n"
        "## Initial admission"
    )
    replacement = (
        "The canonical schemas and signing-byte functions are in "
        "`codex_hepta_cognitive_store::bootstrap`.\n\n"
        "The signed `sourceCommit` and `sourceTree` fields bind the host-selected deployment candidate inside the manifest. They are not executable-byte attestation by themselves. Before invoking Agentd, the trusted host must compare them with an independently accepted release or artifact manifest; an ordinary local build remains unbound.\n\n"
        "Across process restart, the latest accepted authority-state revision and semantic digest must be retained outside the Agent and fleet rollback domains. Agentd enforces exact monotonicity from the state observed by the live process; the trusted host must reject any bootstrap behind its retained frontier before invoking Agentd.\n\n"
        "`tools/cognitive-store-host-bootstrap` is an operator-side HMAC ceremony ledger for retaining monotone current-cut, canary, rollback and indeterminate-state evidence. It does not issue the Ed25519 production authority, does not contain the raw fencing token, and is not a substitute for the four Agentd bootstrap inputs above.\n\n"
        "## Initial admission"
    )
    replace_once(
        BOOTSTRAP_RUNBOOK,
        marker,
        replacement,
        "bootstrap source/frontier claim boundary",
    )


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
    stage("remove temporary convergence helpers")
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
            "fix(cognitive-store): finalize permissions, threat ownership, and bootstrap truth",
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
    harden_qualification_workflow()
    synchronize_security_and_bootstrap_truth()
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
