#!/usr/bin/env python3
"""Verify auxiliary learning.eval control-plane bytes against a candidate SHA.

This script is executed from the trusted default-branch checkout by the
`workflow_run` reporter. Candidate files are fetched as untrusted data and must
match the trusted local bytes exactly. It complements the primary allowlist in
`hepta-learning-eval-trusted-entry.py`; it does not execute candidate code or
issue qualification, acceptance, activation, promotion, or release authority.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Callable, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SHA1_RE = re.compile(r"[0-9a-f]{40}")
EXTRA_CONTROL_PLANE_PATHS = (
    ".github/workflows/hepta-learning-eval-control-plane-bootstrap.yml",
    ".github/workflows/hepta-learning-eval-convergence.yml",
    ".github/workflows/hepta-learning-eval-exact.yml",
    ".github/workflows/hepta-learning-eval-trusted-report.yml",
    "scripts/hepta-learning-eval-control-plane-identity.py",
    "scripts/hepta-learning-eval-markdown-links.py",
    "scripts/hepta_learning_eval_projection.py",
    "scripts/hepta_rust_identifiers.py",
    "scripts/learning_eval_status_model.json",
    "scripts/test_hepta_learning_eval_control_plane_identity.py",
    "scripts/test_hepta_learning_eval_projection.py",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_identity(repository: str, source_sha: str) -> None:
    if REPOSITORY_RE.fullmatch(repository) is None:
        raise ValueError("repository must be an exact owner/name identity")
    if SHA1_RE.fullmatch(source_sha) is None:
        raise ValueError("source SHA must be a literal lowercase SHA-1")


def validate_relative_path(path: str) -> Path:
    value = Path(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise ValueError(f"invalid control-plane path: {path}")
    return value


def trusted_file_bytes(path: str, root: Path = ROOT) -> bytes:
    relative = validate_relative_path(path)
    root = root.resolve(strict=True)
    candidate = root.joinpath(relative)
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"trusted control-plane path contains symlink: {path}")
    metadata = candidate.stat()
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_FILE_BYTES:
        raise ValueError(f"trusted control-plane file is invalid: {path}")
    return candidate.read_bytes()


def contents_url(repository: str, path: str, source_sha: str) -> str:
    encoded = "/".join(quote(part, safe="") for part in validate_relative_path(path).parts)
    return (
        f"https://api.github.com/repos/{repository}/contents/{encoded}"
        f"?ref={source_sha}"
    )


def fetch_candidate_file(
    repository: str,
    path: str,
    source_sha: str,
    token: str,
) -> bytes:
    if not token:
        raise ValueError("GitHub token is required")
    request = Request(
        contents_url(repository, path, source_sha),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-learning-eval-control-plane-identity",
        },
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError(f"candidate Contents response is too large: {path}")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or value.get("type") != "file":
        raise ValueError(f"candidate control-plane path is not a regular file: {path}")
    if value.get("encoding") != "base64" or not isinstance(value.get("content"), str):
        raise ValueError(f"candidate control-plane encoding is invalid: {path}")
    try:
        decoded = base64.b64decode("".join(value["content"].split()), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"candidate control-plane base64 is invalid: {path}") from error
    if not 0 < len(decoded) <= MAX_FILE_BYTES:
        raise ValueError(f"candidate control-plane file size is invalid: {path}")
    declared_size = value.get("size")
    if not isinstance(declared_size, int) or declared_size != len(decoded):
        raise ValueError(f"candidate control-plane size disagrees with payload: {path}")
    return decoded


Fetcher = Callable[[str, str, str, str], bytes]


def verify_control_plane(
    repository: str,
    source_sha: str,
    token: str,
    *,
    root: Path = ROOT,
    paths: Iterable[str] = EXTRA_CONTROL_PLANE_PATHS,
    fetcher: Fetcher = fetch_candidate_file,
) -> dict[str, object]:
    validate_identity(repository, source_sha)
    selected = tuple(paths)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("control-plane path inventory is empty or duplicated")
    digests: dict[str, str] = {}
    for path in selected:
        trusted = trusted_file_bytes(path, root=root)
        candidate = fetcher(repository, path, source_sha, token)
        if candidate != trusted:
            raise ValueError(
                "candidate auxiliary qualification control-plane file differs "
                f"from trusted default branch: {path}"
            )
        digests[path] = hashlib.sha256(trusted).hexdigest()
    aggregate = hashlib.sha256(canonical(digests)).hexdigest()
    return {
        "schema": "hepta.learning-eval.auxiliary-control-plane-identity.v1",
        "repository": repository,
        "sourceCommit": source_sha,
        "files": digests,
        "controlPlaneSha256": aggregate,
        "authority": "DENY_ALL",
        "releasePosture": "NO_GO",
        "claims": {
            "sourceQualifiedByThisRun": False,
            "targetHostQualified": False,
            "independentAcceptanceIssued": False,
            "activationAuthorized": False,
            "releaseAuthorized": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        value = verify_control_plane(
            args.repository,
            args.source_sha,
            os.environ.get(args.token_env, ""),
        )
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(value, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
