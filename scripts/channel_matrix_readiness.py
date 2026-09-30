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
import channel_matrix_source_provenance as source_provenance

ROOT = SCRIPT_DIRECTORY.parent
WORKFLOW_PATH = ".github/workflows/channel-matrix-preserve-unknown.yml"
IMPLEMENTATION_MAP = ROOT / "docs/modules/channel.matrix/IMPLEMENTATION_MAP.json"
PRODUCTION_QUALIFICATION_PROFILE = (
    ROOT / "docs/modules/channel.matrix/PRODUCTION_QUALIFICATION_PROFILE.json"
)
PROCESS_FAULT_PROFILE = ROOT / "docs/modules/channel.matrix/PROCESS_FAULT_MATRIX.json"
TRANSPORT_TCB = ROOT / "docs/modules/channel.matrix/TRANSPORT_TCB.json"
MODULE_STATUS = ROOT / "docs/modules/channel.matrix/MODULE_STATUS.json"
DOCUMENT_SOURCES = ROOT / "docs/modules/channel.matrix/DOCUMENT_SOURCES.json"
REVIEW_SLICES = ROOT / "docs/modules/channel.matrix/REVIEW_SLICES.json"
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
READINESS_KEY_DOMAIN = b"hepta.channel-matrix-readiness-key.v1"
REPOSITORY_REQUIRED_LANES = (
    "source_head",
    "source_head_provenance",
    "deterministic_merge",
    "deterministic_merge_provenance",
    "github_merge",
    "paired_repository_receipt",
    "same_workflow_attempt",
)
MERGE_REQUIRED_LANES = (*REPOSITORY_REQUIRED_LANES, "final_merge")
PRODUCTION_REQUIRED_LANES = (
    *MERGE_REQUIRED_LANES,
    "target_qualification",
    "independent_acceptance",
)
READINESS_KEY_FIELDS = (
    "event_kind",
    "source_head_sha",
    "source_tree_hash",
    "frozen_source_sha",
    "frozen_source_tree_hash",
    "base_sha",
    "deterministic_merge_sha",
    "deterministic_merge_tree_hash",
    "github_merge_sha",
    "github_merge_tree_hash",
    "workflow_sha",
    "final_merge_sha",
    "final_merge_tree_hash",
    "workflow_run_id",
    "attempt_id",
    "runner_image",
    "target_triple",
    "Cargo.lock_hash",
    "migration_hash",
    "test_set_hash",
    "qualification_profile_hash",
    "production_qualification_profile_hash",
    "process_fault_profile_hash",
    "transport_tcb_hash",
    "implementation_map_hash",
    "module_status_hash",
    "document_sources_hash",
    "review_slices_hash",
    "documentation_hash",
    "artifact_hashes",
    "required_lanes",
    "lane_status",
)


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


