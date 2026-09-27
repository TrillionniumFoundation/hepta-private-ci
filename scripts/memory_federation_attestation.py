#!/usr/bin/env python3
"""Emit and verify deterministic memory.federation qualification attestations.

The attestation is deliberately split into a payload and an envelope. The payload
contains exact source identities, selected-source file digests, toolchain facts,
and the command contract. GitHub Actions uploads that payload first, then emits
an envelope that binds the returned artifact id and digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any, Iterable

SCHEMA = "hepta.memory-federation.qualification-attestation.v1"
ENVELOPE_SCHEMA = "hepta.memory-federation.qualification-envelope.v1"

QUALIFIED_PATHS = (
    ".github/actions/hepta-synthetic-merge",
    ".github/workflows/blocking-ci.yml",
    ".github/workflows/memory-federation-pr-qualification.yml",
    ".github/workflows/memory-federation-slim-smoke.yml",
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
    "python3 scripts/hepta-implementation-maps.py verify --expected-sha <tested-sha> --expected-tree <tested-tree>",
    "cargo fmt -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-hepta-agentd -p codex-app-server -- --check",
    "cargo test -p codex-hepta-memory-federation --lib",
    "cargo test -p codex-hepta-memory-federation --lib --features legacy-v1",
    "cargo test -p codex-hepta-memory --lib cognitive_runtime_tests",
    "cargo test -p codex-hepta-memory --lib cognitive_federation_tests",
    "cargo test -p codex-hepta-memory-extension --lib cognitive::federation",
    "cargo check -p codex-hepta-agentd -p codex-app-server",
    "cargo clippy -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-app-server --all-targets -- -D warnings",
    "cargo clippy -p codex-hepta-memory-federation --all-targets --features legacy-v1 -- -D warnings",
    "cargo clippy -p codex-hepta-agentd --lib -- -D warnings",
    "git diff --check",
    "test -z \"$(git status --porcelain --untracked-files=no)\"",
)

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_LANES = {"source-head", "deterministic-merge"}
_ALLOWED_CONCLUSIONS = {"success", "failure", "cancelled", "skipped"}
_CLAIM_FIELDS = (
    "productExecutionProved",
    "independentAcceptance",
    "activation",
    "promotion",
    "release",
)


class AttestationError(RuntimeError):
    """Raised for malformed, incomplete, or internally inconsistent evidence."""


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


def _read_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AttestationError(f"cannot read canonical JSON {path}: {error}") from error


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


def _require_mapping(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AttestationError(f"{name} must be an object")
    return value


def _require_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise AttestationError(f"{name} must be a non-empty string")
    return value


def _require_hex(name: str, value: Any, pattern: re.Pattern[str]) -> str:
    selected = _require_string(name, value).lower()
    if not pattern.fullmatch(selected):
        raise AttestationError(f"{name} is not a canonical hexadecimal digest")
    return selected


def _resolve_evidence_file(attestation_path: pathlib.Path, value: Any) -> pathlib.Path:
    relative = pathlib.PurePosixPath(_require_string("evidence path", value))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise AttestationError(f"unsafe evidence path: {relative}")
    path = attestation_path.parent.joinpath(*relative.parts)
    if not path.is_file():
        raise AttestationError(f"referenced evidence file is missing: {path}")
    return path


def _verify_git_identity(
    name: str,
    value: Any,
    *,
    required: bool,
) -> tuple[str | None, str | None]:
    identity = _require_mapping(name, value)
    sha_value = identity.get("sha")
    tree_value = identity.get("tree")
    if sha_value is None:
        if required:
            raise AttestationError(f"{name}.sha is required")
        if tree_value is not None:
            raise AttestationError(f"{name}.tree cannot exist without a commit")
        return None, None
    sha = _require_hex(f"{name}.sha", sha_value, _GIT_SHA_RE)
    tree = _require_hex(f"{name}.tree", tree_value, _GIT_SHA_RE)
    resolved_sha = _git("rev-parse", f"{sha}^{{commit}}")
    if resolved_sha != sha:
        raise AttestationError(f"{name}.sha does not resolve to the recorded commit")
    resolved_tree = _git("rev-parse", f"{sha}^{{tree}}")
    if resolved_tree != tree:
        raise AttestationError(f"{name}.tree does not match the recorded commit")
    return sha, tree


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
    if not _SHA256_RE.fullmatch(artifact_digest):
        raise AttestationError("artifact digest must be a canonical SHA-256 hex value")
    artifact_id = _require_string("artifact id", (args.artifact_id or "").strip())
    if not artifact_id.isdecimal():
        raise AttestationError("artifact id must be a decimal GitHub artifact identifier")

    envelope = {
        "schema": ENVELOPE_SCHEMA,
        "module": "memory.federation",
        "lane": args.lane,
        "conclusion": args.conclusion,
        "payload": {
            "attestationSha256": payload_digest,
            "artifactName": args.artifact_name,
            "artifactId": artifact_id,
            "artifactDigestSha256": artifact_digest,
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


def _verify_common(value: Any) -> tuple[dict[str, Any], str, str]:
    document = _require_mapping("attestation", value)
    if document.get("module") != "memory.federation":
        raise AttestationError("attestation module mismatch")
    lane = _require_string("attestation lane", document.get("lane"))
    if lane not in _ALLOWED_LANES:
        raise AttestationError(f"unsupported attestation lane: {lane}")
    conclusion = _require_string("attestation conclusion", document.get("conclusion"))
    if conclusion not in _ALLOWED_CONCLUSIONS:
        raise AttestationError(f"unsupported attestation conclusion: {conclusion}")
    return document, lane, conclusion


def _verify_payload(path: pathlib.Path, value: Any) -> dict[str, Any]:
    document, lane, conclusion = _verify_common(value)
    if document.get("schema") != SCHEMA:
        raise AttestationError("payload schema mismatch")

    claims = _require_mapping("claimBoundary", document.get("claimBoundary"))
    for field in _CLAIM_FIELDS:
        if claims.get(field) is not False:
            raise AttestationError(f"claimBoundary.{field} must remain false")
    _require_string("claimBoundary.note", claims.get("note"))

    source_sha, source_tree = _verify_git_identity(
        "source", document.get("source"), required=True
    )
    tested_sha, tested_tree = _verify_git_identity(
        "tested", document.get("tested"), required=True
    )
    base_sha, _ = _verify_git_identity("base", document.get("base"), required=False)
    merge_sha, merge_tree = _verify_git_identity(
        "mergeCandidate", document.get("mergeCandidate"), required=False
    )

    head_sha = _git("rev-parse", "HEAD")
    head_tree = _git("rev-parse", "HEAD^{tree}")
    if tested_sha != head_sha or tested_tree != head_tree:
        raise AttestationError("tested identity is not the exact checked-out HEAD")
    if lane == "source-head":
        if source_sha != tested_sha or source_tree != tested_tree:
            raise AttestationError("source-head lane must test the exact source commit")
        if merge_sha is not None or merge_tree is not None:
            raise AttestationError("source-head lane cannot claim a merge candidate")
    else:
        if base_sha is None or merge_sha is None or merge_tree is None:
            raise AttestationError("deterministic-merge lane requires base and merge identities")
        if merge_sha != tested_sha or merge_tree != tested_tree:
            raise AttestationError("deterministic-merge lane must test the recorded merge")
        if source_sha == tested_sha:
            raise AttestationError("deterministic-merge source and merge commits must differ")

    evidence = _require_mapping("evidence", document.get("evidence"))
    source_path = _resolve_evidence_file(path, evidence.get("sourceFiles"))
    commands_path = _resolve_evidence_file(path, evidence.get("commands"))
    source_digest = _require_hex(
        "evidence.sourceFilesSha256", evidence.get("sourceFilesSha256"), _SHA256_RE
    )
    commands_digest = _require_hex(
        "evidence.commandsSha256", evidence.get("commandsSha256"), _SHA256_RE
    )
    if _sha256_bytes(source_path.read_bytes()) != source_digest:
        raise AttestationError("source manifest digest mismatch")
    if _sha256_bytes(commands_path.read_bytes()) != commands_digest:
        raise AttestationError("command manifest digest mismatch")

    recorded_manifest = _read_json(source_path)
    expected_manifest = _source_manifest()
    if recorded_manifest != expected_manifest:
        raise AttestationError("source manifest does not match the exact checkout")
    if evidence.get("qualifiedFileCount") != len(expected_manifest):
        raise AttestationError("qualified source file count mismatch")
    if _read_json(commands_path) != list(COMMANDS):
        raise AttestationError("command manifest does not match the verifier contract")

    toolchain = _require_mapping("toolchain", document.get("toolchain"))
    for field in ("rustc", "cargo", "python"):
        _require_string(f"toolchain.{field}", toolchain.get(field))

    github = _require_mapping("github", document.get("github"))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for field in ("repository", "workflow", "runId", "runAttempt", "job", "ref", "sha", "actor"):
            _require_string(f"github.{field}", github.get(field))
        expected_repository = os.environ.get("GITHUB_REPOSITORY", "")
        if expected_repository and github.get("repository") != expected_repository:
            raise AttestationError("GitHub repository identity mismatch")
        expected_run = os.environ.get("GITHUB_RUN_ID", "")
        if expected_run and github.get("runId") != expected_run:
            raise AttestationError("GitHub run identity mismatch")

    if conclusion == "success" and not expected_manifest:
        raise AttestationError("successful qualification cannot have an empty source manifest")
    return document


def _verify_envelope(
    path: pathlib.Path,
    value: Any,
    payload_path: pathlib.Path | None,
) -> dict[str, Any]:
    document, lane, conclusion = _verify_common(value)
    if document.get("schema") != ENVELOPE_SCHEMA:
        raise AttestationError("envelope schema mismatch")
    if payload_path is None or not payload_path.is_file():
        raise AttestationError("envelope verification requires the payload attestation")
    payload_document = _verify_payload(payload_path, _read_json(payload_path))
    if payload_document.get("lane") != lane:
        raise AttestationError("envelope lane does not match its payload")
    if payload_document.get("conclusion") != conclusion:
        raise AttestationError("envelope conclusion does not match its payload")

    payload = _require_mapping("payload", document.get("payload"))
    recorded_payload_digest = _require_hex(
        "payload.attestationSha256", payload.get("attestationSha256"), _SHA256_RE
    )
    if _sha256_bytes(payload_path.read_bytes()) != recorded_payload_digest:
        raise AttestationError("envelope payload digest mismatch")
    _require_string("payload.artifactName", payload.get("artifactName"))
    artifact_id = _require_string("payload.artifactId", payload.get("artifactId"))
    if not artifact_id.isdecimal():
        raise AttestationError("payload.artifactId must be decimal")
    _require_hex(
        "payload.artifactDigestSha256", payload.get("artifactDigestSha256"), _SHA256_RE
    )

    github = _require_mapping("github", document.get("github"))
    payload_github = _require_mapping("payload github", payload_document.get("github"))
    for field in ("repository", "runId", "runAttempt"):
        if github.get(field) != payload_github.get(field):
            raise AttestationError(f"envelope GitHub {field} does not match its payload")
    return document


def verify(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.path)
    value = _read_json(path)
    schema = value.get("schema") if isinstance(value, dict) else None
    if schema == SCHEMA:
        _verify_payload(path, value)
    elif schema == ENVELOPE_SCHEMA:
        payload = pathlib.Path(args.payload) if args.payload else None
        _verify_envelope(path, value, payload)
    else:
        raise AttestationError(f"unsupported attestation schema: {schema!r}")
    return 0


def _expect_failure(action: Any, description: str) -> None:
    try:
        action()
    except AttestationError:
        return
    raise AttestationError(f"self-test did not reject {description}")


def self_test(_args: argparse.Namespace) -> int:
    head = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD^")
    with tempfile.TemporaryDirectory(prefix="memory-federation-attestation-") as directory:
        root = pathlib.Path(directory)
        payload_dir = root / "payload"
        emit_payload(
            argparse.Namespace(
                output=str(payload_dir),
                lane="source-head",
                conclusion="success",
                source_sha=head,
                tested_sha=head,
                tested_tree=_git("rev-parse", "HEAD^{tree}"),
                base_sha=parent,
                merge_sha=None,
                merge_tree=None,
            )
        )
        payload_path = payload_dir / "attestation.json"
        verify(argparse.Namespace(path=str(payload_path), payload=None))

        commands_path = payload_dir / "commands.json"
        original_commands = commands_path.read_bytes()
        commands_path.write_text("[]\n", encoding="utf-8")
        _expect_failure(
            lambda: verify(argparse.Namespace(path=str(payload_path), payload=None)),
            "a tampered command manifest",
        )
        commands_path.write_bytes(original_commands)

        envelope_path = root / "envelope.json"
        emit_envelope(
            argparse.Namespace(
                output=str(envelope_path),
                payload=str(payload_path),
                lane="source-head",
                conclusion="success",
                artifact_name="self-test-artifact",
                artifact_id="1",
                artifact_digest="ab" * 32,
            )
        )
        verify(argparse.Namespace(path=str(envelope_path), payload=str(payload_path)))

        envelope = _read_json(envelope_path)
        envelope["payload"]["attestationSha256"] = "cd" * 32
        _write_json(envelope_path, envelope)
        _expect_failure(
            lambda: verify(
                argparse.Namespace(path=str(envelope_path), payload=str(payload_path))
            ),
            "a tampered envelope payload binding",
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    payload = subparsers.add_parser("emit-payload")
    payload.add_argument("--output", required=True)
    payload.add_argument("--lane", required=True, choices=sorted(_ALLOWED_LANES))
    payload.add_argument("--conclusion", required=True, choices=sorted(_ALLOWED_CONCLUSIONS))
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
    envelope.add_argument("--lane", required=True, choices=sorted(_ALLOWED_LANES))
    envelope.add_argument("--conclusion", required=True, choices=sorted(_ALLOWED_CONCLUSIONS))
    envelope.add_argument("--artifact-name", required=True)
    envelope.add_argument("--artifact-id", required=True)
    envelope.add_argument("--artifact-digest", required=True)
    envelope.set_defaults(func=emit_envelope)

    verifier = subparsers.add_parser("verify")
    verifier.add_argument("path")
    verifier.add_argument("--payload")
    verifier.set_defaults(func=verify)

    self_tester = subparsers.add_parser("self-test")
    self_tester.set_defaults(func=self_test)
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
