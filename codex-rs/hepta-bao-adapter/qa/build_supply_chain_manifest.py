#!/usr/bin/env python3
"""Build unsigned source/SBOM evidence from a pristine exact Git candidate."""
from __future__ import annotations

import argparse
import fnmatch
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
ADAPTER_MANIFEST = ROOT / "codex-rs/hepta-bao-adapter/Cargo.toml"
METADATA_COMMAND = [
    "cargo", "metadata", "--locked", "--offline", "--format-version", "1",
    "--manifest-path", str(ADAPTER_MANIFEST),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def source_digest(path: Path, source_sha: str) -> str:
    relative = path.relative_to(ROOT).as_posix()
    return hashlib.sha256(git_bytes("show", f"{source_sha}:{relative}")).hexdigest()


def digest_paths(paths: Iterable[Path], source_sha: str) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        relative = path.relative_to(ROOT).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        payload = git_bytes("show", f"{source_sha}:{relative.decode()}")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


@lru_cache(maxsize=2)
def committed_paths(source_sha: str) -> tuple[str, ...]:
    return tuple(path for path in git_bytes(
        "ls-tree", "-r", "-z", "--name-only", source_sha
    ).decode().split("\0") if path)


def matches_path(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern:
        return not path
    if pattern[0] == "**":
        return matches_path(path, pattern[1:]) or bool(path and matches_path(path[1:], pattern))
    return bool(path and fnmatch.fnmatchcase(path[0], pattern[0])
                and matches_path(path[1:], pattern[1:]))


def files(pattern: str, source_sha: str) -> list[Path]:
    return [ROOT / path for path in committed_paths(source_sha)
            if matches_path(tuple(path.split("/")), tuple(pattern.split("/")))]


def git(*args: str) -> str:
    return git_bytes(*args).decode().strip()


def source_identity() -> tuple[str, str]:
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("supply-chain evidence requires pristine tracked and untracked source")
    return git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")


def verify_metadata(path: Path) -> tuple[dict, str]:
    payload = path.read_bytes()
    metadata = json.loads(payload)
    if not isinstance(metadata, dict) or not isinstance(metadata.get("packages"), list) or not metadata["packages"]:
        raise ValueError("cargo metadata must contain a non-empty resolved package set")
    packages = metadata["packages"]
    for package in packages:
        if not isinstance(package, dict) or any(
            not isinstance(package.get(field), str) or not package[field].strip()
            for field in ("id", "name", "version", "manifest_path")
        ) or (package.get("source") is not None and not isinstance(package["source"], str)):
            raise ValueError("cargo metadata contains an invalid package identity")
    adapter = [package for package in packages if package["name"] == "codex-hepta-bao-adapter"]
    if len(adapter) != 1 or Path(adapter[0]["manifest_path"]).resolve() != ADAPTER_MANIFEST.resolve():
        raise ValueError("cargo metadata does not bind the repository adapter manifest")
    members = metadata.get("workspace_members")
    if not isinstance(members, list) or adapter[0]["id"] not in members:
        raise ValueError("cargo metadata omits the adapter workspace identity")
    if not isinstance(metadata.get("resolve"), dict):
        raise ValueError("cargo metadata must include the resolved dependency graph")
    executed = json.loads(subprocess.check_output(METADATA_COMMAND, cwd=ROOT, text=True))
    if metadata != executed:
        raise ValueError("cargo metadata differs from the native locked exact-candidate resolution")
    return metadata, hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cargo-metadata", required=True, type=Path)
    parser.add_argument("--artifact", action="append", default=[], type=Path)
    args = parser.parse_args()

    source_sha, source_tree = source_identity()
    metadata, metadata_digest = verify_metadata(args.cargo_metadata)
    packages = sorted(
        {
            (package["name"], package["version"], package.get("source"))
            for package in metadata.get("packages", [])
        }, key=lambda package: (package[0], package[1], package[2] or "")
    )
    artifacts = []
    artifact_names = set()
    for path in args.artifact:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"requested artifact is missing or is not a regular file: {path}")
        if path.name in artifact_names:
            raise ValueError(f"duplicate artifact name: {path.name}")
        artifact_names.add(path.name)
        artifacts.append({
            "path": str(path),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        })
    receipt = {
        "schema": "hepta.secrets-supply-chain-receipt.v1",
        "sourceHeadSha": source_sha,
        "sourceTreeSha": source_tree,
        "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA") or os.environ.get("GITHUB_SHA"),
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "attemptId": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerImage": os.environ.get("ImageOS"),
        "runnerArchitecture": os.environ.get("RUNNER_ARCH"),
        "targetTriple": os.environ.get("TARGET") or "x86_64-unknown-linux-gnu",
        "cargoLockSha256": source_digest(ROOT / "codex-rs/Cargo.lock", source_sha),
        "cargoMetadataSha256": metadata_digest,
        "metadataSourceBinding": "native_locked_offline_exact_candidate_resolution",
        "metadataVerificationCommand": METADATA_COMMAND,
        "migrationHash": digest_paths(files("codex-rs/hepta-bao-adapter/migrations/*.sql", source_sha), source_sha),
        "testSetHash": digest_paths(
            files("codex-rs/hepta-bao-adapter/qa/test_*.py", source_sha)
            + files("codex-rs/hepta-bao-adapter/src/**/*test*.rs", source_sha), source_sha
        ),
        "qualificationProfileHash": digest_paths(
            files("codex-rs/hepta-bao-adapter/qa/*.py", source_sha)
            + files(".github/workflows/secrets-heptabao*.yml", source_sha), source_sha
        ),
        "implementationMapHash": source_digest(
            ROOT / "docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json", source_sha
        ),
        "documentationHash": digest_paths(files("docs/modules/secrets.heptabao/**/*", source_sha), source_sha),
        "sourceHash": digest_paths(files("codex-rs/hepta-bao-adapter/src/**/*.rs", source_sha), source_sha),
        "sbom": [
            {"name": name, "version": version, "source": source}
            for name, version, source in packages
        ],
        "artifacts": artifacts,
        "signed": False,
        "released": False,
        "productionQualified": False,
        "nonclaims": [
            "This unsigned receipt does not authenticate an external builder or authorize release.",
            "Artifact digests identify supplied bytes; they do not prove candidate build provenance.",
        ],
    }
    if source_identity() != (source_sha, source_tree):
        raise ValueError("candidate identity changed during supply-chain evidence collection")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
