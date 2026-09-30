#!/usr/bin/env python3
"""Emit non-promoting, exact-source SBOM and provenance for ui.native packages."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib
import uuid

SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
KINDS = {"head", "merge"}
PLATFORMS = {"linux", "macos", "windows"}
MAX_JSON_BYTES = 8 * 1024 * 1024


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"unsafe or oversized JSON input: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input is not an object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def cargo_components(lock_path: Path, source: str) -> list[dict]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise ValueError(f"Cargo lock has no package list: {lock_path}")
    components = []
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError(f"invalid Cargo package in {lock_path}")
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise ValueError(f"invalid Cargo package identity in {lock_path}")
        component = {
            "type": "library",
            "name": name,
            "version": version,
            "bom-ref": f"pkg:cargo/{name}@{version}?lock={source}",
            "purl": f"pkg:cargo/{name}@{version}",
            "properties": [{"name": "hepta:lockfile", "value": source}],
        }
        checksum = package.get("checksum")
        if isinstance(checksum, str) and SHA256.fullmatch(checksum):
            component["hashes"] = [{"alg": "SHA-256", "content": checksum}]
        package_source = package.get("source")
        if isinstance(package_source, str) and package_source:
            component["properties"].append(
                {"name": "hepta:cargo-source", "value": package_source}
            )
        components.append(component)
    return components


def normalized_timestamp(value: str | None) -> str:
    if value is None:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def generate(
    *,
    root: Path,
    candidate: str,
    base: str,
    implementation: str,
    source_sha: str,
    source_tree: str,
    kind: str,
    platform: str,
    package_receipt_path: Path,
    out_dir: Path,
    timestamp: str | None,
) -> dict:
    for name, value in {
        "candidate": candidate,
        "base": base,
        "implementation": implementation,
        "source_sha": source_sha,
        "source_tree": source_tree,
    }.items():
        if not SHA1.fullmatch(value) or value == "0" * 40:
            raise ValueError(f"{name} must be a complete nonzero Git identity")
    if kind not in KINDS or platform not in PLATFORMS:
        raise ValueError("unsupported source kind or platform")
    if out_dir.exists() or out_dir.is_symlink():
        raise ValueError("supply-chain output directory must be new")

    receipt = read_json(package_receipt_path)
    if receipt.get("schema") != "hepta.ui-native-package-receipt.v1":
        raise ValueError("unexpected package receipt schema")
    if receipt.get("platform") != platform:
        raise ValueError("package receipt platform mismatch")
    archive_name = receipt.get("archive")
    archive_digest = receipt.get("archiveSha256")
    if (
        not isinstance(archive_name, str)
        or not re.fullmatch(r"[A-Za-z0-9._-]+\.zip", archive_name)
        or not isinstance(archive_digest, str)
        or not SHA256.fullmatch(archive_digest)
    ):
        raise ValueError("invalid package archive identity")
    package_manifest = receipt.get("manifest")
    if not isinstance(package_manifest, dict):
        raise ValueError("package manifest is absent")
    for key in ("productionSigningObserved", "notarizationObserved", "releaseAuthorized"):
        if package_manifest.get(key) is not False:
            raise ValueError(f"unsigned package attempted unsupported promotion: {key}")

    app_lock = root / "apps/hepta-native/Cargo.lock"
    owner_lock = root / "codex-rs/Cargo.lock"
    for lock in (app_lock, owner_lock):
        if lock.is_symlink() or not lock.is_file():
            raise ValueError(f"dependency lock is unavailable: {lock}")
    lock_digests = {
        "apps/hepta-native/Cargo.lock": file_digest(app_lock),
        "codex-rs/Cargo.lock": file_digest(owner_lock),
    }
    components = cargo_components(app_lock, "application") + cargo_components(
        owner_lock, "owner"
    )
    components.sort(key=lambda item: (item["name"], item["version"], item["bom-ref"]))
    generated_at = normalized_timestamp(timestamp)
    serial_seed = f"{candidate}:{base}:{source_sha}:{kind}:{platform}:{archive_digest}"
    serial = uuid.uuid5(uuid.NAMESPACE_URL, serial_seed)
    properties = [
        {"name": "hepta:candidate-sha", "value": candidate},
        {"name": "hepta:base-sha", "value": base},
        {"name": "hepta:implementation-source-sha", "value": implementation},
        {"name": "hepta:subject-source-sha", "value": source_sha},
        {"name": "hepta:subject-source-tree", "value": source_tree},
        {"name": "hepta:source-kind", "value": kind},
        {"name": "hepta:platform", "value": platform},
        {"name": "hepta:production-qualified", "value": "false"},
        {"name": "hepta:release-authorized", "value": "false"},
    ]
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": generated_at,
            "component": {
                "type": "application",
                "name": "hepta-native",
                "version": str(package_manifest.get("version", "unknown")),
                "hashes": [{"alg": "SHA-256", "content": archive_digest}],
                "properties": properties,
            },
            "properties": [
                {"name": "hepta:application-lock-sha256", "value": lock_digests["apps/hepta-native/Cargo.lock"]},
                {"name": "hepta:owner-lock-sha256", "value": lock_digests["codex-rs/Cargo.lock"]},
            ],
        },
        "components": components,
    }

    run_id = os.environ.get("GITHUB_RUN_ID", "unbound")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "unbound")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "TrillionniumFoundation/hepta-private-ci")
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", ".github/workflows/ui-native-qualification.yml")
    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": archive_name, "digest": {"sha256": archive_digest}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://github.com/TrillionniumFoundation/hepta-private-ci/ui-native-qualification/v1",
                "externalParameters": {
                    "candidateSha": candidate,
                    "baseSha": base,
                    "implementationSourceSha": implementation,
                    "subjectSourceSha": source_sha,
                    "subjectSourceTree": source_tree,
                    "sourceKind": kind,
                    "platform": platform,
                },
                "internalParameters": {
                    "runId": run_id,
                    "runAttempt": attempt,
                    "runnerOs": os.environ.get("RUNNER_OS", platform),
                    "runnerArch": os.environ.get("RUNNER_ARCH", "unknown"),
                    "imageOs": os.environ.get("ImageOS", "unknown"),
                    "imageVersion": os.environ.get("ImageVersion", "unknown"),
                },
                "resolvedDependencies": [
                    {"uri": f"git+{server}/{repository}@{candidate}", "digest": {"sha1": candidate}},
                    *[
                        {"uri": f"file:{name}", "digest": {"sha256": value}}
                        for name, value in sorted(lock_digests.items())
                    ],
                ],
            },
            "runDetails": {
                "builder": {"id": f"{server}/{repository}/actions/{workflow_ref}"},
                "metadata": {
                    "invocationId": f"{server}/{repository}/actions/runs/{run_id}/attempts/{attempt}",
                    "startedOn": generated_at,
                    "finishedOn": generated_at,
                },
                "byproducts": [
                    {"name": "productionSigningObserved", "value": False},
                    {"name": "physicalHostAcceptance", "value": False},
                    {"name": "releaseAuthorized", "value": False},
                ],
            },
        },
    }

    out_dir.mkdir(parents=True, exist_ok=False)
    sbom_path = out_dir / "sbom.cdx.json"
    provenance_path = out_dir / "provenance.intoto.json"
    write_json(sbom_path, sbom)
    write_json(provenance_path, provenance)
    manifest = {
        "schema": "hepta.ui-native-supply-chain.v1",
        "candidateSha": candidate,
        "baseSha": base,
        "implementationSourceSha": implementation,
        "sourceSha": source_sha,
        "sourceTreeSha": source_tree,
        "sourceKind": kind,
        "platform": platform,
        "packageArchive": archive_name,
        "packageSha256": archive_digest,
        "applicationCargoLockSha256": lock_digests["apps/hepta-native/Cargo.lock"],
        "ownerCargoLockSha256": lock_digests["codex-rs/Cargo.lock"],
        "sbom": {"path": sbom_path.name, "sha256": file_digest(sbom_path)},
        "provenance": {"path": provenance_path.name, "sha256": file_digest(provenance_path)},
        "productionSigningObserved": False,
        "physicalHostAcceptance": False,
        "productionQualified": False,
        "deploymentQualified": False,
        "releaseAuthorized": False,
    }
    write_json(out_dir / "supply-chain.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--implementation", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--kind", choices=sorted(KINDS), required=True)
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--package-receipt", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--timestamp")
    args = parser.parse_args()
    try:
        manifest = generate(
            root=args.root,
            candidate=args.candidate,
            base=args.base,
            implementation=args.implementation,
            source_sha=args.source_sha,
            source_tree=args.source_tree,
            kind=args.kind,
            platform=args.platform,
            package_receipt_path=args.package_receipt,
            out_dir=args.out_dir,
            timestamp=args.timestamp,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        print(f"ui.native supply-chain evidence refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
