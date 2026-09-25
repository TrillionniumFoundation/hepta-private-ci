"""Codex-built V8 artifact overrides for package Cargo builds."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

from .targets import REPO_ROOT, TargetSpec

DOWNLOAD_TIMEOUT_SECS = 120
V8_ARTIFACT_PROFILE = "ptrcomp_sandbox_release"


@dataclass(frozen=True)
class RustyV8ArtifactPair:
    archive: Path
    binding: Path


def resolve_codex_v8_cargo_env(
    spec: TargetSpec,
    *,
    environ: Mapping[str, str] | None = None,
    cache_root: Path | None = None,
) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    if environ.get("V8_FROM_SOURCE") in {"true", "1", "yes"}:
        return {}

    archive_override = environ.get("RUSTY_V8_ARCHIVE")
    binding_override = environ.get("RUSTY_V8_SRC_BINDING_PATH")
    if archive_override and binding_override:
        return {}
    if archive_override or binding_override:
        raise RuntimeError(
            "Cargo package builds need RUSTY_V8_ARCHIVE and RUSTY_V8_SRC_BINDING_PATH set together."
        )

    artifacts = fetch_codex_v8_artifacts(spec, cache_root=cache_root)
    return {
        "RUSTY_V8_ARCHIVE": str(artifacts.archive),
        "RUSTY_V8_SRC_BINDING_PATH": str(artifacts.binding),
    }


def fetch_codex_v8_artifacts(
    spec: TargetSpec,
    *,
    version: str | None = None,
    cache_root: Path | None = None,
) -> RustyV8ArtifactPair:
    version = version or resolved_v8_crate_version()
    release_url = (
        f"https://github.com/openai/codex/releases/download/rusty-v8-v{version}"
    )
    target = spec.target
    cache_dir = (cache_root or default_cache_root()) / f"rusty-v8-{version}-{target}"

    if spec.is_windows:
        archive_name = f"rusty_v8_{V8_ARTIFACT_PROFILE}_{target}.lib.gz"
    else:
        archive_name = f"librusty_v8_{V8_ARTIFACT_PROFILE}_{target}.a.gz"
    binding_name = f"src_binding_{V8_ARTIFACT_PROFILE}_{target}.rs"
    checksums_name = f"rusty_v8_{V8_ARTIFACT_PROFILE}_{target}.sha256"

    archive = cache_dir / archive_name
    binding = cache_dir / binding_name
    checksums = cache_dir / checksums_name

    download_file(f"{release_url}/{checksums.name}", checksums)
    expected_checksums = load_checksums(checksums, {archive.name, binding.name})
    for artifact in [archive, binding]:
        ensure_valid_artifact(
            artifact,
            expected_checksums[artifact.name],
            f"{release_url}/{artifact.name}",
        )

    return RustyV8ArtifactPair(archive=archive, binding=binding)


def resolved_v8_crate_version() -> str:
    import tomllib

    cargo_lock = tomllib.loads((REPO_ROOT / "codex-rs" / "Cargo.lock").read_text())
    versions = sorted(
        {
            package["version"]
            for package in cargo_lock["package"]
            if package["name"] == "v8"
        }
    )
    if len(versions) != 1:
        raise RuntimeError(
            f"Expected exactly one resolved v8 version, found: {versions}"
        )
    return versions[0]


def default_cache_root() -> Path:
    return Path(tempfile.gettempdir()) / "codex-package"


def load_checksums(checksums_path: Path, artifact_names: set[str]) -> dict[str, str]:
    checksums: dict[str, str] = {}
    lines = checksums_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != len(artifact_names):
        raise RuntimeError(
            f"Expected {len(artifact_names)} V8 checksums in {checksums_path}, found {len(lines)}."
        )

    for line in lines:
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise RuntimeError(
                f"Invalid V8 checksum line in {checksums_path}: {line!r}"
            )

        digest, artifact_name = parts[0], parts[1].strip()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RuntimeError(
                f"Invalid V8 checksum digest in {checksums_path}: {digest}"
            )
        if artifact_name not in artifact_names:
            raise RuntimeError(
                f"Unexpected V8 checksum artifact in {checksums_path}: {artifact_name}"
            )
        checksums[artifact_name] = digest

    if checksums.keys() != artifact_names:
        raise RuntimeError(
            f"V8 checksum manifest {checksums_path} does not cover {artifact_names}."
        )
    return checksums


def ensure_valid_artifact(artifact: Path, checksum: str, url: str) -> None:
    if has_checksum(artifact, checksum):
        return

    # Only a verified private staging file may replace the shared cache entry.
    # A failed downloader must not remove bytes published by another builder.
    download_file(url, artifact, expected_checksum=checksum)


def has_checksum(path: Path, expected: str) -> bool:
    if not path.is_file():
        return False

    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def download_file(
    url: str, dest: Path, *, expected_checksum: str | None = None
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Distinct same-directory staging files allow concurrent builders without
    # unlinking another process's active download. Publication remains atomic.
    fd, name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            with urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECS) as response:
                shutil.copyfileobj(response, output)
        if expected_checksum is not None and not has_checksum(
            temp_path, expected_checksum
        ):
            raise RuntimeError(
                f"Codex-built V8 artifact {dest} failed checksum validation."
            )
        temp_path.replace(dest)
    finally:
        temp_path.unlink(missing_ok=True)
