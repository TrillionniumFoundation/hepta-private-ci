#!/usr/bin/env python3
"""Hardened trusted entrypoint for learning.eval PR evidence reporting.

The default-branch workflow invokes this entrypoint rather than the lower-level
reporter directly. It adds deterministic guards that are intentionally awkward
to express in GitHub Actions YAML:

* one bounded allowlisted artifact inventory with a consistent status projection;
* strict JSON with no duplicate keys or non-finite constants;
* normalized producer job conclusions matched to ``needs.*.result`` semantics;
* at most one well-formed marker of each registered kind before replacement;
* a second current-PR scope check immediately before the body PATCH;
* byte identity for the producer qualification control plane;
* Draft/NO_GO preservation while this reporter is the active writer.

Candidate source and artifacts remain untrusted data. This script imports the
lower-level reporter from the trusted default-branch checkout only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType
from typing import Any
import urllib.error

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
MAX_SUMMARY_BYTES = 1024 * 1024
MAX_ARTIFACT_ENTRIES = 32
MAX_ARTIFACT_DEPTH = 4
MAX_PR_BODY_BYTES = 1024 * 1024
MAX_CONTROL_FILE_BYTES = 1024 * 1024
SUMMARY_NAMES = {
    "source": "qualification-summary.json",
    "exact": "exact-summary.json",
}
ARTIFACT_FILE_SETS = {
    "source": frozenset(("qualification-summary.json", "CURRENT_STATUS.run.json")),
    "exact": frozenset(("exact-summary.json",)),
}
TRUSTED_CONTROL_PLANE_PATHS = (
    "justfile",
    "scripts/just-shell.py",
    "codex-rs/.cargo/config.toml",
    "codex-rs/.config/nextest.toml",
    "codex-rs/hepta-intelligence-eval/fixtures/trusted-inprocess/Cargo.toml.in",
    "codex-rs/hepta-intelligence-eval/fixtures/trusted-inprocess/tests/operator_claim.rs",
    "scripts/hepta-learning-eval-aggregate.py",
    "scripts/hepta-learning-eval-api-surface.sh",
    "scripts/hepta-learning-eval-compat-fixture.py",
    "scripts/hepta-learning-eval-doc-contract.py",
    "scripts/hepta-learning-eval-exact-entry.py",
    "scripts/hepta-learning-eval-exact-summary.py",
    "scripts/hepta-learning-eval-exact.py",
    "scripts/hepta-learning-eval-faults.sh",
    "scripts/hepta-learning-eval-status.py",
    "scripts/hepta-learning-eval-target-host.py",
    "scripts/hepta-learning-eval-trusted-entry.py",
    "scripts/hepta-learning-eval-trusted-report.py",
    "scripts/hepta-learning-eval-pr-status.py",
    "scripts/hepta-learning-eval-local-verify.py",
    "scripts/hepta-nextest-require.py",
    "scripts/test_hepta_learning_eval_compat_fixture.py",
    "scripts/test_hepta_learning_eval_doc_contract.py",
    "scripts/test_hepta_learning_eval_evidence.py",
    "scripts/test_hepta_learning_eval_exact.py",
    "scripts/test_hepta_learning_eval_exact_entry.py",
    "scripts/test_hepta_learning_eval_trusted_report.py",
    "scripts/test_hepta_learning_eval_trusted_report_base.py",
    "scripts/test_hepta_learning_eval_trusted_entry.py",
    "scripts/test_hepta_learning_eval_local_verify.py",
    "scripts/test_hepta_learning_eval_status.py",
    "scripts/test_hepta_nextest_require.py",
    "scripts/test_hepta_rust_identifiers.py",
)
MARKERS = {
    "source": (
        "<!-- learning.eval source-qualification:start -->",
        "<!-- learning.eval source-qualification:end -->",
    ),
    "exact": (
        "<!-- learning.eval exact-qualification:start -->",
        "<!-- learning.eval exact-qualification:end -->",
    ),
}
LEGACY_SOURCE_MARKER = (
    "<!-- learning.eval qualification:start -->",
    "<!-- learning.eval qualification:end -->",
)
CONCLUSION_NORMALIZATION = {
    "success": "success",
    "failure": "failure",
    "cancelled": "cancelled",
    "skipped": "skipped",
    "neutral": "failure",
    "timed_out": "failure",
    "action_required": "failure",
    "stale": "failure",
    "startup_failure": "failure",
}
_REPORTER: ModuleType | None = None


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load trusted reporter dependency: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def reporter() -> ModuleType:
    global _REPORTER
    if _REPORTER is None:
        _REPORTER = load_module(
            "hepta_learning_eval_trusted_report",
            SCRIPT_DIR / "hepta-learning-eval-trusted-report.py",
        )
    return _REPORTER


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = child
    return value


def reject_nonfinite_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant is prohibited: {value}")


def artifact_files(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact root must be a real directory")
    resolved_root = root.resolve(strict=True)
    files: list[Path] = []
    entries = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        if depth > MAX_ARTIFACT_DEPTH:
            raise ValueError("artifact directory depth exceeds the allowed bound")
        with os.scandir(directory) as children:
            for child in children:
                entries += 1
                if entries > MAX_ARTIFACT_ENTRIES:
                    raise ValueError("artifact entry count exceeds the allowed bound")
                path = Path(child.path)
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise ValueError("artifact must not contain symlinks")
                if stat.S_ISDIR(metadata.st_mode):
                    stack.append((path, depth + 1))
                elif stat.S_ISREG(metadata.st_mode):
                    try:
                        path.resolve(strict=True).relative_to(resolved_root)
                    except ValueError as error:
                        raise ValueError(
                            "artifact file escapes its extraction root"
                        ) from error
                    files.append(path)
                else:
                    raise ValueError("artifact contains a non-regular entry")
    return files


def load_strict_json(path: Path) -> Any:
    size = path.stat().st_size
    if not 0 < size <= MAX_SUMMARY_BYTES:
        raise ValueError(
            f"artifact JSON size is outside the allowed bound: {path.name}"
        )
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_pairs,
        parse_constant=reject_nonfinite_constant,
    )


def validate_source_status_companion(
    summary: dict[str, Any], status: dict[str, Any]
) -> None:
    if status.get("schema") != "hepta.learning-eval.current-run-status.v1":
        raise ValueError("source artifact status companion has an unexpected schema")
    if status.get("module") != "learning.eval":
        raise ValueError("source artifact status companion has an unexpected module")
    for key in (
        "source",
        "evidenceSha256",
        "releasePosture",
        "authority",
        "claims",
        "jobs",
    ):
        if status.get(key) != summary.get(key):
            raise ValueError(
                f"source artifact status companion disagrees with summary field: {key}"
            )


def load_strict_summary(root: Path, expected_name: str) -> dict[str, Any]:
    if expected_name not in SUMMARY_NAMES.values():
        raise ValueError("unapproved evidence summary filename")
    marker = next(
        key for key, filename in SUMMARY_NAMES.items() if filename == expected_name
    )
    files = artifact_files(root)
    by_name: dict[str, Path] = {}
    for path in files:
        if path.name in by_name:
            raise ValueError(f"artifact contains duplicate basename: {path.name}")
        by_name[path.name] = path
    expected = ARTIFACT_FILE_SETS[marker]
    if set(by_name) != set(expected):
        names = sorted(str(path.relative_to(root)) for path in files)
        raise ValueError(
            f"artifact file inventory mismatch expected={sorted(expected)} actual={names}"
        )
    value = load_strict_json(by_name[expected_name])
    if not isinstance(value, dict):
        raise ValueError("evidence summary must be a JSON object")
    if marker == "source":
        status = load_strict_json(by_name["CURRENT_STATUS.run.json"])
        if not isinstance(status, dict):
            raise ValueError("source artifact status companion must be a JSON object")
        validate_source_status_companion(value, status)
    return value


def normalized_job_conclusions(
    value: dict[str, Any], run_attempt: str
) -> dict[str, str]:
    jobs = value.get("jobs")
    total = value.get("total_count")
    if (
        not isinstance(jobs, list)
        or not isinstance(total, int)
        or total != len(jobs)
        or total > 100
    ):
        raise ValueError("producer job inventory is incomplete or malformed")
    conclusions: dict[str, str] = {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("producer job entry is malformed")
        name = job.get("name")
        raw = job.get("conclusion")
        if not isinstance(name, str) or not name:
            raise ValueError("producer job lacks a terminal name")
        if not isinstance(raw, str) or raw not in CONCLUSION_NORMALIZATION:
            raise ValueError(
                f"producer job has an unapproved conclusion: {name}={raw!r}"
            )
        if name in conclusions:
            raise ValueError(f"duplicate producer job name: {name}")
        if str(job.get("run_attempt", run_attempt)) != run_attempt:
            raise ValueError(f"producer job belongs to another run attempt: {name}")
        conclusions[name] = CONCLUSION_NORMALIZATION[raw]
    return conclusions


def trusted_control_plane_text(path: str, *, root: Path = ROOT) -> str:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"invalid trusted control-plane path: {path}")
    candidate = root.joinpath(relative)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"trusted control-plane file is not regular: {path}")
    size = candidate.stat().st_size
    if not 0 < size <= MAX_CONTROL_FILE_BYTES:
        raise ValueError(f"trusted control-plane file size is invalid: {path}")
    return candidate.read_text(encoding="utf-8")


def validate_control_plane_text(
    candidate: str, path: str, *, root: Path = ROOT
) -> None:
    trusted = trusted_control_plane_text(path, root=root)
    if candidate.encode("utf-8") != trusted.encode("utf-8"):
        raise ValueError(
            f"candidate qualification control-plane file differs from trusted default branch: {path}"
        )


def validate_trusted_control_plane_identity(
    repository: str,
    source_sha: str,
    token: str,
    *,
    root: Path = ROOT,
) -> None:
    module = reporter()
    for path in TRUSTED_CONTROL_PLANE_PATHS:
        candidate = module.fetch_candidate_workflow(repository, path, source_sha, token)
        validate_control_plane_text(candidate, path, root=root)


def validate_complete_job_results(
    summary: dict[str, Any], marker: str, conclusions: dict[str, str]
) -> None:
    module = reporter()
    config = module.WORKFLOWS[marker]
    expected = {config["summary_job"], config["attestation_job"]}
    if marker == "source":
        expected.update(config["required_jobs"].values())
    else:
        expected.update(config["matrix_jobs"])
    if set(conclusions) != expected:
        raise ValueError(
            "producer job inventory mismatch "
            f"missing={sorted(expected - set(conclusions))} "
            f"extra={sorted(set(conclusions) - expected)}"
        )
    original = getattr(module, "_strict_original_validate_actual_job_results", None)
    if original is None:
        raise RuntimeError("trusted reporter original job validator is unavailable")
    original(summary, marker, conclusions)


def marker_counts(body: str, marker: str) -> tuple[int, int, int, int]:
    if marker not in MARKERS:
        raise ValueError("unapproved PR marker")
    if len(body.encode("utf-8")) > MAX_PR_BODY_BYTES:
        raise ValueError("pull request body exceeds the allowed bound")
    start, end = MARKERS[marker]
    modern_start = body.count(start)
    modern_end = body.count(end)
    legacy_start = legacy_end = 0
    if marker == "source":
        legacy_start = body.count(LEGACY_SOURCE_MARKER[0])
        legacy_end = body.count(LEGACY_SOURCE_MARKER[1])
    return modern_start, modern_end, legacy_start, legacy_end


def validate_marker_inventory(body: str, marker: str) -> None:
    modern_start, modern_end, legacy_start, legacy_end = marker_counts(body, marker)
    if modern_start != modern_end or modern_start > 1:
        raise ValueError("PR body has malformed or duplicate machine marker")
    if legacy_start != legacy_end or legacy_start > 1:
        raise ValueError("PR body has malformed or duplicate legacy marker")
    if modern_start and legacy_start:
        raise ValueError("PR body contains both modern and legacy source markers")
    if modern_start:
        start, end = MARKERS[marker]
        if body.find(start) > body.find(end):
            raise ValueError("PR body machine marker endpoints are reversed")
    if legacy_start:
        if body.find(LEGACY_SOURCE_MARKER[0]) > body.find(LEGACY_SOURCE_MARKER[1]):
            raise ValueError("PR body legacy marker endpoints are reversed")


def validate_all_marker_inventory(body: str) -> None:
    for selected in MARKERS:
        validate_marker_inventory(body, selected)


def replace_single_marker(body: str, block: str, marker: str) -> str:
    validate_all_marker_inventory(body)
    start, end = MARKERS[marker]
    if start in body:
        first = body.index(start)
        last = body.index(end, first) + len(end)
        suffix = "\n" if last < len(body) and body[last] == "\n" else ""
        next_body = body[:first] + block + body[last + len(suffix) :]
    elif marker == "source" and LEGACY_SOURCE_MARKER[0] in body:
        legacy_start, legacy_end = LEGACY_SOURCE_MARKER
        first = body.index(legacy_start)
        last = body.index(legacy_end, first) + len(legacy_end)
        suffix = "\n" if last < len(body) and body[last] == "\n" else ""
        next_body = body[:first] + block + body[last + len(suffix) :]
    else:
        separator = "" if not body else ("\n" if body.endswith("\n") else "\n\n")
        next_body = body + separator + block
    validate_all_marker_inventory(next_body)
    if next_body.count(start) != 1 or next_body.count(end) != 1:
        raise ValueError("PR marker replacement did not produce one canonical block")
    if marker == "source" and (
        LEGACY_SOURCE_MARKER[0] in next_body or LEGACY_SOURCE_MARKER[1] in next_body
    ):
        raise ValueError("legacy marker survived canonical replacement")
    return next_body


def validate_final_pr_scope(
    current: dict[str, Any],
    summary: dict[str, Any],
    marker: str,
    repository: str,
    pull_request: int,
    source_sha: str,
) -> None:
    module = reporter()
    module.validate_current_pull_request(current, repository, pull_request, source_sha)
    if current.get("number") != pull_request:
        raise ValueError("current pull request number mismatch")
    if current.get("draft") is not True:
        raise ValueError("NO_GO reporter refuses to update a non-draft pull request")
    base = current.get("base")
    if not isinstance(base, dict):
        raise ValueError("current pull request base identity is missing")
    base_repo = base.get("repo")
    if not isinstance(base_repo, dict) or base_repo.get("full_name") != repository:
        raise ValueError("current pull request base repository mismatch")
    if marker == "exact":
        if summary.get("baseCommit") != base.get("sha"):
            raise ValueError("exact summary base changed before PR marker update")
        if summary.get("syntheticMergeCommit") != current.get("merge_commit_sha"):
            raise ValueError(
                "exact summary synthetic merge changed before PR marker update"
            )


def update_current_pull_request_strict(
    summary: dict[str, Any],
    marker: str,
    repository: str,
    pull_request: int,
    source_sha: str,
    token: str,
    *,
    dry_run: bool = False,
) -> str:
    if pull_request < 1:
        raise ValueError("pull request number must be positive")
    if not token and not dry_run:
        raise ValueError("missing GitHub token")
    module = reporter()
    url = f"https://api.github.com/repos/{repository}/pulls/{pull_request}"
    current = module.PR_STATUS.request_json(url, token or "dry-run-token")
    validate_final_pr_scope(
        current, summary, marker, repository, pull_request, source_sha
    )
    body = current.get("body") or ""
    if not isinstance(body, str):
        raise ValueError("pull request body is not text")
    validate_all_marker_inventory(body)
    block = module.PR_STATUS.render(summary, marker)
    next_body = replace_single_marker(body, block, marker)
    if next_body != body and not dry_run:
        updated = module.PR_STATUS.request_json(
            url, token, method="PATCH", payload={"body": next_body}
        )
        validate_final_pr_scope(
            updated, summary, marker, repository, pull_request, source_sha
        )
        if updated.get("body") != next_body:
            raise ValueError("GitHub did not preserve the exact machine marker update")
    return next_body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument(
        "--summary-name", choices=tuple(SUMMARY_NAMES.values()), required=True
    )
    parser.add_argument("--marker", choices=tuple(SUMMARY_NAMES), required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if SUMMARY_NAMES[args.marker] != args.summary_name:
            raise ValueError("summary filename does not match the selected marker")
        summary = load_strict_summary(args.artifact_root.resolve(), args.summary_name)
        module = reporter()
        module.job_conclusions = normalized_job_conclusions
        if not hasattr(module, "_strict_original_validate_actual_job_results"):
            module._strict_original_validate_actual_job_results = (
                module.validate_actual_job_results
            )
        module.validate_actual_job_results = validate_complete_job_results
        module.validate_bound_summary(
            summary,
            args.marker,
            args.repository,
            args.run_id,
            args.run_attempt,
            args.source_sha,
        )
        token = os.environ.get(args.token_env, "")
        if not token:
            raise ValueError(f"missing token environment variable: {args.token_env}")
        module.validate_producer_run(
            summary,
            args.marker,
            args.repository,
            args.run_id,
            args.run_attempt,
            args.source_sha,
            args.pull_request,
            token,
        )
        validate_trusted_control_plane_identity(
            args.repository,
            args.source_sha,
            token,
        )
        body = update_current_pull_request_strict(
            summary,
            args.marker,
            args.repository,
            args.pull_request,
            args.source_sha,
            token,
            dry_run=args.dry_run,
        )
        print(body)
        return 0
    except (
        OSError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
