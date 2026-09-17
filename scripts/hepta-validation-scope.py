#!/usr/bin/env python3
"""Classify one exact candidate into fast, impacted, or critical validation.

The classifier is intentionally conservative. It is the only source of
`not_applicable` decisions consumed by the blocking CI fan-in; a skipped job
without a matching classifier decision is therefore a failure, not a green
result inherited from another commit or workflow.

Only source families with an explicit impacted-check mapping are eligible for
the impacted profile. Workflow, action, script, app, tool, and other unmapped
surfaces fail closed to the critical profile until their validation ownership is
declared here. This keeps faster feedback from becoming a coverage hole.

Every Git diff status participates in classification. In particular, deleting a
critical authority/state/execution file must not disappear from the path set and
accidentally become an empty-diff fast validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable

SCHEMA = "hepta.validation-scope.v1"

JOBS = (
    "hepta-contract-gate",
    "bazel",
    "blob-size-policy",
    "cargo-deny",
    "codespell",
    "repo-checks",
    "rust-ci",
    "sdk",
)

ALWAYS_JOBS = {
    "hepta-contract-gate",
    "blob-size-policy",
    "codespell",
    "repo-checks",
}

CRITICAL_PREFIXES = (
    "codex-rs/hepta-authbus/",
    "codex-rs/hepta-control-plane/",
    "codex-rs/hepta-learning-ledger/",
    "codex-rs/hepta-memory/",
    "codex-rs/hepta-runtime/",
    "codex-rs/hepta-supervisor/",
    "codex-rs/state/",
    "codex-rs/core/",
    "codex-rs/app-server/",
    "tools/hepta-engineering-control/",
    "tools/hepta-os-evidence/",
    ".github/actions/hepta-synthetic-merge/",
)

CRITICAL_EXACT = {
    "docs/branch-policy.json",
    "codex-rs/Cargo.lock",
    "codex-rs/Cargo.toml",
    "rust-toolchain",
    "rust-toolchain.toml",
    "codex-rs/rust-toolchain",
    "codex-rs/rust-toolchain.toml",
    "scripts/hepta-validation-scope.py",
    "scripts/hepta-delivery-evidence.py",
    ".github/workflows/blocking-ci.yml",
    ".github/workflows/hepta-consolidated-source.yml",
}

DOC_PREFIXES = ("docs/",)
DOC_EXACT = {"README.md", "AGENTS.md", "SECURITY.md"}

BAZEL_MARKERS = (
    "BUILD",
    "BUILD.bazel",
    "MODULE.bazel",
    "MODULE.bazel.lock",
    ".bazelrc",
)

SDK_PREFIXES = ("sdk/", "codex-rs/codex-api/", "codex-rs/codex-client/")

# Deliberately no --diff-filter: deletions, type changes and every other committed
# status are validation inputs just like additions/modifications/renames.
DIFF_NAME_ONLY_ARGS = ("diff", "--name-only")


def _run_git(*args: str) -> str:
    return subprocess.check_output(("git", *args), text=True).strip()


def changed_paths(base: str, head: str) -> tuple[list[str], str | None]:
    """Return all changed paths, or fail closed when either commit is unavailable."""
    try:
        subprocess.run(
            ("git", "cat-file", "-e", f"{base}^{{commit}}"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ("git", "cat-file", "-e", f"{head}^{{commit}}"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return [], "base_or_head_unavailable"
    output = _run_git(*DIFF_NAME_ONLY_ARGS, base, head)
    paths = sorted({line for line in output.splitlines() if line})
    return paths, None


def _is_critical(path: str) -> bool:
    if path in CRITICAL_EXACT or path.startswith(CRITICAL_PREFIXES):
        return True
    if path.startswith("scripts/hepta-"):
        return True
    if path.startswith(".github/workflows/hepta-"):
        return True
    lowered = path.lower()
    return any(
        token in lowered
        for token in (
            "authority",
            "promotion",
            "release",
            "migration",
            "schema",
            "writer",
            "handoff",
            "recovery",
        )
    )


def _is_docs_only(path: str) -> bool:
    return path in DOC_EXACT or path.startswith(DOC_PREFIXES) or path.endswith(".md")


def _touches_bazel(path: str) -> bool:
    name = Path(path).name
    return name in BAZEL_MARKERS or path.startswith(".bazel") or "/bazel/" in path


def _touches_dependencies(path: str) -> bool:
    name = Path(path).name
    return name in {"Cargo.toml", "Cargo.lock", "deny.toml"}


def _touches_rust(path: str) -> bool:
    return path.startswith("codex-rs/") and (
        path.endswith(".rs")
        or Path(path).name in {"Cargo.toml", "Cargo.lock", "build.rs"}
    )


def _touches_sdk(path: str) -> bool:
    return path.startswith(SDK_PREFIXES)


def _has_explicit_impacted_mapping(path: str) -> bool:
    return (
        _is_docs_only(path)
        or _touches_bazel(path)
        or _touches_dependencies(path)
        or _touches_rust(path)
        or _touches_sdk(path)
    )


def classify(paths: Iterable[str], unavailable_reason: str | None = None) -> dict:
    paths = sorted(set(paths))
    critical_paths = [path for path in paths if _is_critical(path)]
    all_docs = bool(paths) and all(_is_docs_only(path) for path in paths)

    if unavailable_reason:
        profile = "critical"
        profile_reason = unavailable_reason
    elif critical_paths:
        profile = "critical"
        profile_reason = "critical_boundary_changed"
    elif all_docs:
        profile = "fast"
        profile_reason = "documentation_only"
    elif paths:
        profile = "impacted"
        profile_reason = "ordinary_impacted_change"
    else:
        profile = "fast"
        profile_reason = "empty_diff"

    if profile == "critical":
        required = {job: True for job in JOBS}
    else:
        required = {job: job in ALWAYS_JOBS for job in JOBS}
        if profile == "impacted":
            required["bazel"] = any(_touches_bazel(path) for path in paths)
            required["cargo-deny"] = any(_touches_dependencies(path) for path in paths)
            required["rust-ci"] = any(_touches_rust(path) for path in paths)
            required["sdk"] = any(_touches_sdk(path) for path in paths)

        # Unknown non-document source must never silently become N/A. Only
        # explicitly mapped families are eligible for impacted validation.
        if paths and not all(_has_explicit_impacted_mapping(path) for path in paths):
            profile = "critical"
            profile_reason = "unclassified_path_fail_closed"
            required = {job: True for job in JOBS}

    jobs = {}
    for job in JOBS:
        if required[job]:
            reason = (
                profile_reason
                if job not in ALWAYS_JOBS
                else "always_on_repository_contract"
            )
        else:
            reason = f"not_applicable_under_{profile}_profile"
        jobs[job] = {"required": required[job], "reason": reason}

    canonical_paths = "\n".join(paths).encode()
    return {
        "schema": SCHEMA,
        "profile": profile,
        "profile_reason": profile_reason,
        "paths": paths,
        "paths_sha256": hashlib.sha256(canonical_paths).hexdigest(),
        "critical_paths": critical_paths,
        "jobs": jobs,
    }


def _self_test() -> None:
    # Path discovery itself must not suppress deletions/type changes.
    assert DIFF_NAME_ONLY_ARGS == ("diff", "--name-only")

    docs = classify(["docs/DEVELOPMENT.md"])
    assert docs["profile"] == "fast"
    assert docs["jobs"]["rust-ci"]["required"] is False

    rust = classify(["codex-rs/hepta-intuition/src/lib.rs"])
    assert rust["profile"] == "impacted"
    assert rust["jobs"]["rust-ci"]["required"] is True
    assert rust["jobs"]["sdk"]["required"] is False

    critical = classify(["codex-rs/hepta-supervisor/src/lib.rs"])
    assert critical["profile"] == "critical"
    assert all(value["required"] for value in critical["jobs"].values())

    # The classifier is status-agnostic once Git supplies a path. This fixture
    # represents a deleted critical source file and must still require all jobs.
    deleted_critical = classify(["codex-rs/hepta-supervisor/src/deleted.rs"])
    assert deleted_critical["profile"] == "critical"
    assert all(value["required"] for value in deleted_critical["jobs"].values())

    workflow = classify([".github/workflows/ordinary.yml"])
    assert workflow["profile"] == "critical"
    assert workflow["profile_reason"] == "unclassified_path_fail_closed"

    script = classify(["scripts/ordinary-maintenance.py"])
    assert script["profile"] == "critical"

    unknown = classify(["mystery/new-format.bin"])
    assert unknown["profile"] == "critical"

    missing = classify([], "base_or_head_unavailable")
    assert missing["profile"] == "critical"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--paths-file")
    parser.add_argument("--output")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print(json.dumps({"status": "PASS_HEPTA_VALIDATION_SCOPE_SELF_TEST"}))
        return 0

    if args.paths_file:
        paths = [
            line.strip()
            for line in Path(args.paths_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        unavailable = None
    else:
        if not args.base or not args.head:
            parser.error("--base and --head are required without --paths-file")
        paths, unavailable = changed_paths(args.base, args.head)

    result = classify(paths, unavailable)
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"profile={result['profile']}\n")
            handle.write(f"scope_json={payload}\n")
            for job, applicability in result["jobs"].items():
                handle.write(
                    f"{job.replace('-', '_')}={'true' if applicability['required'] else 'false'}\n"
                )
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
