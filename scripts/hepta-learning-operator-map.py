#!/usr/bin/env python3
"""Derive an exact candidate-bound learning.operator implementation map."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = Path("docs/modules/learning.operator/IMPLEMENTATION_MAP.json")
SCHEMA = "hepta.module-implementation-observation.v1"
OBSERVED_PATHS = (
    "codex-rs/hepta-bellman-operator",
    "codex-rs/hepta-agentd/src/cognitive_ranker.rs",
    "codex-rs/hepta-agentd/src/shared_terminal_cell.rs",
    "codex-rs/hepta-agentd/tests/terminal_cell_owner.rs",
    "codex-rs/hepta-shadow-qualification/tests/lane_e_api_contract.rs",
    ".github/workflows/learning-operator-required.yml",
    ".github/workflows/blocking-ci.yml",
)
DEFAULT_SURFACE = (
    "TrainingProfileV1",
    "WorldModelProfileV1",
    "WorkControlV1",
    "build_sensor_core_controlled_v2",
    "fit_tabular_operator_strict_controlled_v3",
    "verify_tabular_operator_plan_v3",
    "fit_tabular_operator_verified_v3",
    "revalidate_tabular_candidate_for_publication_v3",
    "PreparedTabularPayloadV3::into_loaded",
    "verify_world_model_dataset_v3",
    "fit_transition_model_verified_v3",
    "revalidate_world_model_candidate_for_publication_v3",
)


def run(*args: str) -> bytes:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def git_text(*args: str) -> str:
    return run("git", *args).decode("utf-8").strip()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_hex(value: str, length: int, label: str) -> str:
    if len(value) != length:
        raise ValueError(f"invalid {label}")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"invalid {label}") from error
    return value


def source_blob(path: str) -> bytes:
    return run("git", "show", f":{path}")


def source_object(path: str) -> str:
    # Use the candidate index tree rather than HEAD so this works for the
    # unpushed deterministic merge tree as well as the exact source commit.
    candidate_tree = git_text("write-tree")
    return git_text("rev-parse", f"{candidate_tree}:{path}")


def operation_inventory(source: dict[str, Any]) -> list[dict[str, Any]]:
    operations = source.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("implementation map has no operation inventory")
    observed: list[dict[str, Any]] = []
    for item in operations:
        if not isinstance(item, dict):
            raise ValueError("invalid implementation-map operation")
        name = item.get("operation")
        source_path = item.get("sourcePath")
        if not isinstance(name, str) or not isinstance(source_path, str):
            raise ValueError("operation is missing name or sourcePath")
        path = ROOT / source_path
        observed.append(
            {
                "operation": name,
                "nativeSymbol": item.get("nativeSymbol"),
                "sourcePath": source_path,
                "sourcePathExists": path.exists(),
                "state": item.get("state"),
                "authority": item.get("authority"),
            }
        )
    return observed


def derive(args: argparse.Namespace) -> dict[str, Any]:
    source_sha = require_hex(args.source_sha, 40, "source SHA")
    candidate_sha = require_hex(args.candidate_sha, 40, "candidate SHA")
    candidate_tree = require_hex(args.candidate_tree, 40, "candidate tree")
    base_sha = require_hex(args.base_sha, 40, "base SHA") if args.base_sha else None
    if git_text("rev-parse", f"{candidate_sha}^{{tree}}") != candidate_tree:
        raise ValueError("candidate commit/tree mismatch")
    if git_text("write-tree") != candidate_tree:
        raise ValueError("candidate tree does not match checked-out index")
    if args.mode == "exact-source":
        if source_sha != candidate_sha:
            raise ValueError("exact-source candidate must equal source")
    elif args.mode == "synthetic-merge":
        if base_sha is None:
            raise ValueError("synthetic merge requires base SHA")
        if git_text("rev-parse", f"{candidate_sha}^1") != base_sha:
            raise ValueError("synthetic merge first parent mismatch")
        if git_text("rev-parse", f"{candidate_sha}^2") != source_sha:
            raise ValueError("synthetic merge second parent mismatch")
    else:
        raise ValueError("invalid observation mode")

    raw = source_blob(str(SOURCE_MAP))
    source = json.loads(raw.decode("utf-8"))
    if source.get("module") != "learning.operator":
        raise ValueError("unexpected implementation map module")
    refreshed = copy.deepcopy(source)
    refreshed["observedAtHead"] = {
        "mode": args.mode,
        "sourceCommit": source_sha,
        "baseCommit": base_sha,
        "candidateCommit": candidate_sha,
        "candidateTree": candidate_tree,
        "generatedAt": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    refreshed["sourceIdentityPolicy"] = "exact_candidate_and_ordered_parent_merge_v2"

    source_objects = []
    for path in OBSERVED_PATHS:
        if not (ROOT / path).exists():
            raise ValueError(f"missing observed path: {path}")
        source_objects.append({"path": path, "object": source_object(path)})

    claim = refreshed.get("claimBoundary")
    if not isinstance(claim, dict):
        raise ValueError("missing claim boundary")
    observation = {
        "schema": SCHEMA,
        "module": "learning.operator",
        "sourceMap": {
            "path": str(SOURCE_MAP),
            "sha256": sha256(raw),
        },
        "observedAtHead": refreshed["observedAtHead"],
        "refreshedImplementationMap": refreshed,
        "observedOperations": operation_inventory(refreshed),
        "observedSourceObjects": source_objects,
        "defaultPublicSurface": list(DEFAULT_SURFACE),
        "compatibilitySurface": {
            "feature": "compatibility-api",
            "defaultEnabled": False,
            "sourcePath": "codex-rs/hepta-bellman-operator/Cargo.toml",
        },
        "qualification": {
            "workflow": ".github/workflows/learning-operator-required.yml",
            "workflowObject": source_object(
                ".github/workflows/learning-operator-required.yml"
            ),
            "skipAccepted": False,
            "productionActivation": False,
            "independentAcceptance": bool(claim.get("independentAcceptance", False)),
        },
        "authority": "DENY_ALL",
    }
    return observation


def verify(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA or document.get("module") != "learning.operator":
        raise ValueError("unexpected implementation observation")
    identity = document.get("observedAtHead")
    if not isinstance(identity, dict):
        raise ValueError("missing observedAtHead")
    require_hex(str(identity.get("sourceCommit", "")), 40, "source SHA")
    require_hex(str(identity.get("candidateCommit", "")), 40, "candidate SHA")
    require_hex(str(identity.get("candidateTree", "")), 40, "candidate tree")
    source_map = document.get("sourceMap")
    if not isinstance(source_map, dict):
        raise ValueError("missing source map binding")
    if source_map.get("sha256") != sha256(source_blob(str(SOURCE_MAP))):
        raise ValueError("source implementation map drift")
    if document.get("authority") != "DENY_ALL":
        raise ValueError("implementation observation grants authority")
    qualification = document.get("qualification")
    if not isinstance(qualification, dict) or qualification.get("skipAccepted") is not False:
        raise ValueError("implementation observation accepts skipped qualification")
    if qualification.get("productionActivation") is not False:
        raise ValueError("implementation observation activates production")
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("emit")
    emit.add_argument("--mode", choices=("exact-source", "synthetic-merge"), required=True)
    emit.add_argument("--source-sha", required=True)
    emit.add_argument("--base-sha", default="")
    emit.add_argument("--candidate-sha", required=True)
    emit.add_argument("--candidate-tree", required=True)
    emit.add_argument("--output", required=True)
    check = sub.add_parser("verify")
    check.add_argument("path")
    args = parser.parse_args()
    try:
        if args.command == "emit":
            document = derive(args)
            output = ROOT / args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            document = verify(ROOT / args.path)
        print(json.dumps(document, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"learning.operator map failure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
