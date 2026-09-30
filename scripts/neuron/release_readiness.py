#!/usr/bin/env python3
"""Finalize neuron.runtime source readiness with the exact repository baseline.

This tool deliberately cannot activate production or authorize a release.  It
combines one already-validated module readiness manifest with the blocking-ci
``CI required`` job for the same source/base candidate and emits a single,
bounded, immutable manifest suitable for workflow retention.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = ROOT / "docs/modules/neuron.runtime/MODULE_SPEC.json"
MODULE_SCHEMA = "hepta.neuron.runtime.readiness-manifest.v2"
BASELINE_SCHEMA = "hepta.neuron.runtime.repository-baseline.v1"
FINAL_SCHEMA = "hepta.neuron.runtime.release-readiness-manifest.v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_GATES = 64


class ReleaseReadinessError(RuntimeError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ReleaseReadinessError(f"cannot stat {path}: {error}") from error
    if size > MAX_JSON_BYTES:
        raise ReleaseReadinessError(f"JSON input exceeds {MAX_JSON_BYTES} bytes: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ReleaseReadinessError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReleaseReadinessError(f"expected JSON object: {path}")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as error:
        raise ReleaseReadinessError(f"cannot hash {path}: {error}") from error


def require_sha(label: str, value: Any) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise ReleaseReadinessError(f"{label} must be a lowercase 40-hex commit SHA")
    return value


def require_false(label: str, value: Any) -> None:
    if value is not False:
        raise ReleaseReadinessError(f"{label} must remain false")


def validate_module_manifest(
    manifest: dict[str, Any], source_sha: str, base_sha: str
) -> list[str]:
    blockers: list[str] = []
    if manifest.get("schema") != MODULE_SCHEMA:
        blockers.append("module readiness schema is not current")
    if manifest.get("module") != "neuron.runtime":
        blockers.append("module readiness belongs to another module")
    if manifest.get("sourceSha") != source_sha:
        blockers.append("module readiness source SHA differs from candidate")
    if manifest.get("baseSha") != base_sha:
        blockers.append("module readiness base SHA differs from candidate")
    if manifest.get("qualificationReady") is not True:
        blockers.append("module readiness is not qualified")
    if manifest.get("productionActivation") is not False:
        blockers.append("module manifest attempted production activation")
    if manifest.get("release") is not False:
        blockers.append("module manifest attempted release authorization")
    claim = manifest.get("claimBoundary")
    if not isinstance(claim, dict):
        blockers.append("module claim boundary is missing")
    else:
        if claim.get("productionActivation") is not False:
            blockers.append("module claim boundary attempted production activation")
        if claim.get("release") is not False:
            blockers.append("module claim boundary attempted release authorization")
        if claim.get("sourceQualification") is not True:
            blockers.append("module source qualification claim is not true")
    workflow_outcomes = manifest.get("workflowOutcomes")
    if not isinstance(workflow_outcomes, dict) or any(
        workflow_outcomes.get(name) != "success"
        for name in ("qualification", "download")
    ):
        blockers.append("module workflow or artifact download did not succeed")
    gates = manifest.get("gates")
    if not isinstance(gates, list) or not gates or len(gates) > MAX_GATES:
        blockers.append("module gate inventory is missing or out of bounds")
    elif any(
        not isinstance(gate, dict) or gate.get("result") != "success" for gate in gates
    ):
        blockers.append("one or more module gates did not succeed")
    manifest_blockers = manifest.get("blockers")
    if manifest_blockers not in ([], None):
        blockers.append("module readiness retains blockers")
    return blockers


def validate_baseline(
    baseline: dict[str, Any], source_sha: str, base_sha: str
) -> list[str]:
    blockers: list[str] = []
    if baseline.get("schema") != BASELINE_SCHEMA:
        blockers.append("repository baseline schema is not current")
    if baseline.get("sourceSha") != source_sha:
        blockers.append("repository baseline source SHA differs from candidate")
    if baseline.get("baseSha") != base_sha:
        blockers.append("repository baseline base SHA differs from candidate")
    pull_request = baseline.get("pullRequest")
    if not isinstance(pull_request, dict):
        blockers.append("repository baseline pull request binding is missing")
    else:
        number = pull_request.get("number")
        if not isinstance(number, int) or number <= 0:
            blockers.append("repository baseline pull request number is invalid")
        if pull_request.get("headSha") != source_sha:
            blockers.append("repository baseline pull request head differs from candidate")
        if pull_request.get("baseSha") != base_sha:
            blockers.append("repository baseline pull request base differs from candidate")
    if baseline.get("workflow") != "blocking-ci":
        blockers.append("repository baseline did not come from blocking-ci")
    if baseline.get("checkName") != "CI required":
        blockers.append("repository baseline is not the CI required job")
    if baseline.get("status") != "completed":
        blockers.append("repository baseline is not complete")
    if baseline.get("conclusion") != "success":
        blockers.append("repository baseline did not succeed")
    for field in ("runId", "runAttempt", "jobId"):
        value = baseline.get(field)
        if not isinstance(value, int) or value <= 0:
            blockers.append(f"repository baseline {field} is invalid")
    fingerprint = baseline.get("runnerFingerprintSha256")
    if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        blockers.append("repository baseline runner fingerprint is invalid")
    return blockers


def source_bindings(spec_path: Path) -> dict[str, Any]:
    spec = read_json(spec_path)
    documents = spec.get("documents")
    if not isinstance(documents, list) or len(documents) > 256:
        raise ReleaseReadinessError("module document inventory is invalid")
    document_records: list[dict[str, str]] = []
    for item in documents:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ReleaseReadinessError("module document entry is invalid")
        relative = item["path"]
        path = ROOT / relative
        if not path.is_file():
            raise ReleaseReadinessError(f"bound module document is missing: {relative}")
        document_records.append({"path": relative, "sha256": file_sha256(path)})
    document_records.sort(key=lambda item: item["path"])

    paths = spec.get("paths")
    qualification = spec.get("qualification")
    if not isinstance(paths, dict) or not isinstance(qualification, dict):
        raise ReleaseReadinessError("module spec paths or qualification section is invalid")
    implementation_map = paths.get("implementationMap")
    module_workflow = qualification.get("workflow")
    if not isinstance(implementation_map, str) or not isinstance(module_workflow, str):
        raise ReleaseReadinessError("module spec binding paths are invalid")

    baseline_sources = [
        ".github/workflows/blocking-ci.yml",
        ".github/scripts/check_ci_results.py",
        "scripts/hepta_ci_scope.py",
        "scripts/hepta_ci_dependencies.py",
    ]
    baseline_records = [
        {"path": relative, "sha256": file_sha256(ROOT / relative)}
        for relative in baseline_sources
    ]
    return {
        "specSha256": file_sha256(spec_path),
        "cargoLockSha256": file_sha256(ROOT / "codex-rs/Cargo.lock"),
        "documentationSha256": sha256_bytes(canonical_bytes(document_records)),
        "implementationMapSha256": file_sha256(ROOT / implementation_map),
        "moduleWorkflowSha256": file_sha256(ROOT / module_workflow),
        "repositoryBaselineDefinitionSha256": sha256_bytes(
            canonical_bytes(baseline_records)
        ),
        "finalizerSha256": file_sha256(Path(__file__).resolve()),
    }


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    source_sha = require_sha("source SHA", args.source_sha)
    base_sha = require_sha("base SHA", args.base_sha)
    module_manifest = read_json(args.module_manifest)
    baseline = read_json(args.baseline)

    blockers = validate_module_manifest(module_manifest, source_sha, base_sha)
    blockers.extend(validate_baseline(baseline, source_sha, base_sha))
    bindings = source_bindings(args.spec.resolve())

    generated_at = (
        args.generated_at
        or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    )
    final = {
        "schema": FINAL_SCHEMA,
        "module": "neuron.runtime",
        "generatedAt": generated_at,
        "sourceSha": source_sha,
        "baseSha": base_sha,
        "qualificationReady": not blockers,
        "moduleReadiness": {
            "schema": module_manifest.get("schema"),
            "workflowRunId": str(
                module_manifest.get("workflowContext", {}).get("runId", "")
            ),
            "workflowRunAttempt": str(
                module_manifest.get("workflowContext", {}).get("runAttempt", "")
            ),
            "sha256": file_sha256(args.module_manifest),
        },
        "repositoryBaseline": baseline,
        "sourceBindings": bindings,
        "productionActivation": False,
        "release": False,
        "blockers": sorted(set(blockers)),
        "claimBoundary": {
            "moduleSourceQualification": not validate_module_manifest(
                module_manifest, source_sha, base_sha
            ),
            "repositoryBaselineQualified": not validate_baseline(
                baseline, source_sha, base_sha
            ),
            "productExecutionProved": False,
            "independentAcceptance": False,
            "productionActivation": False,
            "release": False,
        },
    }
    require_false("final production activation", final["productionActivation"])
    require_false("final release", final["release"])

    if args.output.resolve().is_relative_to(ROOT.resolve()):
        raise ReleaseReadinessError("final evidence output must be outside checked source")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(final))
    if blockers and not args.allow_incomplete:
        raise ReleaseReadinessError("; ".join(final["blockers"]))
    return final


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    command = sub.add_parser("finalize")
    command.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    command.add_argument("--module-manifest", type=Path, required=True)
    command.add_argument("--baseline", type=Path, required=True)
    command.add_argument("--source-sha", required=True)
    command.add_argument("--base-sha", required=True)
    command.add_argument("--generated-at")
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--allow-incomplete", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command != "finalize":
            raise AssertionError(args.command)
        finalize(args)
    except (
        ReleaseReadinessError,
        OSError,
        ValueError,
        KeyError,
        RecursionError,
    ) as error:
        print(f"neuron release readiness: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
