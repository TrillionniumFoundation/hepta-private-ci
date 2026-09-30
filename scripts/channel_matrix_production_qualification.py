#!/usr/bin/env python3
"""Validate complete, external channel.matrix production evidence manifests."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import channel_matrix_process_qualification as process

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "docs/modules/channel.matrix/PRODUCTION_QUALIFICATION_PROFILE.json"
PROFILE_SCHEMA = "hepta.channel-matrix-production-qualification-profile.v1"
MANIFEST_SCHEMA = "hepta.channel-matrix-production-evidence-manifest.v1"
RESULT_SCHEMA = "hepta.channel-matrix-production-evidence-validation.v1"
PROCESS_CHECK_ID = "process_fault_matrix"
SCOPES = ("target_qualification", "independent_acceptance")
PROFILE_KEYS = {
    "target_qualification": "targetQualification",
    "independent_acceptance": "independentAcceptance",
}
PROFILE_FIELDS = {"schema", "schemaVersion", *PROFILE_KEYS.values()}
MANIFEST_FIELDS = {
    "schema",
    "scope",
    "candidate",
    "result",
    "executor",
    "checks",
    "authorityGranted",
    "activation",
    "release",
}
EXECUTOR_FIELDS = {
    "principal",
    "hostFingerprint",
    "startedAtUnixMs",
    "finishedAtUnixMs",
}
CHECK_FIELDS = {"id", "result", "artifact"}
ARTIFACT_FIELDS = {"path", "bytes", "sha256"}
MAX_PROFILE_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,160}")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _object(payload: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate {label} key")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _stable_bytes(path: Path, maximum: int, label: str) -> tuple[Path, bytes]:
    absolute = path.absolute()
    resolved = path.resolve(strict=True)
    if path.is_symlink() or resolved != absolute or not resolved.is_file():
        raise ValueError(f"canonical regular {label} required")
    before = resolved.stat()
    if not 0 <= before.st_size <= maximum:
        raise ValueError(f"{label} exceeds budget")
    payload = resolved.read_bytes()
    after = resolved.stat()
    identity = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_size,
        row.st_mtime_ns,
        row.st_ctime_ns,
    )
    if identity(before) != identity(after) or len(payload) != before.st_size:
        raise ValueError(f"{label} changed while being read")
    return resolved, payload


def _sibling(directory: Path, value: object, maximum: int) -> tuple[Path, bytes]:
    if (
        not isinstance(value, str)
        or Path(value).is_absolute()
        or Path(value).name != value
    ):
        raise ValueError("artifact path must be one sibling file")
    return _stable_bytes(directory / value, maximum, "evidence artifact")


def load_profile(path: Path = PROFILE_PATH) -> tuple[dict[str, tuple[str, ...]], str]:
    _, payload = _stable_bytes(path, MAX_PROFILE_BYTES, "qualification profile")
    row = _object(payload, "qualification profile")
    if (
        set(row) != PROFILE_FIELDS
        or row.get("schema") != PROFILE_SCHEMA
        or type(row.get("schemaVersion")) is not int
        or row["schemaVersion"] != 1
    ):
        raise ValueError("unsupported production qualification profile")
    result: dict[str, tuple[str, ...]] = {}
    for scope, key in PROFILE_KEYS.items():
        values = row.get(key)
        if (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(values))
            or any(
                not isinstance(value, str) or not IDENTIFIER.fullmatch(value)
                for value in values
            )
            or values != sorted(values)
        ):
            raise ValueError(f"invalid {scope} check inventory")
        result[scope] = tuple(values)
    if PROCESS_CHECK_ID not in result["target_qualification"]:
        raise ValueError("target qualification omits the process-fault matrix")
    return result, _digest(payload)


def _candidate(value: object) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"commit", "tree"}
        or any(
            not isinstance(item, str) or not HEX40.fullmatch(item)
            for item in value.values()
        )
    ):
        raise ValueError("invalid exact candidate")
    return dict(value)


def validate_manifest(
    manifest_path: Path,
    expected_candidate: dict[str, str],
    profile_path: Path = PROFILE_PATH,
) -> dict[str, Any]:
    candidate = _candidate(expected_candidate)
    manifest, payload = _stable_bytes(
        manifest_path, MAX_MANIFEST_BYTES, "production evidence manifest"
    )
    if manifest.is_relative_to(ROOT.resolve()):
        raise ValueError("production evidence must remain outside the checkout")
    row = _object(payload, "production evidence manifest")
    if set(row) != MANIFEST_FIELDS or row.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unsupported production evidence manifest")
    scope = row.get("scope")
    if scope not in SCOPES or row.get("result") != "pass":
        raise ValueError("manifest scope or result mismatch")
    if _candidate(row.get("candidate")) != candidate:
        raise ValueError("manifest candidate mismatch")
    if (
        row.get("authorityGranted") is not False
        or row.get("activation") is not False
        or row.get("release") is not False
    ):
        raise ValueError("qualification evidence cannot grant authority or release")

    executor = row.get("executor")
    if not isinstance(executor, dict) or set(executor) != EXECUTOR_FIELDS:
        raise ValueError("invalid executor identity")
    for key in ("principal", "hostFingerprint"):
        value = executor.get(key)
        if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
            raise ValueError("invalid executor identity")
    started = executor.get("startedAtUnixMs")
    finished = executor.get("finishedAtUnixMs")
    if (
        type(started) is not int
        or type(finished) is not int
        or not 0 < started <= finished <= 2**63 - 1
    ):
        raise ValueError("invalid execution window")

    profile, profile_sha256 = load_profile(profile_path)
    required = set(profile[scope])
    checks = row.get("checks")
    if not isinstance(checks, list) or len(checks) != len(required):
        raise ValueError("qualification check inventory is incomplete")
    observed: set[str] = set()
    artifact_names: set[str] = set()
    artifacts = []
    process_validation = None
    for check in checks:
        if not isinstance(check, dict) or set(check) != CHECK_FIELDS:
            raise ValueError("invalid qualification check")
        check_id = check.get("id")
        if (
            not isinstance(check_id, str)
            or check_id not in required
            or check_id in observed
            or check.get("result") != "pass"
        ):
            raise ValueError("missing, duplicate or failed qualification check")
        artifact = check.get("artifact")
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_FIELDS:
            raise ValueError("invalid qualification artifact")
        artifact_path, artifact_bytes = _sibling(
            manifest.parent, artifact.get("path"), MAX_ARTIFACT_BYTES
        )
        expected = {
            "path": artifact_path.name,
            "bytes": len(artifact_bytes),
            "sha256": _digest(artifact_bytes),
        }
        if artifact != expected or artifact_path.name in artifact_names:
            raise ValueError("qualification artifact identity mismatch")
        if scope == "target_qualification" and check_id == PROCESS_CHECK_ID:
            process_validation = process.validate_result(artifact_bytes, candidate)
        observed.add(check_id)
        artifact_names.add(artifact_path.name)
        artifacts.append({"id": check_id, **expected})
    if observed != required:
        raise ValueError("qualification check inventory is incomplete")
    if scope == "target_qualification" and process_validation is None:
        raise ValueError("target qualification lacks a validated process-fault matrix")
    artifacts.sort(key=lambda value: value["id"])
    return {
        "schema": RESULT_SCHEMA,
        "scope": scope,
        "candidate": candidate,
        "result": "pass",
        "executor": executor,
        "profileSha256": profile_sha256,
        "manifest": {
            "path": manifest.name,
            "bytes": len(payload),
            "sha256": _digest(payload),
        },
        "artifacts": artifacts,
        "processFaultMatrix": (
            {
                "result": process_validation["result"],
                "profileSha256": process_validation["profileSha256"],
                "scenarioCount": len(process_validation["scenarios"]),
                "manifestSha256": process_validation["manifest"]["sha256"],
            }
            if process_validation is not None
            else None
        ),
        "authorityGranted": False,
        "activation": False,
        "release": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate_manifest(
            args.manifest,
            {"commit": args.expected_commit, "tree": args.expected_tree},
            args.profile,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            json.dumps(
                {
                    "schema": RESULT_SCHEMA,
                    "result": "fail",
                    "error": str(exc),
                    "authorityGranted": False,
                    "activation": False,
                    "release": False,
                },
                sort_keys=True,
            )
        )
        return 2
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        output = args.output.absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
