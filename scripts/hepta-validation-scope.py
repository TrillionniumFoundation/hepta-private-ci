#!/usr/bin/env python3
"""Classify one source candidate into risk-proportional blocking validation.

The classifier is the only source of not-applicable decisions consumed by the
blocking fan-in. A skipped job without a same-candidate decision is a failure.
The scope binds the immutable source candidate; the delivery bundle separately
binds the integration artifact that GitHub Actions actually tested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable

SCHEMA = "hepta.validation-scope.v2"
POLICY_SOURCE = "scripts/hepta-validation-scope.py"

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
    "codex-rs/hepta-agentd/",
    "codex-rs/hepta-authbus/",
    "codex-rs/hepta-contracts/",
    "codex-rs/hepta-control-plane/",
    "codex-rs/hepta-learning-artifacts/",
    "codex-rs/hepta-learning-ledger/",
    "codex-rs/hepta-learning-plasticity/",
    "codex-rs/hepta-memory/",
    "codex-rs/hepta-runtime/",
    "codex-rs/hepta-supervisor/",
    "codex-rs/model-provider/",
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


def _run_git(*args: str) -> str:
    return subprocess.check_output(("git", *args), text=True).strip()


def _commit_tree(commit_sha: str) -> str:
    return _run_git("rev-parse", f"{commit_sha}^{{tree}}")


def changed_paths(base: str, source: str) -> tuple[list[str], str | None]:
    """Return source-candidate paths or a fail-closed reason."""
    try:
        subprocess.run(
            ("git", "cat-file", "-e", f"{base}^{{commit}}"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ("git", "cat-file", "-e", f"{source}^{{commit}}"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return [], "base_or_source_unavailable"
    output = _run_git("diff", "--name-only", "--diff-filter=ACMR", base, source)
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
            "execution",
        )
    )


def _is_docs_only(path: str) -> bool:
    return path in DOC_EXACT or path.startswith(DOC_PREFIXES) or path.endswith(".md")


def _touches_bazel(path: str) -> bool:
    name = Path(path).name
    return name in BAZEL_MARKERS or path.startswith(".bazel") or "/bazel/" in path


def _touches_dependencies(path: str) -> bool:
    return Path(path).name in {"Cargo.toml", "Cargo.lock", "deny.toml"}


def _touches_rust(path: str) -> bool:
    return path.startswith("codex-rs/") and (
        path.endswith(".rs")
        or Path(path).name in {"Cargo.toml", "Cargo.lock", "build.rs"}
    )


def _touches_sdk(path: str) -> bool:
    return path.startswith(SDK_PREFIXES)


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

        recognized = all(
            _is_docs_only(path)
            or _touches_bazel(path)
            or _touches_dependencies(path)
            or _touches_rust(path)
            or _touches_sdk(path)
            or path.startswith((".github/", "scripts/", "apps/", "tools/"))
            for path in paths
        )
        if paths and not recognized:
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
        jobs[job] = {
            "required": required[job],
            "reason": reason,
            "source": POLICY_SOURCE,
        }

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


def bind_source_identity(result: dict, base: str, source: str) -> dict:
    bound = dict(result)
    bound["source_candidate"] = {
        "commit_sha": source,
        "tree_sha": _commit_tree(source),
    }
    bound["base_commit_sha"] = base
    return bound


def _self_test() -> None:
    docs = classify(["docs/DEVELOPMENT.md"])
    assert docs["profile"] == "fast"
    assert docs["jobs"]["rust-ci"]["required"] is False
    assert docs["jobs"]["rust-ci"]["source"] == POLICY_SOURCE

    rust = classify(["codex-rs/hepta-intuition/src/lib.rs"])
    assert rust["profile"] == "impacted"
    assert rust["jobs"]["rust-ci"]["required"] is True
    assert rust["jobs"]["sdk"]["required"] is False

    critical = classify(["codex-rs/hepta-supervisor/src/lib.rs"])
    assert critical["profile"] == "critical"
    assert all(value["required"] for value in critical["jobs"].values())

    authority = classify(["codex-rs/model-provider/src/provider_effect.rs"])
    assert authority["profile"] == "critical"

    learning_artifact = classify(
        ["codex-rs/hepta-learning-artifacts/src/iteration_ledger.rs"]
    )
    assert learning_artifact["profile"] == "critical"

    unknown = classify(["mystery/new-format.bin"])
    assert unknown["profile"] == "critical"

    missing = classify([], "base_or_source_unavailable")
    assert missing["profile"] == "critical"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--source")
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
        if not args.base or not args.source:
            parser.error("--base and --source are required without --paths-file")
        paths, unavailable = changed_paths(args.base, args.source)

    result = classify(paths, unavailable)
    if args.base and args.source and unavailable is None:
        result = bind_source_identity(result, args.base, args.source)

    payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"profile={result['profile']}\n")
            handle.write(f"scope_json={payload}\n")
            for job, applicability in result["jobs"].items():
                handle.write(
                    f"{job.replace('-', '_')}="
                    f"{'true' if applicability['required'] else 'false'}\n"
                )
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
