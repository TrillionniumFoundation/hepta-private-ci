#!/usr/bin/env python3
"""Emit and verify immutable learning.operator qualification manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_GATES = {
    "coverage",
    "default-api-surface",
    "documentation-map",
    "exact-head",
    "fresh-process-load",
    "lifecycle-state-space",
    "module-tests",
    "mutation-profile",
    "payload-replay",
    "performance-profile",
    "product-shadow-e2e",
    "static-quality",
    "synthetic-merge",
    "target-build",
    "workspace-all-targets",
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_sha(value: object, label: str) -> str:
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None,
        f"{label} must be a literal SHA-1 identity",
    )
    return value


def git(*args: str) -> str:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def relative_file(value: str, label: str) -> Path:
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts, f"{label} path escapes root")
    resolved = ROOT / path
    require(resolved.is_file(), f"{label} file absent: {value}")
    return resolved


def parse_evidence(values: list[str]) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    names: set[str] = set()
    for value in values:
        require("=" in value, "--evidence requires NAME=PATH")
        name, raw_path = value.split("=", 1)
        require(bool(name) and name not in names, f"duplicate evidence name: {name!r}")
        names.add(name)
        result.append((name, relative_file(raw_path, f"evidence {name}")))
    return sorted(result, key=lambda item: item[0])


def emit(args: argparse.Namespace) -> None:
    source_sha = require_sha(args.source_sha, "source SHA")
    source_tree = require_sha(args.source_tree, "source tree")
    workflow_blob = require_sha(args.workflow_blob, "workflow blob")
    main_sha = require_sha(args.main_sha, "main SHA")
    synthetic_sha = require_sha(args.synthetic_sha, "synthetic SHA")
    synthetic_tree = require_sha(args.synthetic_tree, "synthetic tree")
    require(git("rev-parse", f"{source_sha}^{{tree}}") == source_tree, "source SHA/tree mismatch")
    require(
        git("rev-parse", f"{source_sha}:{args.workflow_path}") == workflow_blob,
        "workflow blob is not part of the source candidate",
    )
    require(git("rev-parse", f"{synthetic_sha}^{{tree}}") == synthetic_tree, "synthetic SHA/tree mismatch")
    require(git("rev-parse", f"{synthetic_sha}^1") == main_sha, "synthetic first parent mismatch")
    require(git("rev-parse", f"{synthetic_sha}^2") == source_sha, "synthetic second parent mismatch")

    lock = relative_file("codex-rs/Cargo.lock", "dependency lock")
    rustc = relative_file(args.rustc_file, "compiler evidence")
    runner = relative_file(args.runner_file, "runner evidence")
    test_set = relative_file(args.test_set_file, "test-set evidence")
    implementation_map = relative_file(args.implementation_map, "implementation map")
    map_value = json.loads(implementation_map.read_text(encoding="utf-8"))
    require(
        map_value.get("source") == {"sha": source_sha, "tree": source_tree},
        "implementation map is not bound to the source candidate",
    )

    evidence_rows = []
    for name, path in parse_evidence(args.evidence):
        value = json.loads(path.read_text(encoding="utf-8"))
        require(
            value.get("module") == "learning.operator"
            and value.get("sourceSha") == source_sha
            and value.get("sourceTree") == source_tree
            and value.get("status") == "pass",
            f"{name}: gate receipt is not a passing source-bound result",
        )
        evidence_rows.append(
            {
                "name": name,
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
            }
        )
    observed = {row["name"] for row in evidence_rows}
    require(
        REQUIRED_GATES.issubset(observed),
        "qualification evidence is incomplete: "
        + ", ".join(sorted(REQUIRED_GATES - observed)),
    )

    payload: dict[str, object] = {
        "schema": "hepta.learning-operator-qualification-manifest.v3",
        "schemaVersion": 3,
        "module": "learning.operator",
        "source": {
            "sha": source_sha,
            "tree": source_tree,
            "authoritativeCandidate": True,
        },
        "currentMain": {"sha": main_sha},
        "workflow": {
            "path": args.workflow_path,
            "blobSha": workflow_blob,
            "runId": str(args.workflow_run_id),
            "runAttempt": str(args.workflow_run_attempt),
        },
        "dependencyLock": {
            "path": str(lock.relative_to(ROOT)),
            "sha256": sha256(lock),
        },
        "compiler": {
            "target": args.target,
            "evidencePath": str(rustc.relative_to(ROOT)),
            "sha256": sha256(rustc),
        },
        "runner": {
            "evidencePath": str(runner.relative_to(ROOT)),
            "sha256": sha256(runner),
        },
        "testSet": {
            "evidencePath": str(test_set.relative_to(ROOT)),
            "sha256": sha256(test_set),
        },
        "implementationMap": {
            "path": str(implementation_map.relative_to(ROOT)),
            "sha256": sha256(implementation_map),
            "sourceSha": source_sha,
            "sourceTree": source_tree,
        },
        "syntheticMerge": {
            "sha": synthetic_sha,
            "tree": synthetic_tree,
            "parents": [main_sha, source_sha],
            "deterministicCommitMetadata": True,
        },
        "evidence": evidence_rows,
        "independentAcceptanceIdentity": None,
        "externalGates": {
            "status": "unissued_external_gate",
            "independentScientificAcceptance": False,
            "targetHostBenchmarkAcceptance": False,
            "futureWindowEfficacy": False,
            "operatorAcceptance": False,
            "canaryAcceptance": False,
            "promotion": False,
            "activation": False,
            "release": False,
        },
        "claimBoundary": {
            "repositoryQualificationEvidence": True,
            "singleUseFinalUseCapabilities": True,
            "defaultShadowOnlyCoordinator": True,
            "activation": False,
            "release": False,
        },
    }
    payload["aggregateEvidenceSha256"] = hashlib.sha256(
        canonical_bytes(payload)
    ).hexdigest()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    verify(output, expected_sha=source_sha, expected_tree=source_tree)


def verify(
    path: Path,
    *,
    expected_sha: str | None = None,
    expected_tree: str | None = None,
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(
        value.get("schema") == "hepta.learning-operator-qualification-manifest.v3"
        and value.get("schemaVersion") == 3
        and value.get("module") == "learning.operator",
        "qualification manifest schema or module mismatch",
    )
    source = value.get("source", {})
    source_sha = require_sha(source.get("sha"), "source SHA")
    source_tree = require_sha(source.get("tree"), "source tree")
    if expected_sha is not None:
        require(source_sha == expected_sha, "manifest source SHA differs from expected")
    if expected_tree is not None:
        require(source_tree == expected_tree, "manifest source tree differs from expected")
    require(git("rev-parse", f"{source_sha}^{{tree}}") == source_tree, "manifest source SHA/tree mismatch")

    workflow = value.get("workflow", {})
    workflow_path = workflow.get("path")
    require(isinstance(workflow_path, str), "workflow path absent")
    workflow_blob = require_sha(workflow.get("blobSha"), "workflow blob")
    require(git("rev-parse", f"{source_sha}:{workflow_path}") == workflow_blob, "workflow blob drift")
    require(bool(str(workflow.get("runId", ""))), "workflow run ID absent")
    require(bool(str(workflow.get("runAttempt", ""))), "workflow run attempt absent")

    main_sha = require_sha(value.get("currentMain", {}).get("sha"), "main SHA")
    synthetic = value.get("syntheticMerge", {})
    synthetic_sha = require_sha(synthetic.get("sha"), "synthetic SHA")
    synthetic_tree = require_sha(synthetic.get("tree"), "synthetic tree")
    require(git("rev-parse", f"{synthetic_sha}^{{tree}}") == synthetic_tree, "synthetic tree drift")
    require(git("rev-parse", f"{synthetic_sha}^1") == main_sha, "synthetic first parent drift")
    require(git("rev-parse", f"{synthetic_sha}^2") == source_sha, "synthetic second parent drift")

    for key in ("dependencyLock", "compiler", "runner", "testSet", "implementationMap"):
        row = value.get(key, {})
        path_key = "path" if key in {"dependencyLock", "implementationMap"} else "evidencePath"
        artifact = relative_file(str(row.get(path_key, "")), key)
        require(sha256(artifact) == row.get("sha256"), f"{key} digest drift")
    implementation_row = value["implementationMap"]
    implementation_path = relative_file(implementation_row["path"], "implementation map")
    implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
    require(
        implementation.get("source") == {"sha": source_sha, "tree": source_tree},
        "implementation map source drift",
    )

    observed: set[str] = set()
    evidence = value.get("evidence")
    require(isinstance(evidence, list), "evidence inventory absent")
    for row in evidence:
        require(isinstance(row, dict), "evidence row malformed")
        name = row.get("name")
        require(isinstance(name, str) and name not in observed, "duplicate evidence name")
        evidence_path = relative_file(str(row.get("path", "")), f"evidence {name}")
        require(sha256(evidence_path) == row.get("sha256"), f"{name}: evidence digest drift")
        gate = json.loads(evidence_path.read_text(encoding="utf-8"))
        require(
            gate.get("module") == "learning.operator"
            and gate.get("sourceSha") == source_sha
            and gate.get("sourceTree") == source_tree
            and gate.get("status") == "pass",
            f"{name}: gate source/status drift",
        )
        observed.add(name)
    require(REQUIRED_GATES.issubset(observed), "required gate inventory incomplete")

    external = value.get("externalGates", {})
    require(external.get("status") == "unissued_external_gate", "external gate claim drift")
    for key in (
        "independentScientificAcceptance",
        "targetHostBenchmarkAcceptance",
        "futureWindowEfficacy",
        "operatorAcceptance",
        "canaryAcceptance",
        "promotion",
        "activation",
        "release",
    ):
        require(external.get(key) is False, f"repository cannot self-issue {key}")
    require(value.get("independentAcceptanceIdentity") is None, "independent acceptance identity must be absent")

    aggregate = value.pop("aggregateEvidenceSha256", None)
    require(
        aggregate == hashlib.sha256(canonical_bytes(value)).hexdigest(),
        "aggregate qualification digest mismatch",
    )
    value["aggregateEvidenceSha256"] = aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    emit_parser = subparsers.add_parser("emit")
    emit_parser.add_argument("--source-sha", required=True)
    emit_parser.add_argument("--source-tree", required=True)
    emit_parser.add_argument("--workflow-path", required=True)
    emit_parser.add_argument("--workflow-blob", required=True)
    emit_parser.add_argument("--workflow-run-id", required=True)
    emit_parser.add_argument("--workflow-run-attempt", required=True)
    emit_parser.add_argument("--main-sha", required=True)
    emit_parser.add_argument("--synthetic-sha", required=True)
    emit_parser.add_argument("--synthetic-tree", required=True)
    emit_parser.add_argument("--target", required=True)
    emit_parser.add_argument("--rustc-file", required=True)
    emit_parser.add_argument("--runner-file", required=True)
    emit_parser.add_argument("--test-set-file", required=True)
    emit_parser.add_argument("--implementation-map", required=True)
    emit_parser.add_argument("--evidence", action="append", default=[])
    emit_parser.add_argument("--output", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--path", required=True)
    verify_parser.add_argument("--expected-source-sha")
    verify_parser.add_argument("--expected-source-tree")
    args = parser.parse_args()
    if args.command == "emit":
        emit(args)
    else:
        verify(
            relative_file(args.path, "qualification manifest"),
            expected_sha=args.expected_source_sha,
            expected_tree=args.expected_source_tree,
        )


if __name__ == "__main__":
    main()
