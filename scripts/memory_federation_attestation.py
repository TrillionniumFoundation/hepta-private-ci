#!/usr/bin/env python3
"""Emit deterministic memory.federation qualification attestations.

The attestation is deliberately split into a payload and an envelope.  The payload
contains exact source identities, selected-source file digests, toolchain facts,
and the command contract.  GitHub Actions uploads that payload first, then emits
an envelope that binds the returned artifact id and digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Any, Iterable

SCHEMA = "hepta.memory-federation.qualification-attestation.v1"
ENVELOPE_SCHEMA = "hepta.memory-federation.qualification-envelope.v1"

QUALIFIED_PATHS = (
    ".github/actions/hepta-synthetic-merge",
    ".github/workflows/blocking-ci.yml",
    ".github/workflows/memory-federation-v2-final-verify.yml",
    "codex-rs/hepta-memory-federation",
    "codex-rs/hepta-memory",
    "codex-rs/hepta-agentd",
    "codex-rs/ext/hepta-memory",
    "codex-rs/app-server",
    "docs/modules/memory.federation",
    "qualification/memory-federation",
    "qualification/module-execution-dossiers/detail/memory.federation.md",
    "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json",
    "scripts/hepta-implementation-maps.py",
    "scripts/memory_federation_attestation.py",
)

COMMANDS = (
    "python3 scripts/hepta-implementation-maps.py verify",
    "cargo fmt -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-hepta-agentd -p codex-app-server -- --check",
    "cargo test -p codex-hepta-memory-federation --lib",
    "cargo test -p codex-hepta-memory-federation --features legacy-v1 --lib",
    "cargo test -p codex-hepta-memory --lib cognitive_runtime_tests",
    "cargo test -p codex-hepta-memory --lib cognitive_federation_tests",
    "cargo test -p codex-hepta-memory-extension --lib cognitive::federation",
    "cargo check -p codex-hepta-agentd -p codex-app-server",
    "cargo clippy -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-app-server --all-targets -- -D warnings",
    "cargo clippy -p codex-hepta-agentd --lib -- -D warnings",
    "git diff --check",
    "test -z \"$(git status --porcelain --untracked-files=no)\"",
)


class AttestationError(RuntimeError):
    """Raised for malformed or incomplete qualification evidence."""


def _run(*argv: str, check: bool = True) -> str:
    completed = subprocess.run(
        argv,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and completed.returncode != 0:
        raise AttestationError(
            f"{' '.join(argv)} failed with {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _git(*argv: str) -> str:
    return _run("git", *argv)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _write_json(path: pathlib.Path, value: Any) -> str:
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def _optional_git_tree(commit: str | None) -> str | None:
    if not commit:
        return None
    return _git("rev-parse", f"{commit}^{{tree}}")


def _tracked_files() -> list[str]:
    output = _run("git", "ls-files", "-z", "--", *QUALIFIED_PATHS)
    return sorted(path for path in output.split("\0") if path)


def _source_manifest() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in _tracked_files():
        path = pathlib.Path(relative)
        if not path.is_file():
            raise AttestationError(f"qualified source is not a regular file: {relative}")
        data = path.read_bytes()
        rows.append(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": _sha256_bytes(data),
            }
        )
    if not rows:
        raise AttestationError("qualified source manifest is empty")
    return rows


def _toolchain() -> dict[str, str]:
    return {
        "rustc": _run("rustc", "-Vv", check=False),
        "cargo": _run("cargo", "-V", check=False),
        "python": _run(sys.executable, "--version", check=False),
        "runnerOs": os.environ.get("RUNNER_OS", ""),
        "runnerArch": os.environ.get("RUNNER_ARCH", ""),
        "runnerName": os.environ.get("RUNNER_NAME", ""),
    }


def _identity(value: str | None, fallback: str) -> str:
    selected = (value or "").strip()
    return selected if selected else fallback


def emit_payload(args: argparse.Namespace) -> int:
    output = pathlib.Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    tested_sha = _identity(args.tested_sha, _git("rev-parse", "HEAD"))
    tested_tree = _identity(args.tested_tree, _git("rev-parse", "HEAD^{tree}"))
    source_sha = _identity(args.source_sha, tested_sha)
    source_tree = _optional_git_tree(source_sha)

    manifest = _source_manifest()
    manifest_digest = _write_json(output / "source-files.json", manifest)
    commands_digest = _write_json(output / "commands.json", list(COMMANDS))

    base_sha = (args.base_sha or "").strip() or None
    merge_sha = (args.merge_sha or "").strip() or None
    merge_tree = (args.merge_tree or "").strip() or None
    if merge_sha and not merge_tree:
        merge_tree = _optional_git_tree(merge_sha)

    attestation = {
        "schema": SCHEMA,
        "module": "memory.federation",
        "lane": args.lane,
        "conclusion": args.conclusion,
        "claimBoundary": {
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
            "note": (
                "This execution receipt proves only the commands and source identities "
                "recorded here. Promotion fields remain false until a reviewed repository "
                "change binds a successful exact-head and deterministic-merge receipt."
            ),
        },
        "source": {
            "sha": source_sha,
            "tree": source_tree,
        },
        "tested": {
            "sha": tested_sha,
            "tree": tested_tree,
        },
        "base": {
            "sha": base_sha,
            "tree": _optional_git_tree(base_sha),
        },
        "mergeCandidate": {
            "sha": merge_sha,
            "tree": merge_tree,
        },
        "evidence": {
            "sourceFiles": "source-files.json",
            "sourceFilesSha256": manifest_digest,
            "commands": "commands.json",
            "commandsSha256": commands_digest,
            "qualifiedFileCount": len(manifest),
        },
        "toolchain": _toolchain(),
        "github": {
            "repository": os.environ.get("GITHUB_REPOSITORY", ""),
            "workflow": os.environ.get("GITHUB_WORKFLOW", ""),
            "eventName": os.environ.get("GITHUB_EVENT_NAME", ""),
            "runId": os.environ.get("GITHUB_RUN_ID", ""),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            "job": os.environ.get("GITHUB_JOB", ""),
            "ref": os.environ.get("GITHUB_REF", ""),
            "sha": os.environ.get("GITHUB_SHA", ""),
            "actor": os.environ.get("GITHUB_ACTOR", ""),
        },
    }
    digest = _write_json(output / "attestation.json", attestation)
    (output / "attestation.sha256").write_text(
        f"{digest}  attestation.json\n", encoding="utf-8"
    )
    return 0


def emit_envelope(args: argparse.Namespace) -> int:
    payload_path = pathlib.Path(args.payload)
    if not payload_path.is_file():
        raise AttestationError(f"payload attestation missing: {payload_path}")
    payload_digest = _sha256_bytes(payload_path.read_bytes())

    artifact_digest = (args.artifact_digest or "").strip().lower()
    if artifact_digest.startswith("sha256:"):
        artifact_digest = artifact_digest.removeprefix("sha256:")
    if artifact_digest and len(artifact_digest) != 64:
        raise AttestationError("artifact digest must be a 64-character SHA-256 hex value")
    if artifact_digest and any(ch not in "0123456789abcdef" for ch in artifact_digest):
        raise AttestationError("artifact digest is not hexadecimal")

    envelope = {
        "schema": ENVELOPE_SCHEMA,
        "module": "memory.federation",
        "lane": args.lane,
        "conclusion": args.conclusion,
        "payload": {
            "attestationSha256": payload_digest,
            "artifactName": args.artifact_name,
            "artifactId": (args.artifact_id or "").strip(),
            "artifactDigestSha256": artifact_digest or None,
        },
        "github": {
            "repository": os.environ.get("GITHUB_REPOSITORY", ""),
            "runId": os.environ.get("GITHUB_RUN_ID", ""),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        },
    }
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = _write_json(output, envelope)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="utf-8"
    )
    return 0


def verify(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.path)
    value = json.loads(path.read_text(encoding="utf-8"))
    schema = value.get("schema")
    if schema not in {SCHEMA, ENVELOPE_SCHEMA}:
        raise AttestationError(f"unsupported attestation schema: {schema!r}")
    if value.get("module") != "memory.federation":
        raise AttestationError("attestation module mismatch")
    if not isinstance(value.get("lane"), str) or not value["lane"]:
        raise AttestationError("attestation lane is missing")
    if not isinstance(value.get("conclusion"), str) or not value["conclusion"]:
        raise AttestationError("attestation conclusion is missing")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    payload = subparsers.add_parser("emit-payload")
    payload.add_argument("--output", required=True)
    payload.add_argument("--lane", required=True)
    payload.add_argument("--conclusion", required=True)
    payload.add_argument("--source-sha")
    payload.add_argument("--tested-sha")
    payload.add_argument("--tested-tree")
    payload.add_argument("--base-sha")
    payload.add_argument("--merge-sha")
    payload.add_argument("--merge-tree")
    payload.set_defaults(func=emit_payload)

    envelope = subparsers.add_parser("emit-envelope")
    envelope.add_argument("--output", required=True)
    envelope.add_argument("--payload", required=True)
    envelope.add_argument("--lane", required=True)
    envelope.add_argument("--conclusion", required=True)
    envelope.add_argument("--artifact-name", required=True)
    envelope.add_argument("--artifact-id")
    envelope.add_argument("--artifact-digest")
    envelope.set_defaults(func=emit_envelope)

    verifier = subparsers.add_parser("verify")
    verifier.add_argument("path")
    verifier.set_defaults(func=verify)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except (AttestationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"memory federation attestation error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
