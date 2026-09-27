#!/usr/bin/env python3
"""Freeze exact runtime.agentd qualification artifacts and their source identity.

This receipt binds one clean Git commit/tree to the exact Agentd and App Server
binaries exercised by the native qualification lane. It deliberately does not
claim deployment qualification, independent acceptance, or production
activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
ARTIFACT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
REQUIRED_WORKFLOW_CHECKS = (
    "derived-projections",
    "owner-formatting",
    "catalog-admission",
    "owner-and-lifecycle-libraries",
    "optional-retirement-and-durable-recovery",
    "plasticity-and-live-cutover",
    "writer-admission-and-real-daemon-process",
    "strict-owner-lint",
)


class ReceiptError(ValueError):
    """Fail-closed receipt construction error."""


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT
    ).strip()


def command_output(*args: str) -> str:
    return subprocess.check_output(
        list(args), text=True, stderr=subprocess.STDOUT
    ).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_artifacts(specifications: Iterable[str]) -> list[tuple[str, Path]]:
    parsed: list[tuple[str, Path]] = []
    names: set[str] = set()
    for specification in specifications:
        name, separator, raw_path = specification.partition("=")
        if not separator or not ARTIFACT_NAME.fullmatch(name):
            raise ReceiptError(
                "artifact must use name=/absolute/path with a bounded lowercase name"
            )
        if name in names:
            raise ReceiptError(f"duplicate artifact name: {name}")
        path = Path(raw_path)
        if not path.is_absolute():
            raise ReceiptError(f"artifact path must be absolute: {path}")
        names.add(name)
        parsed.append((name, path))
    if not parsed:
        raise ReceiptError("at least one artifact is required")
    return parsed


def require_outside_checkout(path: Path, root: Path = ROOT) -> Path:
    resolved = path.resolve(strict=False)
    checkout = root.resolve()
    if resolved == checkout or resolved.is_relative_to(checkout):
        raise ReceiptError("qualification output must be outside the source checkout")
    return resolved


def freeze_artifact(name: str, source: Path, output: Path) -> dict[str, Any]:
    source_lstat = source.lstat()
    if stat.S_ISLNK(source_lstat.st_mode) or not stat.S_ISREG(source_lstat.st_mode):
        raise ReceiptError(f"qualified artifact is not a regular non-symlink file: {source}")
    if source_lstat.st_size <= 0 or source_lstat.st_size > MAX_ARTIFACT_BYTES:
        raise ReceiptError(f"qualified artifact has an invalid size: {source}")

    destination = output / "qualified-artifacts" / name
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o500)

    source_digest = sha256_file(source)
    frozen_digest = sha256_file(destination)
    if source_digest != frozen_digest:
        raise ReceiptError(f"qualified artifact copy changed bytes: {name}")
    frozen_stat = destination.stat()
    if frozen_stat.st_size != source_lstat.st_size:
        raise ReceiptError(f"qualified artifact copy changed size: {name}")

    return {
        "name": name,
        "relative_path": destination.relative_to(output).as_posix(),
        "sha256": frozen_digest,
        "size_bytes": frozen_stat.st_size,
        "source_mode_octal": oct(source_lstat.st_mode & 0o777),
        "frozen_mode_octal": oct(frozen_stat.st_mode & 0o777),
    }


def workflow_identity() -> dict[str, str]:
    mapping = {
        "repository": "GITHUB_REPOSITORY",
        "workflow": "GITHUB_WORKFLOW",
        "job": "GITHUB_JOB",
        "run_id": "GITHUB_RUN_ID",
        "run_attempt": "GITHUB_RUN_ATTEMPT",
        "event_name": "GITHUB_EVENT_NAME",
        "runner_name": "RUNNER_NAME",
        "runner_arch": "RUNNER_ARCH",
        "runner_os": "RUNNER_OS",
    }
    return {
        field: value
        for field, variable in mapping.items()
        if (value := os.environ.get(variable))
    }


def build_receipt(
    *,
    expected_sha: str,
    lane: str,
    host_platform: str,
    artifacts: list[tuple[str, Path]],
    output: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    actual_sha = git("rev-parse", "HEAD", root=root)
    if actual_sha != expected_sha:
        raise ReceiptError(
            f"qualification source moved: expected {expected_sha}, observed {actual_sha}"
        )
    dirty = git("status", "--porcelain", "--untracked-files=no", root=root)
    if dirty:
        raise ReceiptError("qualification requires a clean tracked source checkout")

    output = require_outside_checkout(output, root)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    frozen = [freeze_artifact(name, source, output) for name, source in artifacts]

    # Recheck after copying so the receipt cannot bind a source tree that moved
    # while artifact bytes were being frozen.
    if git("rev-parse", "HEAD", root=root) != actual_sha:
        raise ReceiptError("qualification source changed while freezing artifacts")
    if git("status", "--porcelain", "--untracked-files=no", root=root):
        raise ReceiptError("qualification source became dirty while freezing artifacts")

    return {
        "schema": "hepta.runtime-agentd.qualification-receipt.v1",
        "schema_version": 1,
        "source_commit": actual_sha,
        "source_tree": git("rev-parse", "HEAD^{tree}", root=root),
        "source_parents": git("show", "-s", "--format=%P", "HEAD", root=root).split(),
        "lane": lane,
        "host_platform": host_platform,
        "workflow_identity": workflow_identity(),
        "toolchain": {
            "rustc": command_output("rustc", "-Vv"),
            "cargo": command_output("cargo", "-V"),
        },
        "required_workflow_checks": list(REQUIRED_WORKFLOW_CHECKS),
        "artifacts": frozen,
        "source_clean_after_freeze": True,
        "deployment_qualified": False,
        "independent_acceptance": False,
        "production_activation": False,
        "claim": "exact-source-and-artifact-binding-only",
    }


def write_receipt(output: Path, receipt: dict[str, Any]) -> Path:
    destination = output / "qualification-receipt.json"
    staging = output / ".qualification-receipt.json.tmp"
    staging.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    staging.replace(destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--lane", choices=("source-head", "merge-candidate"), required=True)
    parser.add_argument("--host-platform", required=True)
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="NAME=/ABSOLUTE/PATH",
        help="binary to copy and bind into the receipt; repeat for each artifact",
    )
    args = parser.parse_args(argv)
    try:
        artifacts = parse_artifacts(args.artifact)
        output = require_outside_checkout(args.out)
        receipt = build_receipt(
            expected_sha=args.expected_sha,
            lane=args.lane,
            host_platform=args.host_platform,
            artifacts=artifacts,
            output=output,
        )
        destination = write_receipt(output, receipt)
    except (OSError, ReceiptError, subprocess.CalledProcessError) as error:
        print(f"FAIL_RUNTIME_AGENTD_QUALIFICATION_RECEIPT: {error}", file=sys.stderr)
        return 1
    print(
        "PASS_RUNTIME_AGENTD_QUALIFICATION_RECEIPT "
        f"source={receipt['source_commit']} tree={receipt['source_tree']} "
        f"artifacts={len(receipt['artifacts'])} receipt={destination}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
