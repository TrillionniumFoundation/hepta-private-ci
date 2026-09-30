#!/usr/bin/env python3
"""Derive one non-mixable channel.matrix readiness manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import channel_matrix_pair_acceptance_v2 as paired_v2

ROOT = SCRIPT_DIRECTORY.parent
WORKFLOW_PATH = ".github/workflows/channel-matrix-preserve-unknown.yml"
IMPLEMENTATION_MAP = ROOT / "docs/modules/channel.matrix/IMPLEMENTATION_MAP.json"
QUALIFICATION_PROFILE = ROOT / "docs/modules/channel.matrix/PRODUCTION_QUALIFICATION_PROFILE.json"
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    def unique(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError(f"invalid evidence object: {path}")
    row = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(row, dict):
        raise ValueError(f"JSON object required: {path}")
    return row


def optional_sha(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not SHA1.fullmatch(value):
        raise ValueError("optional commit identity is not exact lowercase 40-hex")
    return value


def tracked_paths(*pathspecs: str) -> list[str]:
    raw = git("ls-files", "-z", "--", *pathspecs).stdout
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def aggregate_tracked(domain: bytes, *pathspecs: str) -> str:
    rows = []
    for relative in tracked_paths(*pathspecs):
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"non-regular tracked aggregate input: {relative}")
        rows.append({"path": relative, "sha256": digest(path), "bytes": path.stat().st_size})
    if not rows:
        raise ValueError(f"empty tracked aggregate: {pathspecs}")
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(domain + b"\0" + encoded).hexdigest()


def validate_provenance(
    directory: Path,
    lane: dict[str, Any],
    stage: str,
    expected_run: str | None,
    expected_attempt: str | None,
) -> dict[str, Any]:
    path = directory / "source-provenance.json"
    row = read_object(path)
    source = lane["source"]
    execution = row.get("execution")
    claims = row.get("claims")
    if (
        row.get("schema") != "hepta.channel-matrix-source-provenance.v1"
        or row.get("valid") is not True
        or row.get("errors") != []
        or row.get("stage") != stage
        or row.get("checkoutSha") != source.get("testedSha")
        or row.get("checkoutTree") != source.get("testedTree")
        or not isinstance(execution, dict)
        or not isinstance(claims, dict)
        or claims.get("trackedSourceOnly") is not True
        or claims.get("generatedSourceIncluded") is not False
        or claims.get("cacheSourceIncluded") is not False
        or claims.get("artifactSourceIncluded") is not False
        or claims.get("authorityGranted") is not False
    ):
        raise ValueError(f"invalid {stage} source provenance")
    files = row.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"empty {stage} source provenance")
    for item in files:
        if (
            not isinstance(item, dict)
            or item.get("tracked") is not True
            or item.get("gitLsFilesErrorUnmatch") is not True
            or not isinstance(item.get("absolutePath"), str)
            or not isinstance(item.get("repoRelativePath"), str)
            or not SHA1.fullmatch(str(item.get("gitBlob", "")))
            or not SHA256.fullmatch(str(item.get("sha256", "")))
        ):
            raise ValueError(f"unverifiable {stage} source input")
    manifest = lane["manifest"]
    run_id = manifest.get("runId")
    attempt = manifest.get("runAttempt")
    if execution.get("workflowRunId") != run_id or execution.get("attemptId") != attempt:
        raise ValueError(f"{stage} source provenance and artifact manifest mix executions")
    if expected_run is not None and run_id != expected_run:
        raise ValueError(f"{stage} artifact belongs to another workflow run")
    if expected_attempt is not None and attempt != expected_attempt:
        raise ValueError(f"{stage} artifact belongs to another workflow attempt")
    runner_image = execution.get("runnerImage")
    target = execution.get("targetTriple")
    if not isinstance(runner_image, str) or not runner_image or runner_image == "local-unreported":
        raise ValueError(f"{stage} runner image is not bound")
    if not isinstance(target, str) or not target or target == "unavailable":
        raise ValueError(f"{stage} target triple is not bound")
    return row


def skeleton(event_kind: str, expected: dict[str, str | None]) -> dict[str, Any]:
    return {
        "schema": "hepta.channel-matrix-readiness.v1",
        "event_kind": event_kind,
        "source_head_sha": expected.get("source"),
        "frozen_source_sha": None,
        "base_sha": expected.get("base"),
        "deterministic_merge_sha": None,
        "github_merge_sha": expected.get("github_merge"),
        "workflow_sha": expected.get("workflow"),
        "final_merge_sha": expected.get("final_merge"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "attempt_id": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner_image": {"source_head": None, "deterministic_merge": None},
        "target_triple": {"source_head": None, "deterministic_merge": None},
        "Cargo.lock_hash": None,
        "migration_hash": None,
        "test_set_hash": None,
        "qualification_profile_hash": None,
        "implementation_map_hash": None,
        "documentation_hash": None,
        "source_tree_hash": None,
        "artifact_hashes": {},
        "lane_status": {
            "source_head": "missing",
            "deterministic_merge": "missing",
            "github_merge": "missing",
            "final_merge": "missing",
            "paired_repository_receipt": "missing",
            "same_workflow_attempt": False,
            "target_qualification": "not_proved",
            "independent_acceptance": "not_proved",
        },
        "repositoryQualified": False,
        "mergeReady": False,
        "productionQualified": False,
        "activation": False,
        "promotion": False,
        "release": False,
        "authorityGranted": False,
        "blockers": [],
    }


def build(
    source_head: Path,
    base_merge: Path,
    paired_receipt: Path,
    event_kind: str,
    expected_source: str,
    expected_base: str,
    expected_github_merge: str | None,
    expected_final_merge: str | None,
    expected_workflow: str,
) -> dict[str, Any]:
    expected = {
        "source": expected_source,
        "base": expected_base,
        "github_merge": expected_github_merge,
        "final_merge": expected_final_merge,
        "workflow": expected_workflow,
    }
    row = skeleton(event_kind, expected)
    repository_errors: list[str] = []
    expected_run = os.environ.get("GITHUB_RUN_ID")
    expected_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    try:
        if not SHA1.fullmatch(expected_source) or not SHA1.fullmatch(expected_base):
            raise ValueError("source/base identity is not exact lowercase 40-hex")
        if not SHA1.fullmatch(expected_workflow):
            raise ValueError("workflow Git blob identity is not exact lowercase 40-hex")
        source = paired_v2._extended_lane(source_head, "source-head")
        merge = paired_v2._extended_lane(base_merge, "base-merge")
        expected_pair = paired_v2.paired(source_head, base_merge)
        actual_pair = read_object(paired_receipt)
        if actual_pair != expected_pair:
            raise ValueError("paired receipt does not match the two exact lane artifacts")
        source_identity = source["source"]
        merge_identity = merge["source"]
        if source_identity.get("sourceSha") != expected_source:
            raise ValueError("source-head lane does not bind the expected source SHA")
        if source_identity.get("baseSha") != expected_base:
            raise ValueError("source-head lane does not bind the expected base SHA")
        if merge_identity.get("sourceSha") != expected_source or merge_identity.get("baseSha") != expected_base:
            raise ValueError("deterministic merge lane binds another source/base pair")
        source_provenance = validate_provenance(
            source["directory"], source, "source-head", expected_run, expected_attempt
        )
        merge_provenance = validate_provenance(
            merge["directory"], merge, "base-merge", expected_run, expected_attempt
        )
        source_manifest = source["manifest"]
        merge_manifest = merge["manifest"]
        if (
            source_manifest.get("runId") != merge_manifest.get("runId")
            or source_manifest.get("runAttempt") != merge_manifest.get("runAttempt")
        ):
            raise ValueError("source-head and deterministic merge mix workflow attempts")
        row["workflow_run_id"] = source_manifest.get("runId")
        row["attempt_id"] = source_manifest.get("runAttempt")
        row["source_head_sha"] = source_identity["sourceSha"]
        row["base_sha"] = source_identity["baseSha"]
        row["deterministic_merge_sha"] = merge_identity["testedSha"]
        row["source_tree_hash"] = source_identity["testedTree"]
        row["runner_image"] = {
            "source_head": source_provenance["execution"]["runnerImage"],
            "deterministic_merge": merge_provenance["execution"]["runnerImage"],
        }
        row["target_triple"] = {
            "source_head": source_provenance["execution"]["targetTriple"],
            "deterministic_merge": merge_provenance["execution"]["targetTriple"],
        }
        row["lane_status"]["source_head"] = "passed"
        row["lane_status"]["deterministic_merge"] = "passed"
        row["lane_status"]["paired_repository_receipt"] = "passed"
        row["lane_status"]["same_workflow_attempt"] = True

        implementation = read_object(IMPLEMENTATION_MAP)
        observed = implementation.get("observedAtHead")
        if not isinstance(observed, dict) or not SHA1.fullmatch(str(observed.get("commit", ""))):
            raise ValueError("implementation map lacks an exact frozen source commit")
        row["frozen_source_sha"] = observed["commit"]
        row["Cargo.lock_hash"] = digest(ROOT / "codex-rs/Cargo.lock")
        row["migration_hash"] = aggregate_tracked(
            b"hepta.channel-matrix-migrations.v1", "codex-rs/hepta-matrix-store/migrations"
        )
        row["test_set_hash"] = aggregate_tracked(
            b"hepta.channel-matrix-test-set.v1",
            "docs/modules/channel.matrix/QUALIFICATION_SCENARIOS.json",
            "codex-rs/.config/nextest.toml",
            "scripts/channel_matrix_focused_gate.py",
            "scripts/channel_matrix_evidence_v2.py",
            "scripts/channel_matrix_pair_acceptance_v2.py",
        )
        row["qualification_profile_hash"] = digest(QUALIFICATION_PROFILE)
        row["implementation_map_hash"] = digest(IMPLEMENTATION_MAP)
        row["documentation_hash"] = aggregate_tracked(
            b"hepta.channel-matrix-documentation.v1", "docs/modules/channel.matrix"
        )
        actual_workflow = git("rev-parse", f"{expected_source}:{WORKFLOW_PATH}").stdout.decode().strip()
        if actual_workflow != expected_workflow:
            raise ValueError("workflow SHA does not bind the source candidate workflow blob")
        row["workflow_sha"] = actual_workflow

        github_merge = expected_github_merge
        if github_merge is None:
            raise ValueError("GitHub merge identity is missing")
        github_object = git("rev-parse", f"{github_merge}^{{commit}}", check=False)
        if github_object.returncode != 0 or github_object.stdout.decode().strip() != github_merge:
            raise ValueError("GitHub merge commit is not present in the qualification checkout")
        github_tree = git("rev-parse", f"{github_merge}^{{tree}}").stdout.decode().strip()
        if github_tree != merge_identity["testedTree"]:
            raise ValueError("GitHub merge tree differs from the deterministic merge tree")
        row["github_merge_sha"] = github_merge
        row["lane_status"]["github_merge"] = "tree_matched"

        if expected_final_merge is not None:
            final_object = git("rev-parse", f"{expected_final_merge}^{{commit}}", check=False)
            if final_object.returncode != 0 or final_object.stdout.decode().strip() != expected_final_merge:
                raise ValueError("final merge commit is not present in the qualification checkout")
            if expected_final_merge != expected_source:
                raise ValueError("final merge SHA must be the exact tested source on a main push")
            row["final_merge_sha"] = expected_final_merge
            row["lane_status"]["final_merge"] = "passed"
        elif event_kind == "main_push":
            raise ValueError("main-push readiness lacks final merge identity")

        row["artifact_hashes"] = {
            "source_head_manifest": paired_v2.base.digest(source["directory"] / "manifest.json"),
            "deterministic_merge_manifest": paired_v2.base.digest(merge["directory"] / "manifest.json"),
            "source_head_provenance": paired_v2.base.digest(
                source["directory"] / "source-provenance.json"
            ),
            "deterministic_merge_provenance": paired_v2.base.digest(
                merge["directory"] / "source-provenance.json"
            ),
            "paired_repository_receipt": digest(paired_receipt),
            "source_head_artifact_set": source_manifest.get("artifactSetSha256"),
            "deterministic_merge_artifact_set": merge_manifest.get("artifactSetSha256"),
        }
        row["repositoryQualified"] = True
        row["mergeReady"] = event_kind == "main_push" and expected_final_merge is not None
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        repository_errors.append(str(exc))

    if event_kind != "main_push" and expected_final_merge is None:
        row["blockers"].append("final merge SHA is not available before protected main integration")
    row["blockers"].extend(repository_errors)
    row["blockers"].extend(
        [
            "target-host production qualification is not proved by repository CI",
            "independent security/operator acceptance is not proved",
        ]
    )
    # Repository evidence can never self-issue these claims. A future external
    # governed receipt join may derive productionQualified in a separate scope.
    row["productionQualified"] = False
    if repository_errors:
        row["repositoryQualified"] = False
        row["mergeReady"] = False
    return row


def write_output(path_value: Path, row: dict[str, Any]) -> None:
    path = path_value.absolute()
    parent = path.parent.resolve(strict=True)
    if path_value.is_symlink() or parent.is_relative_to(ROOT.resolve()) or path.exists():
        raise ValueError("output must be a new canonical file outside the checkout")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(row, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-head", required=True, type=Path)
    parser.add_argument("--base-merge", required=True, type=Path)
    parser.add_argument("--paired", required=True, type=Path)
    parser.add_argument(
        "--event-kind",
        required=True,
        choices=("pull_request", "main_push", "workflow_dispatch"),
    )
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--github-merge-sha", default="")
    parser.add_argument("--final-merge-sha", default="")
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        row = build(
            args.source_head,
            args.base_merge,
            args.paired,
            args.event_kind,
            args.source_sha,
            args.base_sha,
            optional_sha(args.github_merge_sha),
            optional_sha(args.final_merge_sha),
            args.workflow_sha,
        )
        write_output(args.output, row)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_READINESS: {exc}\n")
    if not row["repositoryQualified"]:
        print("FAIL_CHANNEL_MATRIX_READINESS: repository evidence is incomplete", file=sys.stderr)
        return 1
    print("PASS_CHANNEL_MATRIX_READINESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
