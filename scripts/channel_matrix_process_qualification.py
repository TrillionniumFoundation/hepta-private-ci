#!/usr/bin/env python3
"""Validate exact external process-crash qualification for channel.matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "docs/modules/channel.matrix/PROCESS_FAULT_MATRIX.json"
PROFILE_SCHEMA = "hepta.channel-matrix-process-fault-profile.v1"
MANIFEST_SCHEMA = "hepta.channel-matrix-process-fault-evidence.v1"
RESULT_SCHEMA = "hepta.channel-matrix-process-fault-validation.v1"
PROFILE_FIELDS = {
    "schema",
    "schemaVersion",
    "qualificationScope",
    "storeBackend",
    "transport",
    "scenarios",
}
PROFILE_SCENARIO_FIELDS = {"id", "name", "requiredInvariants"}
MANIFEST_FIELDS = {
    "schema",
    "candidate",
    "result",
    "execution",
    "scenarios",
    "authorityGranted",
    "activation",
    "promotion",
    "release",
}
EXECUTION_FIELDS = {
    "principal",
    "runId",
    "attemptId",
    "hostFingerprint",
    "runnerImage",
    "targetTriple",
    "startedAtUnixMs",
    "finishedAtUnixMs",
    "storeBackend",
    "transport",
    "homeserverImageDigest",
    "agentdSha256",
    "matrixdSha256",
    "testBinarySha256",
    "configurationSha256",
    "processIdentityLedgerSha256",
}
MANIFEST_SCENARIO_FIELDS = {"id", "result", "observedInvariants", "artifact"}
ARTIFACT_FIELDS = {"path", "bytes", "sha256"}
RESULT_FIELDS = {
    "schema",
    "candidate",
    "result",
    "execution",
    "profileSha256",
    "manifest",
    "scenarios",
    "authorityGranted",
    "activation",
    "promotion",
    "release",
}
MAX_PROFILE_BYTES = 512 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[A-Za-z0-9._:/+-]{1,240}")
SCENARIO_ID = re.compile(r"MATRIX-PF[0-9]{2}")
LOWER_IDENTIFIER = re.compile(r"[a-z0-9_]{1,160}")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _object(payload: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate {label} key: {key}")
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


def _artifact(directory: Path, value: object) -> tuple[Path, bytes, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != ARTIFACT_FIELDS:
        raise ValueError("invalid process-fault artifact")
    name = value.get("path")
    if (
        not isinstance(name, str)
        or Path(name).is_absolute()
        or Path(name).name != name
    ):
        raise ValueError("process-fault artifact must be one sibling file")
    path, payload = _stable_bytes(
        directory / name, MAX_ARTIFACT_BYTES, "process-fault artifact"
    )
    expected = {
        "path": path.name,
        "bytes": len(payload),
        "sha256": _digest(payload),
    }
    if value != expected:
        raise ValueError("process-fault artifact identity mismatch")
    return path, payload, expected


def load_profile(
    path: Path = PROFILE_PATH,
) -> tuple[dict[str, Any], str]:
    _, payload = _stable_bytes(path, MAX_PROFILE_BYTES, "process-fault profile")
    row = _object(payload, "process-fault profile")
    if (
        set(row) != PROFILE_FIELDS
        or row.get("schema") != PROFILE_SCHEMA
        or type(row.get("schemaVersion")) is not int
        or row["schemaVersion"] != 1
        or row.get("qualificationScope")
        != "external_process_crash_consistency_not_activation_or_release"
        or row.get("storeBackend") != "sqlite_wal_single_writer"
        or row.get("transport") != "matrix_synapse_authenticated"
    ):
        raise ValueError("unsupported process-fault profile")
    scenarios = row.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("empty process-fault scenario inventory")
    ids: list[str] = []
    names: set[str] = set()
    normalized: dict[str, tuple[str, ...]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != PROFILE_SCENARIO_FIELDS:
            raise ValueError("invalid process-fault scenario")
        scenario_id = scenario.get("id")
        name = scenario.get("name")
        invariants = scenario.get("requiredInvariants")
        if (
            not isinstance(scenario_id, str)
            or not SCENARIO_ID.fullmatch(scenario_id)
            or not isinstance(name, str)
            or not LOWER_IDENTIFIER.fullmatch(name)
            or name in names
            or not isinstance(invariants, list)
            or not invariants
            or invariants != sorted(invariants)
            or len(invariants) != len(set(invariants))
            or any(
                not isinstance(item, str) or not LOWER_IDENTIFIER.fullmatch(item)
                for item in invariants
            )
        ):
            raise ValueError("invalid process-fault scenario identity or invariants")
        ids.append(scenario_id)
        names.add(name)
        normalized[scenario_id] = tuple(invariants)
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ValueError("process-fault scenarios are duplicate or reordered")
    return {
        "storeBackend": row["storeBackend"],
        "transport": row["transport"],
        "scenarios": normalized,
    }, _digest(payload)


def _execution(
    value: object,
    profile: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != EXECUTION_FIELDS:
        raise ValueError("invalid process-fault executor identity")
    for key in (
        "principal",
        "runId",
        "attemptId",
        "hostFingerprint",
        "runnerImage",
        "targetTriple",
    ):
        item = value.get(key)
        if not isinstance(item, str) or not IDENTIFIER.fullmatch(item):
            raise ValueError(f"invalid process-fault execution field: {key}")
    if (
        value.get("storeBackend") != profile["storeBackend"]
        or value.get("transport") != profile["transport"]
    ):
        raise ValueError("process-fault backend or transport mismatch")
    started = value.get("startedAtUnixMs")
    finished = value.get("finishedAtUnixMs")
    if (
        type(started) is not int
        or type(finished) is not int
        or not 0 < started <= finished <= 2**63 - 1
    ):
        raise ValueError("invalid process-fault execution window")
    if not isinstance(value.get("homeserverImageDigest"), str) or not IMAGE_DIGEST.fullmatch(
        value["homeserverImageDigest"]
    ):
        raise ValueError("invalid homeserver image digest")
    for key in (
        "agentdSha256",
        "matrixdSha256",
        "testBinarySha256",
        "configurationSha256",
        "processIdentityLedgerSha256",
    ):
        item = value.get(key)
        if not isinstance(item, str) or not HEX64.fullmatch(item):
            raise ValueError(f"invalid process-fault digest: {key}")
    return dict(value)


def validate_manifest(
    manifest_path: Path,
    expected_candidate: dict[str, str],
    profile_path: Path = PROFILE_PATH,
) -> dict[str, Any]:
    candidate = _candidate(expected_candidate)
    manifest, payload = _stable_bytes(
        manifest_path, MAX_MANIFEST_BYTES, "process-fault evidence manifest"
    )
    if manifest.is_relative_to(ROOT.resolve()):
        raise ValueError("process-fault evidence must remain outside the checkout")
    row = _object(payload, "process-fault evidence manifest")
    if set(row) != MANIFEST_FIELDS or row.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unsupported process-fault evidence manifest")
    if row.get("result") != "pass" or _candidate(row.get("candidate")) != candidate:
        raise ValueError("process-fault result or candidate mismatch")
    for denied in ("authorityGranted", "activation", "promotion", "release"):
        if row.get(denied) is not False:
            raise ValueError(f"process-fault evidence cannot grant {denied}")

    profile, profile_sha256 = load_profile(profile_path)
    execution = _execution(row.get("execution"), profile)
    scenarios = row.get("scenarios")
    required = profile["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) != len(required):
        raise ValueError("process-fault scenario inventory is incomplete")
    observed: set[str] = set()
    artifact_names: set[str] = set()
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != MANIFEST_SCENARIO_FIELDS:
            raise ValueError("invalid process-fault scenario evidence")
        scenario_id = scenario.get("id")
        invariants = scenario.get("observedInvariants")
        if (
            not isinstance(scenario_id, str)
            or scenario_id not in required
            or scenario_id in observed
            or scenario.get("result") != "pass"
            or not isinstance(invariants, list)
            or tuple(invariants) != required[scenario_id]
        ):
            raise ValueError("missing, duplicate, failed or incomplete process-fault scenario")
        artifact_path, _, artifact = _artifact(manifest.parent, scenario.get("artifact"))
        if artifact_path.name in artifact_names:
            raise ValueError("process-fault scenarios reuse one artifact")
        observed.add(scenario_id)
        artifact_names.add(artifact_path.name)
        results.append(
            {
                "id": scenario_id,
                "observedInvariants": list(required[scenario_id]),
                "artifact": artifact,
            }
        )
    if observed != set(required):
        raise ValueError("process-fault scenario inventory is incomplete")
    results.sort(key=lambda item: item["id"])
    return {
        "schema": RESULT_SCHEMA,
        "candidate": candidate,
        "result": "pass",
        "execution": execution,
        "profileSha256": profile_sha256,
        "manifest": {
            "path": manifest.name,
            "bytes": len(payload),
            "sha256": _digest(payload),
        },
        "scenarios": results,
        "authorityGranted": False,
        "activation": False,
        "promotion": False,
        "release": False,
    }


def validate_result(
    payload: bytes,
    expected_candidate: dict[str, str],
    profile_path: Path = PROFILE_PATH,
) -> dict[str, Any]:
    candidate = _candidate(expected_candidate)
    row = _object(payload, "process-fault validation")
    profile, profile_sha256 = load_profile(profile_path)
    if (
        set(row) != RESULT_FIELDS
        or row.get("schema") != RESULT_SCHEMA
        or row.get("result") != "pass"
        or _candidate(row.get("candidate")) != candidate
        or row.get("profileSha256") != profile_sha256
    ):
        raise ValueError("invalid process-fault validation result")
    for denied in ("authorityGranted", "activation", "promotion", "release"):
        if row.get(denied) is not False:
            raise ValueError(f"process-fault validation cannot grant {denied}")
    _execution(row.get("execution"), profile)
    manifest = row.get("manifest")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != ARTIFACT_FIELDS
        or not isinstance(manifest.get("path"), str)
        or Path(manifest["path"]).name != manifest["path"]
        or type(manifest.get("bytes")) is not int
        or manifest["bytes"] <= 0
        or not isinstance(manifest.get("sha256"), str)
        or not HEX64.fullmatch(manifest["sha256"])
    ):
        raise ValueError("invalid process-fault source manifest identity")
    scenarios = row.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(profile["scenarios"]):
        raise ValueError("invalid process-fault validation scenario inventory")
    observed: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != {
            "id",
            "observedInvariants",
            "artifact",
        }:
            raise ValueError("invalid process-fault validation scenario")
        scenario_id = scenario.get("id")
        if (
            scenario_id not in profile["scenarios"]
            or scenario_id in observed
            or tuple(scenario.get("observedInvariants", ()))
            != profile["scenarios"][scenario_id]
        ):
            raise ValueError("process-fault validation scenario mismatch")
        artifact = scenario.get("artifact")
        if (
            not isinstance(artifact, dict)
            or set(artifact) != ARTIFACT_FIELDS
            or type(artifact.get("bytes")) is not int
            or artifact["bytes"] < 0
            or not isinstance(artifact.get("sha256"), str)
            or not HEX64.fullmatch(artifact["sha256"])
        ):
            raise ValueError("invalid process-fault validation artifact")
        observed.add(scenario_id)
    if observed != set(profile["scenarios"]):
        raise ValueError("process-fault validation scenario inventory is incomplete")
    return row


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
                    "promotion": False,
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
