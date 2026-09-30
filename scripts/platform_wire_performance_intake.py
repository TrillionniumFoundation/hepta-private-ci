#!/usr/bin/env python3
"""Fail-closed platform.wire paired-performance artifact intake.

The workflow supplies exact-source and registered-producer identities through
environment variables. This script never selects or broadens a producer and it
never promotes repository-local fixtures into performance acceptance.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import urllib.request
import zipfile

SHA256 = re.compile(r"[0-9a-f]{64}")
ARTIFACT_DIGEST = re.compile(r"sha256:([0-9a-f]{64})")
WORKFLOW_PATH = re.compile(r"\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml")
ARTIFACT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"required environment variable is absent: {name}")
    return value


def json_get(repository: str, token: str, path: str) -> object:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-platform-wire-performance-intake",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def download(repository: str, token: str, artifact_id: int, maximum: int) -> bytes:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-platform-wire-performance-intake",
        },
    )
    chunks: list[bytes] = []
    total = 0
    with urllib.request.urlopen(request, timeout=60) as response:
        while True:
            chunk = response.read(min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise SystemExit(
                    "measurement archive exceeded the bounded download size"
                )
    if total == 0:
        raise SystemExit("measurement archive is empty")
    return b"".join(chunks)


def verified_archive(
    repository: str,
    token: str,
    artifact_id: int,
    expected_digest: str,
    maximum: int,
) -> bytes:
    """Bound the downloaded bytes and match the selected GitHub artifact digest."""
    if (
        not isinstance(expected_digest, str)
        or SHA256.fullmatch(expected_digest) is None
    ):
        raise SystemExit("artifact SHA-256 digest is malformed")
    archive = download(repository, token, artifact_id, maximum)
    if hashlib.sha256(archive).hexdigest() != expected_digest:
        raise SystemExit("downloaded artifact archive digest mismatch")
    return archive


def extract_archive(
    archive: bytes,
    destination: Path,
    limits: dict[str, int],
    maximum: int,
) -> None:
    """Inspect every closed root entry before decompressing any observation.

    Metadata bounds compressed archives only. Each uncompressed entry must
    independently fit its parser limit, including highly compressible inputs.
    """
    if not archive or len(archive) > maximum:
        raise SystemExit("artifact archive exceeds its download byte limit")
    with zipfile.ZipFile(BytesIO(archive)) as package:
        entries = package.infolist()
        names = [entry.filename for entry in entries]
        if sorted(names) != sorted(limits) or len(entries) != len(limits):
            raise SystemExit(
                "artifact archive must contain exactly the closed root files"
            )
        for entry in entries:
            if entry.is_dir() or entry.flag_bits & 0x1:
                raise SystemExit(
                    "artifact archive contains a directory or encrypted entry"
                )
            if Path(entry.filename).name != entry.filename:
                raise SystemExit("artifact archive contains a non-root path")
            mode = (entry.external_attr >> 16) & 0o170000
            if mode not in (0, stat.S_IFREG):
                raise SystemExit("artifact archive contains a non-regular entry")
            if (
                not 0 < entry.file_size <= limits[entry.filename]
                or entry.compress_size > maximum
            ):
                raise SystemExit("artifact archive entry exceeds its byte limit")
            if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise SystemExit(
                    "artifact archive uses an unsupported compression method"
                )
        if destination.is_symlink():
            raise SystemExit("artifact destination is symlinked")
        destination.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            limit = limits[entry.filename]
            with package.open(entry, "r") as stream:
                content = stream.read(limit + 1)
            if len(content) != entry.file_size or len(content) > limit:
                raise SystemExit("artifact archive entry size is inconsistent")
            target = destination / entry.filename
            if target.is_symlink():
                raise SystemExit("artifact destination entry is symlinked")
            target.write_bytes(content)
            target.chmod(0o600)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)


def intake() -> None:
    token = required("GH_TOKEN")
    repository = required("REPOSITORY")
    source = required("SOURCE_SHA")
    run_id_text = required("MEASUREMENT_RUN_ID")
    expected_path = required("MEASUREMENT_WORKFLOW_PATH")
    expected_artifact = required("MEASUREMENT_ARTIFACT")
    records = Path(required("RECORDS"))
    destination = Path(required("INPUT_DIR"))
    maximum = int(required("MAX_ARTIFACT_BYTES"))

    if re.fullmatch(r"[0-9]{1,20}", run_id_text) is None:
        raise SystemExit("measurement run id is malformed")
    if WORKFLOW_PATH.fullmatch(expected_path) is None:
        raise SystemExit("measurement workflow path is malformed")
    if expected_path == ".github/workflows/platform-wire-performance-intake.yml":
        raise SystemExit("the intake workflow cannot register itself as a producer")
    if ARTIFACT_NAME.fullmatch(expected_artifact) is None:
        raise SystemExit("measurement artifact name is malformed")

    run_id = int(run_id_text)
    run = json_get(repository, token, f"/actions/runs/{run_id}")
    if not isinstance(run, dict):
        raise SystemExit("measurement run response is malformed")
    if run.get("head_sha") != source:
        raise SystemExit("measurement run does not bind the selected source")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise SystemExit("measurement run is not a completed success")
    if run.get("event") != "workflow_dispatch":
        raise SystemExit("measurement run must be operator-dispatched")
    if run.get("path") != expected_path:
        raise SystemExit("measurement workflow path differs from the selected producer")
    if run.get("repository", {}).get("full_name") != repository:
        raise SystemExit("measurement run belongs to another repository")
    attempt = run.get("run_attempt")
    if type(attempt) is not int or attempt <= 0:
        raise SystemExit("measurement run attempt is missing")

    listing = json_get(
        repository, token, f"/actions/runs/{run_id}/artifacts?per_page=100"
    )
    artifacts = listing.get("artifacts") if isinstance(listing, dict) else None
    if not isinstance(artifacts, list):
        raise SystemExit("artifact listing is malformed")
    matches = [item for item in artifacts if item.get("name") == expected_artifact]
    if len(matches) != 1:
        raise SystemExit("exactly one selected measurement artifact is required")
    artifact = matches[0]
    artifact_id = artifact.get("id")
    size = artifact.get("size_in_bytes")
    if type(artifact_id) is not int or artifact_id <= 0:
        raise SystemExit("measurement artifact id is invalid")
    if type(size) is not int or not 1 <= size <= maximum:
        raise SystemExit("measurement artifact exceeds the bounded intake size")
    if artifact.get("expired") is not False:
        raise SystemExit("selected measurement artifact is expired")
    digest = artifact.get("digest")
    digest_match = (
        ARTIFACT_DIGEST.fullmatch(digest) if isinstance(digest, str) else None
    )
    if digest_match is None:
        raise SystemExit("measurement artifact has no immutable SHA-256 digest")
    if artifact.get("workflow_run", {}).get("head_sha") != source:
        raise SystemExit("measurement artifact source differs from the selected source")

    archive = verified_archive(
        repository, token, artifact_id, digest_match.group(1), maximum
    )
    actual_digest = hashlib.sha256(archive).hexdigest()

    limits = {
        "performance-plan.json": 256 * 1024,
        "paired-measurements.json": 16 * 1024 * 1024,
    }
    records.mkdir(parents=True, exist_ok=True)
    extract_archive(archive, destination, limits, maximum)

    write_json(
        records / "measurement-run.json",
        {
            "id": run["id"],
            "attempt": attempt,
            "repository": repository,
            "name": run.get("name"),
            "path": run["path"],
            "event": run["event"],
            "head_sha": run["head_sha"],
            "status": run["status"],
            "conclusion": run["conclusion"],
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "html_url": run.get("html_url"),
        },
    )
    write_json(
        records / "measurement-artifact.json",
        {
            "id": artifact_id,
            "name": artifact["name"],
            "size_in_bytes": size,
            "digest": digest,
            "created_at": artifact.get("created_at"),
            "expires_at": artifact.get("expires_at"),
        },
    )
    (records / "measurement-archive.sha256").write_text(
        f"{actual_digest}  measurement-artifact.zip\n", encoding="utf-8"
    )
    with open(required("GITHUB_ENV"), "a", encoding="utf-8") as environment:
        environment.write(f"MEASUREMENT_RUN_ATTEMPT={attempt}\n")
        environment.write(
            f"MEASUREMENT_RUN_IDENTITY=github-actions:{repository}:{run_id}:{attempt}\n"
        )


def read_json(path: Path, limit: int) -> tuple[object, bytes]:
    if path.is_symlink():
        raise ValueError(f"symlinked evidence rejected: {path.name}")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError(f"evidence exceeds limit: {path.name}")
    return json.loads(raw), raw


def receipt() -> None:
    records = Path(required("RECORDS"))
    input_dir = Path(required("INPUT_DIR"))
    source = required("SOURCE_SHA")
    outcomes = {
        "setup": os.environ.get("SETUP_OUTCOME"),
        "metadata": os.environ.get("METADATA_OUTCOME"),
        "validation": os.environ.get("VALIDATION_OUTCOME"),
    }
    errors = [
        f"{name} outcome was {value}"
        for name, value in outcomes.items()
        if value != "success"
    ]
    artifact_meta: object = {}
    run_meta: object = {}
    check: object | None = None
    report: object | None = None
    registry_digest = plan_digest = report_digest = None

    try:
        artifact_meta, _ = read_json(records / "measurement-artifact.json", 64 * 1024)
        run_meta, _ = read_json(records / "measurement-run.json", 64 * 1024)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"producer metadata: {error}")
    try:
        _, registry_raw = read_json(Path(required("REGISTRY")), 256 * 1024)
        registry_digest = hashlib.sha256(registry_raw).hexdigest()
        _, plan_raw = read_json(input_dir / "performance-plan.json", 256 * 1024)
        plan_digest = hashlib.sha256(plan_raw).hexdigest()
        if plan_digest != required("PLAN_SHA256"):
            raise ValueError("plan digest differs from the selected plan")
        report, report_raw = read_json(
            input_dir / "paired-measurements.json", 16 * 1024 * 1024
        )
        report_digest = hashlib.sha256(report_raw).hexdigest()
        check, _ = read_json(records / "performance-check.json", 1024 * 1024)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"paired evidence: {error}")

    artifact_digest = (
        artifact_meta.get("digest") if isinstance(artifact_meta, dict) else None
    )
    digest_match = (
        ARTIFACT_DIGEST.fullmatch(artifact_digest)
        if isinstance(artifact_digest, str)
        else None
    )
    if digest_match is None:
        errors.append("artifact digest is absent or malformed")
        artifact_digest_value = None
    else:
        artifact_digest_value = digest_match.group(1)

    run_attempt = run_meta.get("attempt") if isinstance(run_meta, dict) else None
    if type(run_attempt) is not int or run_attempt <= 0:
        run_attempt = 0
    status = "passed" if not errors else "failed"
    result: dict[str, object] = {
        "schema": "hepta.platform-wire.receipt.v2",
        "kind": "platform-wire-performance",
        "source_sha": source,
        "tested_sha": source,
        "status": status,
        "errors": errors,
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
        "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "run_id": int(required("GITHUB_RUN_ID")),
        "run_attempt": int(required("GITHUB_RUN_ATTEMPT")),
        "event": os.environ.get("GITHUB_EVENT_NAME"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": "platform-wire-performance",
        "measurement_repository": required("REPOSITORY"),
        "measurement_run_id": int(required("MEASUREMENT_RUN_ID")),
        "measurement_run_attempt": run_attempt,
        "measurement_workflow_path": required("MEASUREMENT_WORKFLOW_PATH"),
        "measurement_artifact": required("MEASUREMENT_ARTIFACT"),
        "path_count": 0,
        "independent_acceptance": False,
        "activation": False,
        "release": False,
    }
    if status == "passed":
        if not isinstance(check, dict) or not isinstance(report, dict):
            raise SystemExit("validated performance evidence was not retained")
        paths = check.get("paths")
        registration = check.get("registration")
        if not isinstance(paths, list) or len(paths) != 5:
            raise SystemExit("validated output did not retain five paths")
        if not isinstance(registration, dict):
            raise SystemExit("validated output did not retain registration")
        result.update(
            {
                "measurement_artifact_digest": artifact_digest_value,
                "registry_sha256": registry_digest,
                "registered_owner": registration.get("owner"),
                "plan_sha256": plan_digest,
                "report_sha256": report_digest,
                "host_profile": report.get("host_profile"),
                "runner_identity": report.get("runner_identity"),
                "toolchain": report.get("toolchain"),
                "measurement_run_identity": report.get("run_identity"),
                "reference_transport": report.get("reference_transport"),
                "path_count": len(paths),
                "size_ratio_numerator": 70,
                "size_ratio_denominator": 100,
                "p99_ratio_numerator": 80,
                "p99_ratio_denominator": 100,
                "paths": paths,
                "scope": (
                    "protected intake of an exact-source, same-repository, "
                    "registered paired-measurement archive; independent benchmark review remains external"
                ),
            }
        )
    records.mkdir(parents=True, exist_ok=True)
    write_json(records / "platform-wire-performance.json", result)


def self_test() -> None:
    assert SHA256.fullmatch("a" * 64)
    assert ARTIFACT_DIGEST.fullmatch("sha256:" + "b" * 64)
    assert WORKFLOW_PATH.fullmatch(".github/workflows/producer.yml")
    assert ARTIFACT_NAME.fullmatch("paired-evidence_1")
    print("platform.wire performance intake self-test passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("intake", "receipt", "self-test"))
    args = parser.parse_args()
    if args.command == "intake":
        intake()
    elif args.command == "receipt":
        receipt()
    else:
        self_test()


if __name__ == "__main__":
    main()
