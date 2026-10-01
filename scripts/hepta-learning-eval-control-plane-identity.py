#!/usr/bin/env python3
"""Verify the complete learning.eval control-plane against a candidate SHA.

This script is executed from the trusted default-branch checkout by the
`workflow_run` reporter. Candidate files and the candidate workflow inventory
are fetched as untrusted data and must match the trusted checkout exactly. It
does not execute candidate code or issue qualification, acceptance, activation,
promotion, or release authority.
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
import subprocess
import sys
from typing import Callable, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 1024 * 1024
MAX_FILE_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DIRECTORY_RESPONSE_BYTES = 8 * 1024 * 1024
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SHA1_RE = re.compile(r"[0-9a-f]{40}")
WORKFLOW_DIRECTORY = ".github/workflows"
WORKFLOW_PREFIX = "hepta-learning-eval-"
WORKFLOW_SUFFIX = ".yml"
PYTHON_MODULE_SUFFIXES = (".py", ".pyc", ".pyo", ".so", ".pyd")
AUXILIARY_CONTROL_PLANE_PATHS = (
    "scripts/just-shell.py",
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


def unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("Git metadata contains a duplicate JSON key")
        value[key] = child
    return value


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


def trusted_learning_eval_workflow_paths(root: Path = ROOT) -> tuple[str, ...]:
    root = root.resolve(strict=True)
    directory = root / WORKFLOW_DIRECTORY
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("trusted workflow directory is missing, invalid, or a symlink")
    selected: list[str] = []
    for candidate in sorted(directory.iterdir(), key=lambda path: path.name):
        if not (
            candidate.name.startswith(WORKFLOW_PREFIX)
            and candidate.name.endswith(WORKFLOW_SUFFIX)
        ):
            continue
        relative = candidate.relative_to(root).as_posix()
        trusted_file_bytes(relative, root=root)
        selected.append(relative)
    if not selected:
        raise ValueError("trusted learning.eval workflow inventory is empty")
    return tuple(selected)


def contents_url(repository: str, path: str, source_sha: str) -> str:
    encoded = "/".join(quote(part, safe="") for part in validate_relative_path(path).parts)
    return (
        f"https://api.github.com/repos/{repository}/contents/{encoded}"
        f"?ref={source_sha}"
    )


def github_request(url: str, token: str) -> Request:
    if not token:
        raise ValueError("GitHub token is required")
    return Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-learning-eval-control-plane-identity",
        },
    )


def read_response(request: Request, maximum: int) -> bytes:
    with urlopen(request, timeout=30) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("GitHub Contents response is too large")
    return raw


def fetch_candidate_file(
    repository: str,
    path: str,
    source_sha: str,
    token: str,
) -> bytes:
    raw = read_response(
        github_request(contents_url(repository, path, source_sha), token),
        MAX_FILE_RESPONSE_BYTES,
    )
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or value.get("type") != "file":
        raise ValueError(f"candidate control-plane path is not a regular file: {path}")
    if value.get("path") != path:
        raise ValueError(f"candidate control-plane path identity changed: {path}")
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


def fetch_candidate_workflow_paths(
    repository: str,
    source_sha: str,
    token: str,
) -> tuple[str, ...]:
    raw = read_response(
        github_request(
            contents_url(repository, WORKFLOW_DIRECTORY, source_sha),
            token,
        ),
        MAX_DIRECTORY_RESPONSE_BYTES,
    )
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, list):
        raise ValueError("candidate workflow inventory is not a directory listing")
    selected: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("candidate workflow inventory contains a non-object")
        name = entry.get("name")
        if not isinstance(name, str) or not (
            name.startswith(WORKFLOW_PREFIX) and name.endswith(WORKFLOW_SUFFIX)
        ):
            continue
        path = f"{WORKFLOW_DIRECTORY}/{name}"
        if entry.get("type") != "file" or entry.get("path") != path:
            raise ValueError(f"candidate learning.eval workflow is not a regular file: {path}")
        if path in seen:
            raise ValueError(f"candidate workflow inventory contains a duplicate: {path}")
        seen.add(path)
        selected.append(path)
    if not selected:
        raise ValueError("candidate learning.eval workflow inventory is empty")
    return tuple(sorted(selected))


def python_import_layout(entries: Iterable[tuple[str, str, str]]) -> tuple[tuple[str, str], ...]:
    """Bind committed import paths and kinds without freezing unrelated file bodies.

    Python launched from the repository or codex-rs can reach namespace packages,
    so Python files below those import roots must be included as well as scripts.
    """
    selected: dict[str, str] = {}
    seen: set[str] = set()
    for path, mode, kind in entries:
        parts = path.split("/")
        if not path or "\\" in path or not path.isprintable() or any(
            part in ("", ".", "..") for part in parts
        ):
            raise ValueError("Git tree contains a noncanonical import path")
        if path in seen:
            raise ValueError("Git tree contains a duplicate path")
        seen.add(path)
        if not isinstance(kind, str) or not isinstance(mode, str) or kind not in {
            "blob", "tree", "commit",
        } or mode not in {
            "100644", "100755", "120000", "040000", "160000",
        } or (kind, mode) not in {
            ("blob", "100644"), ("blob", "100755"), ("blob", "120000"),
            ("tree", "040000"), ("commit", "160000"),
        }:
            raise ValueError("Git tree entry kind and mode disagree")
        import_root_path = path.startswith("scripts/") or len(parts) == 1 or (
            len(parts) == 2 and parts[0] == "codex-rs"
        )
        if mode in {"120000", "160000"} and import_root_path:
            raise ValueError("Python import root contains an opaque symlink or submodule")
        if path.endswith(PYTHON_MODULE_SUFFIXES):
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("Python module path is not a regular committed file")
            selected[path] = mode
    return tuple(sorted(selected.items()))


def trusted_python_import_layout(root: Path = ROOT) -> tuple[tuple[str, str], ...]:
    with subprocess.Popen(
        ["git", "-C", str(root), "ls-tree", "-rz", "--full-tree", "HEAD"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as process:
        assert process.stdout is not None
        raw = process.stdout.read(MAX_DIRECTORY_RESPONSE_BYTES + 1)
        if len(raw) > MAX_DIRECTORY_RESPONSE_BYTES:
            process.kill()
            process.wait()
            raise ValueError("trusted Git tree exceeds the inventory size bound")
        if process.wait(timeout=30) != 0:
            raise ValueError("trusted committed Python inventory is unavailable")
    if not raw or not raw.endswith(b"\0"):
        raise ValueError("trusted Git tree inventory is empty or incomplete")
    entries = []
    for item in raw[:-1].decode("utf-8").split("\0"):
        metadata, separator, path = item.partition("\t")
        fields = metadata.split(" ")
        if not separator or len(fields) != 3 or SHA1_RE.fullmatch(fields[2]) is None:
            raise ValueError("trusted Git tree inventory entry is malformed")
        entries.append((path, fields[0], fields[1]))
    return python_import_layout(entries)


def fetch_candidate_python_import_layout(
    repository: str, source_sha: str, token: str,
) -> tuple[tuple[str, str], ...]:
    validate_identity(repository, source_sha)
    base = f"https://api.github.com/repos/{repository}/git"
    commit = json.loads(read_response(
        github_request(f"{base}/commits/{source_sha}", token), MAX_FILE_RESPONSE_BYTES,
    ).decode("utf-8"), object_pairs_hook=unique_json_object)
    tree = commit.get("tree") if isinstance(commit, dict) else None
    tree_sha = tree.get("sha") if isinstance(tree, dict) else None
    if not isinstance(commit, dict) or commit.get("sha") != source_sha or not isinstance(tree_sha, str) or (
        SHA1_RE.fullmatch(tree_sha) is None
    ):
        raise ValueError("candidate commit/tree identity is invalid")
    value = json.loads(read_response(
        github_request(f"{base}/trees/{tree_sha}?recursive=1", token),
        MAX_DIRECTORY_RESPONSE_BYTES,
    ).decode("utf-8"), object_pairs_hook=unique_json_object)
    if not isinstance(value, dict) or value.get("sha") != tree_sha or (
        value.get("truncated") is not False
    ) or not isinstance(value.get("tree"), list):
        raise ValueError("candidate Git tree inventory is incomplete or has the wrong identity")
    entries = []
    for entry in value["tree"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or (
            not isinstance(entry.get("sha"), str)
            or SHA1_RE.fullmatch(entry["sha"]) is None
        ):
            raise ValueError("candidate Git tree entry is malformed")
        entries.append((entry["path"], entry.get("mode"), entry.get("type")))
    return python_import_layout(entries)


Fetcher = Callable[[str, str, str, str], bytes]
WorkflowFetcher = Callable[[str, str, str], tuple[str, ...]]
ImportLayoutFetcher = Callable[[str, str, str], tuple[tuple[str, str], ...]]


def verify_control_plane(
    repository: str,
    source_sha: str,
    token: str,
    *,
    root: Path = ROOT,
    paths: Iterable[str] = AUXILIARY_CONTROL_PLANE_PATHS,
    fetcher: Fetcher = fetch_candidate_file,
    workflow_fetcher: WorkflowFetcher = fetch_candidate_workflow_paths,
    import_layout_fetcher: ImportLayoutFetcher = fetch_candidate_python_import_layout,
) -> dict[str, object]:
    validate_identity(repository, source_sha)
    trusted_workflows = trusted_learning_eval_workflow_paths(root)
    candidate_workflows = workflow_fetcher(repository, source_sha, token)
    if candidate_workflows != trusted_workflows:
        raise ValueError(
            "candidate learning.eval workflow inventory differs from trusted default branch: "
            f"trusted={list(trusted_workflows)!r} candidate={list(candidate_workflows)!r}"
        )
    trusted_imports = trusted_python_import_layout(root)
    candidate_imports = import_layout_fetcher(repository, source_sha, token)
    if candidate_imports != trusted_imports:
        raise ValueError("candidate Python import layout differs from trusted committed source")
    selected = trusted_workflows + tuple(paths)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("control-plane path inventory is empty or duplicated")
    digests: dict[str, str] = {}
    for path in selected:
        trusted = trusted_file_bytes(path, root=root)
        candidate = fetcher(repository, path, source_sha, token)
        if candidate != trusted:
            raise ValueError(
                "candidate qualification control-plane file differs "
                f"from trusted default branch: {path}"
            )
        digests[path] = hashlib.sha256(trusted).hexdigest()
    aggregate = hashlib.sha256(canonical({
        "files": digests, "pythonImportLayout": trusted_imports,
    })).hexdigest()
    return {
        "schema": "hepta.learning-eval.control-plane-identity.v2",
        "repository": repository,
        "sourceCommit": source_sha,
        "workflowInventory": list(trusted_workflows),
        "pythonImportLayout": trusted_imports,
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
        # The exception may originate from a request carrying an Authorization
        # header. Never serialize or log the exception object on this boundary.
        print(
            f"{type(error).__name__}: control-plane verification failed",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
