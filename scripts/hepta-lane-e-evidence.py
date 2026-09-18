#!/usr/bin/env python3
"""Emit and verify exact-candidate Lane E CI provenance receipts.

The receipt is intentionally unsigned unless a separate attestation service
adds a verifiable signature. Repository CI must never invent a signer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATIC_INPUTS = [
    Path("codex-rs/Cargo.lock"),
    Path("codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md"),
    Path("codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md"),
    Path("codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md"),
    Path("codex-rs/hepta-intelligence/src/evaluated_shadow.rs"),
    Path("codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs"),
    Path("codex-rs/hepta-shadow-qualification/src/lane_e_closure_tests.rs"),
    Path("docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"),
    Path("qualification/lane-e/TEST_TRACEABILITY.json"),
]
REVALIDATE_HOURS = 24 * 30
MAX_CLOCK_SKEW = dt.timedelta(minutes=5)
SCHEMA = "hepta.lane-e-ci-evidence.v2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_version(*command: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout.strip()


def canonical_digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def utc_now() -> dt.datetime:
    override = os.environ.get("HEPTA_EVIDENCE_GENERATED_AT")
    if override:
        value = dt.datetime.fromisoformat(override.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_hex_sha(value: str, label: str, allow_empty: bool = False) -> None:
    if allow_empty and not value:
        return
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ValueError(f"{label} must be a 40-character git SHA")


def parse_utc(value: Any, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO-8601 UTC timestamp")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def git_value(*args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout.strip()


def artifact_path(value: str) -> tuple[Path, str]:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"evidence artifact must stay inside repository root: {value}") from error
    return resolved, relative.as_posix()


def emit(args: argparse.Namespace) -> int:
    require_hex_sha(args.source_sha, "source_sha")
    require_hex_sha(args.candidate_sha, "candidate_sha")
    require_hex_sha(args.tree_sha, "tree_sha")
    require_hex_sha(args.base_sha, "base_sha", allow_empty=True)

    inputs: dict[str, str] = {}
    for relative in STATIC_INPUTS:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(relative)
        inputs[relative.as_posix()] = sha256_file(path)

    outputs: dict[str, dict[str, Any]] = {}
    for label, value in [
        ("coverage", args.coverage),
        ("stressAudit", args.stress),
        ("e2eLog", args.e2e),
    ]:
        if not value:
            continue
        path, relative = artifact_path(value)
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"missing or empty {label}: {path}")
        outputs[label] = {
            "path": relative,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    generated = utc_now()
    expires = generated + dt.timedelta(hours=REVALIDATE_HOURS)
    build = {
        "sourceSha": args.source_sha,
        "candidateSha": args.candidate_sha,
        "treeSha": args.tree_sha,
        "rustc": command_version("rustc", "--version", "--verbose"),
        "cargo": command_version("cargo", "--version", "--verbose"),
        "inputs": inputs,
    }
    receipt = {
        "schema": SCHEMA,
        "mode": args.mode,
        "sourceSha": args.source_sha,
        "candidateSha": args.candidate_sha,
        "treeSha": args.tree_sha,
        "baseSha": args.base_sha or None,
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"),
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerOs": os.environ.get("RUNNER_OS"),
        "generatedAtUtc": iso(generated),
        "expiresAtUtc": iso(expires),
        "revalidateAfterHours": REVALIDATE_HOURS,
        "attestationStatus": "unsigned_ci_receipt",
        "signer": None,
        "signature": None,
        "buildIdentity": canonical_digest(build),
        "toolchain": {"rustc": build["rustc"], "cargo": build["cargo"]},
        "inputs": inputs,
        "outputs": outputs,
    }
    receipt["receiptDigest"] = canonical_digest(receipt)

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "receiptDigest": receipt["receiptDigest"]}))
    return 0


def verify(args: argparse.Namespace) -> int:
    path = Path(args.receipt)
    if not path.is_absolute():
        path = ROOT / path
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA:
        raise ValueError("unexpected evidence schema")

    recorded = value.get("receiptDigest")
    copy = dict(value)
    copy.pop("receiptDigest", None)
    if canonical_digest(copy) != recorded:
        raise ValueError("receipt digest mismatch")
    if value.get("attestationStatus") != "unsigned_ci_receipt":
        raise ValueError("repository receipt must not claim an unverified signer")
    if value.get("signer") is not None or value.get("signature") is not None:
        raise ValueError("unsigned repository receipt cannot contain signer/signature")

    source_sha = value.get("sourceSha")
    candidate_sha = value.get("candidateSha")
    tree_sha = value.get("treeSha")
    base_sha = value.get("baseSha")
    if not isinstance(source_sha, str) or not isinstance(candidate_sha, str) or not isinstance(
        tree_sha, str
    ):
        raise ValueError("missing git identity")
    require_hex_sha(source_sha, "sourceSha")
    require_hex_sha(candidate_sha, "candidateSha")
    require_hex_sha(tree_sha, "treeSha")
    if base_sha is not None:
        if not isinstance(base_sha, str):
            raise ValueError("baseSha must be a git SHA or null")
        require_hex_sha(base_sha, "baseSha")

    git_value("cat-file", "-e", f"{source_sha}^{{commit}}")
    git_value("cat-file", "-e", f"{candidate_sha}^{{commit}}")
    observed_tree = git_value("rev-parse", f"{candidate_sha}^{{tree}}")
    if observed_tree != tree_sha:
        raise ValueError("candidate tree mismatch")

    mode = value.get("mode")
    if mode == "exact-head":
        if candidate_sha != source_sha:
            raise ValueError("exact-head candidate must equal source")
        if git_value("rev-parse", f"{source_sha}^{{tree}}") != tree_sha:
            raise ValueError("source tree mismatch")
    elif mode == "synthetic-merge":
        if base_sha is None:
            raise ValueError("synthetic merge requires baseSha")
        parents = git_value("rev-list", "--parents", "-n", "1", candidate_sha).split()
        if parents != [candidate_sha, base_sha, source_sha]:
            raise ValueError("synthetic merge ordered parents mismatch")
    else:
        raise ValueError("unexpected evidence mode")

    generated = parse_utc(value.get("generatedAtUtc"), "generatedAtUtc")
    expires = parse_utc(value.get("expiresAtUtc"), "expiresAtUtc")
    if value.get("revalidateAfterHours") != REVALIDATE_HOURS:
        raise ValueError("unexpected evidence revalidation policy")
    if expires != generated + dt.timedelta(hours=REVALIDATE_HOURS):
        raise ValueError("evidence expiry does not match revalidation policy")
    now = utc_now()
    if generated > now + MAX_CLOCK_SKEW:
        raise ValueError("evidence generation time is in the future")
    if now > expires:
        raise ValueError("evidence receipt expired")

    context_fields = ("repository", "workflow", "workflowRef", "runId", "runAttempt", "runnerOs")
    if any(not isinstance(value.get(field), str) or not value.get(field) for field in context_fields):
        raise ValueError("missing GitHub Actions provenance context")
    current_repository = os.environ.get("GITHUB_REPOSITORY")
    if current_repository and current_repository != value["repository"]:
        raise ValueError("repository context mismatch")

    inputs = value.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {p.as_posix() for p in STATIC_INPUTS}:
        raise ValueError("unexpected evidence input set")
    for relative in STATIC_INPUTS:
        expected = inputs.get(relative.as_posix())
        if expected != sha256_file(ROOT / relative):
            raise ValueError(f"input digest mismatch: {relative}")

    outputs = value.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise ValueError("evidence outputs are missing")
    for label, metadata in outputs.items():
        if not isinstance(label, str) or not isinstance(metadata, dict):
            raise ValueError("invalid output record")
        relative = metadata.get("path")
        digest = metadata.get("sha256")
        size = metadata.get("bytes")
        if (
            not isinstance(relative, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(size, int)
            or size <= 0
        ):
            raise ValueError("invalid output metadata")
        artifact, normalized = artifact_path(relative)
        if normalized != relative or not artifact.is_file():
            raise ValueError(f"output path mismatch: {label}")
        if artifact.stat().st_size != size or sha256_file(artifact) != digest:
            raise ValueError(f"output digest mismatch: {label}")

    toolchain = value.get("toolchain")
    if not isinstance(toolchain, dict) or not isinstance(toolchain.get("rustc"), str) or not isinstance(
        toolchain.get("cargo"), str
    ):
        raise ValueError("missing toolchain identity")
    build = {
        "sourceSha": source_sha,
        "candidateSha": candidate_sha,
        "treeSha": tree_sha,
        "rustc": toolchain["rustc"],
        "cargo": toolchain["cargo"],
        "inputs": inputs,
    }
    if value.get("buildIdentity") != canonical_digest(build):
        raise ValueError("build identity mismatch")

    print(json.dumps({"ok": True, "receiptDigest": recorded}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    emit_parser = sub.add_parser("emit")
    emit_parser.add_argument("--mode", choices=("exact-head", "synthetic-merge"), required=True)
    emit_parser.add_argument("--source-sha", required=True)
    emit_parser.add_argument("--candidate-sha", required=True)
    emit_parser.add_argument("--tree-sha", required=True)
    emit_parser.add_argument("--base-sha", default="")
    emit_parser.add_argument("--coverage")
    emit_parser.add_argument("--stress")
    emit_parser.add_argument("--e2e")
    emit_parser.add_argument("--output", required=True)
    emit_parser.set_defaults(func=emit)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--receipt", required=True)
    verify_parser.set_defaults(func=verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        sys.exit(1)
