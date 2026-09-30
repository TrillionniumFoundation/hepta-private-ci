#!/usr/bin/env python3
"""Require one exact source-head/base-merge qualification pair.

This verifier consumes retained read-only lane artifacts. It never infers target
qualification, independent acceptance, activation, promotion or release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = tuple(f"MATRIX-Q{index:02}" for index in range(1, 30))
LOCAL_STATES = (
    "source_navigation",
    "compilation",
    "native_tests",
    "strict_lint",
    "formatting",
)
MAX_OBJECT_BYTES = 32 * 1024 * 1024


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"non-regular evidence: {path}")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_OBJECT_BYTES:
        raise ValueError(f"invalid evidence object: {path.name}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError(f"evidence object required: {path.name}")
    return result


def evidence_directory(value: Path) -> Path:
    if value.is_symlink():
        raise ValueError("symlinked lane directory")
    directory = value.resolve(strict=True)
    if not directory.is_dir() or directory != value.absolute():
        raise ValueError("lane directory must be canonical")
    return directory


def manifest_inventory(directory: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        manifest.get("schema") != "hepta.channel-matrix-artifact-manifest.v2"
        or manifest.get("runnerReportedStatus") != "success"
        or manifest.get("claims", {}).get("focusedCommandsPassed") is not True
    ):
        raise ValueError("lane manifest does not prove successful local commands")
    claims = manifest.get("claims")
    for denied in (
        "homeserverQualified",
        "independentAcceptance",
        "activation",
        "release",
        "authorityGranted",
    ):
        if claims.get(denied) is not False:
            raise ValueError(f"lane manifest escalates {denied}")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty lane manifest")
    inventory: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise ValueError("invalid manifest file row")
        name = row["path"]
        path = Path(name)
        if (
            not isinstance(name, str)
            or path.is_absolute()
            or ".." in path.parts
            or name in inventory
        ):
            raise ValueError("unsafe or duplicate manifest path")
        actual = directory / path
        if row["bytes"] != actual.stat().st_size or row["sha256"] != digest(actual):
            raise ValueError(f"manifest mismatch: {name}")
        inventory[name] = row
    required = {
        "candidate.json",
        "source.json",
        "source-after.json",
        "status.json",
        "scenario-ledger.json",
        "focused-tests.junit.xml",
    }
    required.update(f"{label}.command.json" for label in ("compile", "focused-tests", "clippy", "format"))
    required.update(f"{label}.log" for label in ("compile", "focused-tests", "clippy", "format"))
    if not required.issubset(inventory):
        raise ValueError(f"manifest is missing required evidence: {sorted(required - inventory.keys())}")
    return inventory


def lane(directory_value: Path, expected_lane: str) -> dict[str, Any]:
    directory = evidence_directory(directory_value)
    status = read_object(directory / "status.json")
    ledger = read_object(directory / "scenario-ledger.json")
    source = read_object(directory / "source.json")
    source_after = read_object(directory / "source-after.json")
    candidate_receipt = read_object(directory / "candidate.json")
    manifest = read_object(directory / "manifest.json")
    inventory = manifest_inventory(directory, manifest)

    if source != source_after:
        raise ValueError("source changed during qualification")
    if source.get("schema") != "hepta.channel-matrix-source-snapshot.v1" or source.get("lane") != expected_lane:
        raise ValueError("wrong source lane")
    for name in ("testedSha", "testedTree", "sourceSha", "baseSha"):
        if not isinstance(source.get(name), str) or not re.fullmatch(r"[0-9a-f]{40}", source[name]):
            raise ValueError("invalid source identity")
    identity = {"commit": source["testedSha"], "tree": source["testedTree"], "lane": expected_lane}
    if (
        status.get("schema") != "hepta.channel-matrix-evidence-status.v2"
        or status.get("candidate") != identity
        or status.get("activation") is not False
        or status.get("release") is not False
        or status.get("authority_granted") is not False
    ):
        raise ValueError("invalid lane status")
    states = status.get("states")
    if not isinstance(states, dict) or any(states.get(name) != "passed" for name in LOCAL_STATES):
        raise ValueError("not all repository-controlled states passed")
    if states.get("target_qualification") != "not_proved" or states.get("independent_acceptance") != "not_proved":
        raise ValueError("local evidence cannot assert external qualification")
    if (
        candidate_receipt.get("schema") != "hepta.channel-matrix-candidate-receipt.v1"
        or candidate_receipt.get("status") != "PASS_CHANNEL_MATRIX_CANDIDATE_BINDING"
        or candidate_receipt.get("candidate") != {"commit": identity["commit"], "tree": identity["tree"]}
        or candidate_receipt.get("authorityGranted") is not False
    ):
        raise ValueError("candidate receipt mismatch")
    if (
        ledger.get("schema") != "hepta.channel-matrix-scenario-ledger.v2"
        or ledger.get("candidate") != {"commit": identity["commit"], "tree": identity["tree"]}
        or ledger.get("lane") != expected_lane
        or ledger.get("native_completion") != "passed"
        or ledger.get("native_blockers") != []
        or ledger.get("independent_acceptance") is not False
        or ledger.get("activation") is not False
        or ledger.get("release") is not False
        or ledger.get("authority_granted") is not False
    ):
        raise ValueError("scenario ledger is incomplete or escalates authority")
    scenarios = ledger.get("scenarios")
    if not isinstance(scenarios, list) or tuple(row.get("id") for row in scenarios) != SCENARIOS:
        raise ValueError("scenario inventory is incomplete or reordered")
    for row in scenarios:
        if row.get("candidate") != {"commit": identity["commit"], "tree": identity["tree"]}:
            raise ValueError("scenario candidate mismatch")
        if row.get("native_required") and row.get("native_fixture_result") != "passed":
            raise ValueError(f"native scenario did not pass: {row.get('id')}")
        external = row.get("external_gates")
        if not isinstance(external, list):
            raise ValueError("untyped external gate inventory")
        expected_external = "not_proved" if external else "not_applicable"
        if row.get("external_qualification") != expected_external:
            raise ValueError("external evidence was inferred locally")
    return {
        "directory": directory,
        "source": source,
        "status": status,
        "ledger": ledger,
        "manifest": manifest,
        "inventory": inventory,
        "digests": {
            "source": digest(directory / "source.json"),
            "status": digest(directory / "status.json"),
            "scenarioLedger": digest(directory / "scenario-ledger.json"),
            "manifest": digest(directory / "manifest.json"),
        },
    }


def paired(source_head: Path, base_merge: Path) -> dict[str, Any]:
    source = lane(source_head, "source-head")
    merge = lane(base_merge, "base-merge")
    source_identity = source["source"]
    merge_identity = merge["source"]
    if source_identity["testedSha"] != source_identity["sourceSha"]:
        raise ValueError("source-head lane did not test the source commit")
    if (
        merge_identity["sourceSha"] != source_identity["sourceSha"]
        or merge_identity["baseSha"] != source_identity["baseSha"]
        or merge["ledger"]["registry_sha256"] != source["ledger"]["registry_sha256"]
        or merge["ledger"]["external_gates_remaining"] != source["ledger"]["external_gates_remaining"]
    ):
        raise ValueError("lane pair does not share one source/base/scenario identity")
    return {
        "schema": "hepta.channel-matrix-paired-qualification.v1",
        "scope": "paired_repository_controlled_execution_not_target_or_release_authority",
        "sourceCandidate": {
            "commit": source_identity["sourceSha"],
            "tree": source_identity["testedTree"],
        },
        "base": source_identity["baseSha"],
        "lanes": {
            "source-head": {
                "candidate": source["status"]["candidate"],
                **source["digests"],
            },
            "base-merge": {
                "candidate": merge["status"]["candidate"],
                **merge["digests"],
            },
        },
        "scenarioRegistrySha256": source["ledger"]["registry_sha256"],
        "nativeScenarios": list(SCENARIOS),
        "allRepositoryControlledScenariosPassed": True,
        "externalGatesRemaining": source["ledger"]["external_gates_remaining"],
        "targetQualification": "not_proved",
        "independentAcceptance": "not_proved",
        "activation": False,
        "promotion": False,
        "release": False,
        "authorityGranted": False,
    }


def write_exclusive(path_value: Path, row: dict[str, Any]) -> None:
    path = path_value.absolute()
    parent = path.parent.resolve(strict=True)
    if path_value.is_symlink() or parent.is_relative_to(ROOT.resolve()) or path.exists():
        raise ValueError("output must be a new canonical file outside the checkout")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(row, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-head", type=Path, required=True)
    parser.add_argument("--base-merge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        write_exclusive(args.output, paired(args.source_head, args.base_merge))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_PAIRED_QUALIFICATION: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