def canonical_digest(domain: bytes, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(domain + b"\0" + encoded).hexdigest()


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
    return canonical_digest(domain, rows)


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
    manifest = lane["manifest"]
    run_id = manifest.get("runId")
    attempt = manifest.get("runAttempt")
    source_provenance.validate_receipt(
        row,
        expected_stage=stage,
        expected_sha=str(source.get("testedSha", "")),
        expected_tree=str(source.get("testedTree", "")),
        expected_run=run_id,
        expected_attempt=attempt,
    )
    if expected_run is not None and run_id != expected_run:
        raise ValueError(f"{stage} artifact belongs to another workflow run")
    if expected_attempt is not None and attempt != expected_attempt:
        raise ValueError(f"{stage} artifact belongs to another workflow attempt")
    execution = row["execution"]
    runner_image = execution.get("runnerImage")
    target = execution.get("targetTriple")
    if not isinstance(runner_image, str) or not runner_image or runner_image == "local-unreported":
        raise ValueError(f"{stage} runner image is not bound")
    if not isinstance(target, str) or not target or target == "unavailable":
        raise ValueError(f"{stage} target triple is not bound")
    return row


def lanes_passed(row: dict[str, Any], names: tuple[str, ...]) -> bool:
    lane_status = row.get("lane_status")
    return isinstance(lane_status, dict) and all(
        lane_status.get(name) == "passed" for name in names
    )


def readiness_key(row: dict[str, Any]) -> str:
    identity = {field: row.get(field) for field in READINESS_KEY_FIELDS}
    for field in (
        "source_head_sha",
        "source_tree_hash",
        "frozen_source_sha",
        "frozen_source_tree_hash",
        "base_sha",
        "deterministic_merge_sha",
        "deterministic_merge_tree_hash",
        "github_merge_sha",
        "github_merge_tree_hash",
        "workflow_sha",
    ):
        if not isinstance(identity.get(field), str) or not SHA1.fullmatch(identity[field]):
            raise ValueError(f"readiness identity lacks exact Git field: {field}")
    for field in (
        "Cargo.lock_hash",
        "migration_hash",
        "test_set_hash",
        "qualification_profile_hash",
        "production_qualification_profile_hash",
        "process_fault_profile_hash",
        "transport_tcb_hash",
        "implementation_map_hash",
        "module_status_hash",
        "document_sources_hash",
        "review_slices_hash",
        "documentation_hash",
    ):
        if not isinstance(identity.get(field), str) or not SHA256.fullmatch(identity[field]):
            raise ValueError(f"readiness identity lacks exact SHA-256 field: {field}")
    for field in ("workflow_run_id", "attempt_id"):
        if not isinstance(identity.get(field), str) or not identity[field]:
            raise ValueError(f"readiness identity lacks execution field: {field}")
    for field in ("runner_image", "target_triple"):
        values = identity.get(field)
        if (
            not isinstance(values, dict)
            or set(values) != {"source_head", "deterministic_merge"}
            or any(not isinstance(value, str) or not value for value in values.values())
        ):
            raise ValueError(f"readiness identity lacks closed execution map: {field}")
    expected_required = {
        "repository": list(REPOSITORY_REQUIRED_LANES),
        "merge": list(MERGE_REQUIRED_LANES),
        "production": list(PRODUCTION_REQUIRED_LANES),
    }
    if identity.get("required_lanes") != expected_required:
        raise ValueError("readiness identity required-lane inventory drifted")
    if row.get("event_kind") == "main_push":
        for field in ("final_merge_sha", "final_merge_tree_hash"):
            if not isinstance(identity.get(field), str) or not SHA1.fullmatch(identity[field]):
                raise ValueError(f"main-push readiness lacks exact field: {field}")
    artifacts = identity.get("artifact_hashes")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("readiness identity lacks artifact hashes")
    for name, value in artifacts.items():
        if not isinstance(name, str) or not isinstance(value, str) or not SHA256.fullmatch(value):
            raise ValueError("readiness artifact hashes are not closed SHA-256 identities")
    if not lanes_passed(row, REPOSITORY_REQUIRED_LANES):
        raise ValueError("readiness key cannot bind incomplete repository lanes")
    return canonical_digest(READINESS_KEY_DOMAIN, identity)


def skeleton(event_kind: str, expected: dict[str, str | None]) -> dict[str, Any]:
    return {
        "schema": "hepta.channel-matrix-readiness.v1",
        "event_kind": event_kind,
        "candidate_key": None,
        "source_head_sha": expected.get("source"),
        "source_tree_hash": None,
        "frozen_source_sha": None,
        "frozen_source_tree_hash": None,
        "base_sha": expected.get("base"),
        "deterministic_merge_sha": None,
        "deterministic_merge_tree_hash": None,
        "github_merge_sha": expected.get("github_merge"),
        "github_merge_tree_hash": None,
        "workflow_sha": expected.get("workflow"),
        "final_merge_sha": expected.get("final_merge"),
        "final_merge_tree_hash": None,
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "attempt_id": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner_image": {"source_head": None, "deterministic_merge": None},
        "target_triple": {"source_head": None, "deterministic_merge": None},
        "Cargo.lock_hash": None,
        "migration_hash": None,
        "test_set_hash": None,
        "qualification_profile_hash": None,
        "production_qualification_profile_hash": None,
        "process_fault_profile_hash": None,
        "transport_tcb_hash": None,
        "implementation_map_hash": None,
        "module_status_hash": None,
        "document_sources_hash": None,
        "review_slices_hash": None,
        "documentation_hash": None,
        "artifact_hashes": {},
        "required_lanes": {
            "repository": list(REPOSITORY_REQUIRED_LANES),
            "merge": list(MERGE_REQUIRED_LANES),
            "production": list(PRODUCTION_REQUIRED_LANES),
        },
        "lane_status": {
            "source_head": "missing",
            "source_head_provenance": "missing",
            "deterministic_merge": "missing",
            "deterministic_merge_provenance": "missing",
            "github_merge": "missing",
            "final_merge": "missing",
            "paired_repository_receipt": "missing",
            "same_workflow_attempt": "missing",
            "target_qualification": "not_proved",
            "independent_acceptance": "not_proved",
        },
        "evidence_policy": {
            "crossCandidateMixingAllowed": False,
            "crossWorkflowRunMixingAllowed": False,
            "crossAttemptMixingAllowed": False,
            "prEvidenceReusableForFinalMerge": False,
            "repositoryManifestMayGrantProduction": False,
            "nonMixableManifestKeyBound": False,
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
        if (
            merge_identity.get("sourceSha") != expected_source
            or merge_identity.get("baseSha") != expected_base
        ):
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
        row["source_tree_hash"] = source_identity["testedTree"]
        row["deterministic_merge_sha"] = merge_identity["testedSha"]
        row["deterministic_merge_tree_hash"] = merge_identity["testedTree"]
        row["runner_image"] = {
            "source_head": source_provenance["execution"]["runnerImage"],
            "deterministic_merge": merge_provenance["execution"]["runnerImage"],
        }
        row["target_triple"] = {
            "source_head": source_provenance["execution"]["targetTriple"],
            "deterministic_merge": merge_provenance["execution"]["targetTriple"],
        }
        row["lane_status"]["source_head"] = "passed"
        row["lane_status"]["source_head_provenance"] = "passed"
        row["lane_status"]["deterministic_merge"] = "passed"
        row["lane_status"]["deterministic_merge_provenance"] = "passed"
        row["lane_status"]["paired_repository_receipt"] = "passed"
        row["lane_status"]["same_workflow_attempt"] = "passed"

        implementation = read_object(IMPLEMENTATION_MAP)
        observed = implementation.get("observedAtHead")
        if (
            not isinstance(observed, dict)
            or not SHA1.fullmatch(str(observed.get("commit", "")))
            or not SHA1.fullmatch(str(observed.get("tree", "")))
        ):
            raise ValueError("implementation map lacks an exact frozen source identity")
        row["frozen_source_sha"] = observed["commit"]
        row["frozen_source_tree_hash"] = observed["tree"]
        row["Cargo.lock_hash"] = digest(ROOT / "codex-rs/Cargo.lock")
        row["migration_hash"] = aggregate_tracked(
            b"hepta.channel-matrix-migrations.v1",
            "codex-rs/hepta-matrix-store/migrations",
        )
        row["test_set_hash"] = aggregate_tracked(
            b"hepta.channel-matrix-test-set.v2",
            "docs/modules/channel.matrix/QUALIFICATION_SCENARIOS.json",
            "codex-rs/.config/nextest.toml",
            "codex-rs/hepta-matrix-sdk/tests",
            "codex-rs/hepta-matrix-store/tests",
            "codex-rs/hepta-matrixd/tests",
            "scripts/tests/test_channel_matrix*",
            "scripts/channel_matrix_focused_gate.py",
            "scripts/channel_matrix_evidence_v2.py",
            "scripts/channel_matrix_pair_acceptance_v2.py",
            "tests/fixtures/run-hermetic-synapse.sh",
        )
        row["production_qualification_profile_hash"] = digest(
            PRODUCTION_QUALIFICATION_PROFILE
        )
        row["process_fault_profile_hash"] = digest(PROCESS_FAULT_PROFILE)
        row["transport_tcb_hash"] = digest(TRANSPORT_TCB)
        row["qualification_profile_hash"] = aggregate_tracked(
            b"hepta.channel-matrix-qualification-contract.v2",
            "docs/modules/channel.matrix/PRODUCTION_QUALIFICATION_PROFILE.json",
            "docs/modules/channel.matrix/PROCESS_FAULT_MATRIX.json",
            "docs/modules/channel.matrix/QUALIFICATION_SCENARIOS.json",
            "docs/modules/channel.matrix/TRANSPORT_TCB.json",
        )
        row["implementation_map_hash"] = digest(IMPLEMENTATION_MAP)
        row["module_status_hash"] = digest(MODULE_STATUS)
        row["document_sources_hash"] = digest(DOCUMENT_SOURCES)
        row["review_slices_hash"] = digest(REVIEW_SLICES)
        row["documentation_hash"] = aggregate_tracked(
            b"hepta.channel-matrix-documentation.v1", "docs/modules/channel.matrix"
        )
        actual_workflow = git(
            "rev-parse", f"{expected_source}:{WORKFLOW_PATH}"
        ).stdout.decode().strip()
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
        row["github_merge_tree_hash"] = github_tree
        row["lane_status"]["github_merge"] = "passed"

        if expected_final_merge is not None:
            final_object = git("rev-parse", f"{expected_final_merge}^{{commit}}", check=False)
            if (
                final_object.returncode != 0
                or final_object.stdout.decode().strip() != expected_final_merge
            ):
                raise ValueError("final merge commit is not present in the qualification checkout")
            if expected_final_merge != expected_source:
                raise ValueError("final merge SHA must be the exact tested source on a main push")
            final_tree = git("rev-parse", f"{expected_final_merge}^{{tree}}").stdout.decode().strip()
            if final_tree != source_identity["testedTree"]:
                raise ValueError("final merge tree differs from the tested source tree")
            row["final_merge_sha"] = expected_final_merge
            row["final_merge_tree_hash"] = final_tree
            row["lane_status"]["final_merge"] = "passed"
        elif event_kind == "main_push":
            raise ValueError("main-push readiness lacks final merge identity")

        row["artifact_hashes"] = {
            "source_head_manifest": paired_v2.base.digest(
                source["directory"] / "manifest.json"
            ),
            "deterministic_merge_manifest": paired_v2.base.digest(
                merge["directory"] / "manifest.json"
            ),
            "source_head_provenance": paired_v2.base.digest(
                source["directory"] / "source-provenance.json"
            ),
            "deterministic_merge_provenance": paired_v2.base.digest(
                merge["directory"] / "source-provenance.json"
            ),
            "source_head_source_inventory": source_provenance["sourceInventorySha256"],
            "deterministic_merge_source_inventory": merge_provenance[
                "sourceInventorySha256"
            ],
            "source_head_content_inventory": source_provenance[
                "sourceContentInventorySha256"
            ],
            "deterministic_merge_content_inventory": merge_provenance[
                "sourceContentInventorySha256"
            ],
            "paired_repository_receipt": digest(paired_receipt),
            "source_head_artifact_set": source_manifest.get("artifactSetSha256"),
            "deterministic_merge_artifact_set": merge_manifest.get("artifactSetSha256"),
        }
        if any(
            not isinstance(value, str) or not SHA256.fullmatch(value)
            for value in row["artifact_hashes"].values()
        ):
            raise ValueError("one or more readiness artifact identities are not SHA-256")
        row["repositoryQualified"] = lanes_passed(row, REPOSITORY_REQUIRED_LANES)
        row["mergeReady"] = event_kind == "main_push" and lanes_passed(
            row, MERGE_REQUIRED_LANES
        )
        row["candidate_key"] = readiness_key(row)
        row["evidence_policy"]["nonMixableManifestKeyBound"] = True
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
        row["blockers"].append(
            "final merge SHA is not available before protected main integration"
        )
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
        row["candidate_key"] = None
        row["evidence_policy"]["nonMixableManifestKeyBound"] = False
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
        print(
            "FAIL_CHANNEL_MATRIX_READINESS: repository evidence is incomplete",
            file=sys.stderr,
        )
        return 1
    print("PASS_CHANNEL_MATRIX_READINESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
