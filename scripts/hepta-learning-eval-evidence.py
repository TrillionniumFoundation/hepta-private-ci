#!/usr/bin/env python3
"""Emit and verify commit-addressed learning.eval CI evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hepta.learning-eval.ci-evidence.v1"
MAX_AGE_DAYS = 30
INPUT_PATHS = (
    "codex-rs/hepta-intelligence-eval",
    "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
    "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
    "codex-rs/hepta-learning-ledger/src/signed_evidence.rs",
    "codex-rs/hepta-shadow-qualification/src/lane_e_closure_tests.rs",
    "codex-rs/hepta-shadow-qualification/tests/lane_e_api_contract.rs",
    "docs/modules/learning.eval/TECHNICAL.md",
    "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json",
    "qualification/lane-e/TEST_TRACEABILITY.json",
    "qualification/module-execution-dossiers/detail/learning.eval.md",
    ".github/workflows/hepta-lane-e-gap-closure.yml",
    "scripts/hepta-lane-e-closure.py",
    "scripts/hepta-learning-eval-evidence.py",
    "codex-rs/Cargo.lock",
)
DIGEST_FILES = {
    "productionContractDigest": "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md",
    "nativeMappingDigest": "codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md",
    "evidenceAdmissionDigest": "codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md",
    "traceabilityDigest": "qualification/lane-e/TEST_TRACEABILITY.json",
    "workflowDigest": ".github/workflows/hepta-lane-e-gap-closure.yml",
    "cargoLockDigest": "codex-rs/Cargo.lock",
}


def run(*args: str) -> bytes:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def git_text(*args: str) -> str:
    return run("git", *args).decode("utf-8").strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def index_bytes(path: str) -> bytes:
    return run("git", "show", f":{path}")


def tracked_paths() -> list[str]:
    raw = run("git", "ls-files", "-z", "--", *INPUT_PATHS)
    paths = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    if not paths:
        raise ValueError("no tracked evidence inputs")
    return sorted(paths)


def input_digest() -> tuple[str, int]:
    digest = hashlib.sha256()
    paths = tracked_paths()
    for path in paths:
        raw_path = path.encode("utf-8")
        content = index_bytes(path)
        digest.update(len(raw_path).to_bytes(4, "big"))
        digest.update(raw_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest(), len(paths)


def file_digest(path: str) -> str:
    return sha256_bytes(index_bytes(path))


def output_digest(path_value: str) -> dict[str, Any]:
    path = (ROOT / path_value).resolve()
    root = ROOT.resolve()
    if root not in path.parents:
        raise ValueError("qualification output must remain inside repository workspace")
    if not path.is_file():
        raise ValueError(f"missing qualification output: {path_value}")
    content = path.read_bytes()
    if not content:
        raise ValueError(f"empty qualification output: {path_value}")
    return {
        "path": str(path.relative_to(root)),
        "sha256": sha256_bytes(content),
        "bytes": len(content),
    }


def rust_identity() -> dict[str, str]:
    output = run("rustc", "-Vv").decode("utf-8")
    result: dict[str, str] = {"rawDigest": sha256_bytes(output.encode("utf-8"))}
    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key in {"release", "host", "commit-hash"}:
                result[key] = value.strip()
    return result


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def emit(args: argparse.Namespace) -> dict[str, Any]:
    digest, count = input_digest()
    current_tree = git_text("write-tree")
    if current_tree != args.candidate_tree:
        raise ValueError(
            f"candidate tree mismatch: index={current_tree} supplied={args.candidate_tree}"
        )
    generated = now_utc()
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": args.mode,
        "sourceSha": args.source_sha,
        "candidateSha": args.candidate_sha,
        "candidateTree": args.candidate_tree,
        "baseSha": args.base_sha or None,
        "inputDigest": digest,
        "inputFileCount": count,
        "generatedAt": iso(generated),
        "expiresAt": iso(generated + timedelta(days=MAX_AGE_DAYS)),
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF", ""),
        "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA", ""),
        "runId": os.environ.get("GITHUB_RUN_ID", ""),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "actor": os.environ.get("GITHUB_ACTOR", ""),
        "runner": {
            "os": os.environ.get("RUNNER_OS", platform.system()),
            "arch": os.environ.get("RUNNER_ARCH", platform.machine()),
        },
        "buildIdentity": rust_identity(),
        "evidenceClasses": (
            [
                "closed_world_traceability_coverage",
                "signed_v2_qualification_e2e",
                "fenced_holdout_stale_replica_stress",
                "signed_runtime_consumer_e2e",
                "evaluator_line_coverage_threshold",
                "runtime_mapping_and_public_surface_contract",
                "exact_candidate_compile_test_lint_format",
            ]
            if args.mode == "exact-source"
            else [
                "closed_world_traceability_coverage",
                "signed_v2_qualification_e2e",
                "signed_runtime_consumer_e2e",
                "runtime_mapping_and_public_surface_contract",
                "synthetic_merge_compile_test_lint_format",
            ]
        ),
        "traceabilityCases": ["EVAL-01", "EVAL-02", "EVAL-03", "EVAL-04"],
        "authorityDelta": "none",
        "attestation": {
            "mechanism": "github-actions-oidc-artifact-attestation",
            "requiredOnMainPush": True,
        },
    }
    for key, path in DIGEST_FILES.items():
        receipt[key] = file_digest(path)
    if args.mode == "exact-source":
        for label, value in (
            ("coverage", args.coverage),
            ("stress", args.stress),
            ("runtime", args.runtime_log),
        ):
            if not value:
                raise ValueError(f"exact-source evidence requires --{label}")
        receipt["qualificationOutputs"] = {
            "coverage": output_digest(args.coverage),
            "stress": output_digest(args.stress),
            "runtime": output_digest(args.runtime_log),
        }
        receipt["lineCoverageThresholdPct"] = 85
        receipt["stressIterations"] = 8
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def verify(path: Path) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != SCHEMA:
        raise ValueError("unexpected evidence schema")
    if receipt.get("mode") not in {"exact-source", "synthetic-merge"}:
        raise ValueError("invalid evidence mode")
    for key in ("sourceSha", "candidateSha", "candidateTree", "inputDigest"):
        value = receipt.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"missing {key}")
    if receipt.get("candidateTree") != git_text("write-tree"):
        raise ValueError("evidence does not bind the current candidate tree")
    digest, count = input_digest()
    if receipt.get("inputDigest") != digest or receipt.get("inputFileCount") != count:
        raise ValueError("evidence input digest mismatch")
    for key, source in DIGEST_FILES.items():
        if receipt.get(key) != file_digest(source):
            raise ValueError(f"stale {key}")
    if receipt.get("authorityDelta") != "none":
        raise ValueError("qualification evidence may not grant authority")
    expected_classes = (
        {
            "closed_world_traceability_coverage",
            "signed_v2_qualification_e2e",
            "fenced_holdout_stale_replica_stress",
            "signed_runtime_consumer_e2e",
            "evaluator_line_coverage_threshold",
            "runtime_mapping_and_public_surface_contract",
            "exact_candidate_compile_test_lint_format",
        }
        if receipt["mode"] == "exact-source"
        else {
            "closed_world_traceability_coverage",
            "signed_v2_qualification_e2e",
            "signed_runtime_consumer_e2e",
            "runtime_mapping_and_public_surface_contract",
            "synthetic_merge_compile_test_lint_format",
        }
    )
    if set(receipt.get("evidenceClasses", [])) != expected_classes:
        raise ValueError("evidence class coverage mismatch")
    if receipt["mode"] == "exact-source":
        if receipt.get("lineCoverageThresholdPct") != 85:
            raise ValueError("coverage threshold binding mismatch")
        if receipt.get("stressIterations") != 8:
            raise ValueError("stress iteration binding mismatch")
        outputs = receipt.get("qualificationOutputs")
        if not isinstance(outputs, dict) or set(outputs) != {"coverage", "stress", "runtime"}:
            raise ValueError("qualification output bindings missing")
        for label, item in outputs.items():
            if not isinstance(item, dict):
                raise ValueError(f"invalid qualification output: {label}")
            current_output = output_digest(str(item.get("path", "")))
            if item != current_output:
                raise ValueError(f"stale qualification output: {label}")
    if set(receipt.get("traceabilityCases", [])) != {
        "EVAL-01",
        "EVAL-02",
        "EVAL-03",
        "EVAL-04",
    }:
        raise ValueError("learning.eval traceability coverage mismatch")
    generated = parse_time(receipt.get("generatedAt"))
    expires = parse_time(receipt.get("expiresAt"))
    current = now_utc()
    if expires <= generated or expires - generated > timedelta(days=MAX_AGE_DAYS, minutes=1):
        raise ValueError("invalid evidence expiry window")
    if generated > current + timedelta(minutes=5):
        raise ValueError("evidence generated in the future")
    if current > expires:
        raise ValueError("expired evidence")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    emitter = sub.add_parser("emit")
    emitter.add_argument("--mode", choices=("exact-source", "synthetic-merge"), required=True)
    emitter.add_argument("--source-sha", required=True)
    emitter.add_argument("--candidate-sha", required=True)
    emitter.add_argument("--candidate-tree", required=True)
    emitter.add_argument("--base-sha", default="")
    emitter.add_argument("--coverage")
    emitter.add_argument("--stress")
    emitter.add_argument("--runtime-log")
    emitter.add_argument("--output", required=True)
    verifier = sub.add_parser("verify")
    verifier.add_argument("path")

    args = parser.parse_args()
    try:
        if args.command == "emit":
            result = emit(args)
        else:
            result = verify(ROOT / args.path)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "schema": result["schema"], "mode": result["mode"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
