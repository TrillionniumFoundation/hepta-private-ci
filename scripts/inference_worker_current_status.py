#!/usr/bin/env python3
"""Generate exact-candidate inference.worker qualification status.

The checked-in module documents describe source intent. This script emits the
run-bound evidence record: exact commit/tree/blob identities, platform results,
profile maturity and external gates. It intentionally never upgrades hardware,
deployment or independent-acceptance gates from repository-local evidence.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
from collections.abc import Sequence
from typing import Any

_SCHEMA = "hepta.inference-worker-current-status.v1"
_DEFAULT_ROOTS = (
    "codex-rs/hepta-infer-worker-host",
    "codex-rs/hepta-infer-core/src/durable_control.rs",
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "docs/modules/inference.worker",
    "qualification/module-execution-dossiers/detail/inference.worker.md",
)


def _git(repo: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _require_object_id(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 40 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{field} must be a 40-character lowercase Git object id")
    return normalized


def source_blob_digests(
    repo: pathlib.Path,
    source_head: str,
    roots: Sequence[str],
) -> dict[str, str]:
    command = ["ls-tree", "-r", "--full-tree", source_head, "--", *roots]
    output = _git(repo, *command)
    blobs: dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            continue
        metadata, path = line.split("\t", 1)
        _mode, object_type, object_id = metadata.split(" ", 2)
        if object_type != "blob":
            continue
        blobs[path] = _require_object_id(object_id, f"blob id for {path}")
    if not blobs:
        raise ValueError("no source blobs were found for the declared inference.worker roots")
    return dict(sorted(blobs.items()))


def build_status(
    *,
    repository: str,
    repo: pathlib.Path,
    source_head: str,
    exact_head_run_id: str,
    exact_head_run_url: str,
    exact_head_result: str,
    merge_candidate_commit: str | None,
    merge_candidate_result: str,
    linux_result: str,
    macos_result: str,
    derived_projections_result: str,
    roots: Sequence[str],
    generated_at: str | None = None,
) -> dict[str, Any]:
    source_head = _require_object_id(source_head, "source_head")
    observed_head = _require_object_id(_git(repo, "rev-parse", "HEAD"), "checked out HEAD")
    if observed_head != source_head:
        raise ValueError(
            f"checked out HEAD {observed_head} does not match requested source_head {source_head}"
        )
    source_tree = _require_object_id(
        _git(repo, "rev-parse", f"{source_head}^{{tree}}"), "source_tree"
    )
    merge_commit = None
    if merge_candidate_commit:
        merge_commit = _require_object_id(
            merge_candidate_commit, "merge_candidate_commit"
        )

    local_checks_passed = all(
        value == "success"
        for value in (linux_result, macos_result, derived_projections_result)
    ) and merge_candidate_result in {"success", "skipped", "not_applicable"}
    aggregate = "success" if local_checks_passed else "failed_or_incomplete"
    timestamp = generated_at or dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0
    ).isoformat()

    return {
        "schema": _SCHEMA,
        "schemaVersion": 1,
        "generated_at": timestamp,
        "repository": repository,
        "source_head": source_head,
        "source_tree": source_tree,
        "source_blob_digests": source_blob_digests(repo, source_head, roots),
        "last_exact_head_run": {
            "run_id": exact_head_run_id,
            "url": exact_head_run_url,
            "result": exact_head_result,
        },
        "last_merge_candidate_run": {
            "commit": merge_commit,
            "result": merge_candidate_result,
        },
        "linux_result": linux_result,
        "macos_result": macos_result,
        "derived_projections_result": derived_projections_result,
        "lib_test_result": aggregate,
        "binary_test_result": aggregate,
        "all_targets_result": aggregate,
        "clippy_result": aggregate,
        "clean_tree_result": aggregate,
        "real_hardware_result": "not_run_external_gate",
        "composition_result": "not_established",
        "independent_acceptance_result": "not_established",
        "profiles": {
            "HostedAppServerWorker": "production-candidate",
            "LocalModelWorker": "experimental-non-production",
            "LegacyReceiptBoundary": "validation-only",
        },
        "local_model_source": {
            "signed_resource_grant": "implemented",
            "verified_manifest_input_deadline": "implemented",
            "aggregate_resource_manager": "implemented",
            "durable_no_replay_recovery": "implemented",
            "real_weights_device_driver": "not_implemented_external_and_product_gate",
            "target_hardware_fault_qualification": "not_established",
        },
        "provider_reconciliation": {
            "exact_app_server_thread_history": "implemented",
            "missing_history_resolution": (
                "repository_quarantine_and_trusted_terminal_receipt_port_implemented; "
                "deployed_resolver_not_established"
            ),
            "trusted_token_usage_reconciliation": (
                "unknown_is_preserved_and_monotonic_receipt_refinement_is_supported; "
                "deployed_provider_verifier_not_established"
            ),
            "real_provider_target_host_qualification": "not_established",
        },
        "operating_runbook": "docs/modules/inference.worker/RECOVERY_AND_OPERATIONS.md",
        "claim_boundary": {
            "repository_local_qualification_complete": local_checks_passed,
            "production_implementation": False,
            "product_execution_complete": False,
            "deployment_qualification_complete": False,
            "independent_acceptance_complete": False,
            "activation": False,
            "release": False,
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--exact-head-run-id", required=True)
    parser.add_argument("--exact-head-run-url", required=True)
    parser.add_argument("--exact-head-result", required=True)
    parser.add_argument("--merge-candidate-commit")
    parser.add_argument("--merge-candidate-result", required=True)
    parser.add_argument("--linux-result", required=True)
    parser.add_argument("--macos-result", required=True)
    parser.add_argument("--derived-projections-result", required=True)
    parser.add_argument("--root", action="append", dest="roots")
    parser.add_argument("--generated-at")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo_root.resolve()
    status = build_status(
        repository=args.repository,
        repo=repo,
        source_head=args.source_head,
        exact_head_run_id=args.exact_head_run_id,
        exact_head_run_url=args.exact_head_run_url,
        exact_head_result=args.exact_head_result,
        merge_candidate_commit=args.merge_candidate_commit,
        merge_candidate_result=args.merge_candidate_result,
        linux_result=args.linux_result,
        macos_result=args.macos_result,
        derived_projections_result=args.derived_projections_result,
        roots=tuple(args.roots or _DEFAULT_ROOTS),
        generated_at=args.generated_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
