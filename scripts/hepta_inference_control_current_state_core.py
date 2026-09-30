#!/usr/bin/env python3
"""Generate and verify inference.control current-state projections and receipts.

The source manifest describes repository facts only. Exact source/tested/base
identities and command outcomes are emitted by `evidence` at CI runtime so a
committed document can never self-assert that its own future commit passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "docs/modules/inference.control/CURRENT_STATE_SOURCE.json"
CURRENT_PATH = ROOT / "docs/modules/inference.control/CURRENT_STATE.json"
MAP_PATH = ROOT / "docs/modules/inference.control/IMPLEMENTATION_MAP.json"
TECHNICAL_STATUS_PATH = (
    ROOT / "docs/modules/inference.control/TECHNICAL_STATUS.generated.md"
)
DOSSIER_STATUS_PATH = (
    ROOT
    / "qualification/module-execution-dossiers/detail/inference.control.current-state.md"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_source(source: dict[str, Any]) -> None:
    require(
        source.get("schema") == "hepta.inference-control-current-state-source.v1",
        "invalid current-state source schema",
    )
    require(source.get("schemaVersion") == 1, "invalid source schema version")
    require(source.get("module") == "inference.control", "invalid module identity")
    provenance = source.get("provenance") or {}
    for field in ("baselineCommit", "baselineTree"):
        value = provenance.get(field)
        require(
            isinstance(value, str) and SHA_PATTERN.fullmatch(value) is not None,
            f"invalid provenance {field}",
        )
    ownership = source.get("ownership") or {}
    roots = ownership.get("declaredRoots")
    require(isinstance(roots, list) and roots, "declared roots must be nonempty")
    require(len(roots) == len(set(roots)), "declared roots must be unique")
    for root in roots:
        require(isinstance(root, str) and root, "invalid declared root")
        require((ROOT / root).is_dir(), f"missing declared root: {root}")
    evidence_roots = ownership.get("sourceEvidenceRoots")
    require(
        isinstance(evidence_roots, list) and evidence_roots,
        "source evidence roots must be nonempty",
    )
    for value in evidence_roots:
        require(isinstance(value, str) and value, "invalid source evidence root")
        require((ROOT / value).exists(), f"missing source evidence root: {value}")
    status = source.get("status") or {}
    for field in (
        "sourceImplementation",
        "productCallerState",
        "productionWriterState",
    ):
        require(
            isinstance(status.get(field), str) and bool(status[field].strip()),
            f"status {field} must be a nonempty string",
        )
    for field in (
        "productionImplementation",
        "productExecutionProved",
        "targetHostQualification",
        "independentAcceptance",
        "activation",
        "release",
    ):
        require(isinstance(status.get(field), bool), f"status {field} must be bool")
    require(
        not status["release"] or status["activation"],
        "release cannot be true without activation",
    )
    require(
        not status["activation"] or status["independentAcceptance"],
        "activation cannot be true without independent acceptance",
    )
    repository_gaps = source.get("repositoryControlledGaps")
    require(
        isinstance(repository_gaps, list),
        "repository-controlled gaps must be a list",
    )
    require(
        len(repository_gaps) == len(set(repository_gaps)),
        "repository-controlled gaps must be unique",
    )
    for index, gap in enumerate(repository_gaps):
        require(
            isinstance(gap, str) and bool(gap.strip()),
            f"repository-controlled gap {index} must be a nonempty string",
        )
    external_gates = source.get("externalEvidenceGates")
    require(isinstance(external_gates, list), "external evidence gates must be a list")
    require(
        len(external_gates) == len(set(external_gates)),
        "external evidence gates must be unique",
    )
    for index, gate in enumerate(external_gates):
        require(
            isinstance(gate, str) and bool(gate.strip()),
            f"external evidence gate {index} must be a nonempty string",
        )
    operations = source.get("operations")
    require(isinstance(operations, list) and operations, "operations must be nonempty")
    names: set[str] = set()
    for index, operation in enumerate(operations):
        require(isinstance(operation, dict), f"operation {index} must be an object")
        name = operation.get("operation")
        require(isinstance(name, str) and name, f"operation {index} missing identity")
        require(name not in names, f"duplicate operation: {name}")
        names.add(name)
        source_path = operation.get("sourcePath")
        symbol = operation.get("nativeSymbol")
        require(isinstance(source_path, str), f"{name}: missing source path")
        require(isinstance(symbol, str) and symbol, f"{name}: missing symbol")
        path = ROOT / source_path
        require(path.is_file(), f"{name}: source path does not exist: {source_path}")
        text = path.read_text(encoding="utf-8")
        leaf_symbol = symbol.split("::")[-1]
        require(
            leaf_symbol in text,
            f"{name}: symbol marker {leaf_symbol!r} not found in {source_path}",
        )
        tests = operation.get("tests")
        require(isinstance(tests, list) and tests, f"{name}: tests must be nonempty")
        for reference in tests:
            require(isinstance(reference, str) and bool(reference), f"{name}: invalid test reference")
            test_path, separator, test_name = reference.partition("::")
            relative = Path(test_path)
            require(not relative.is_absolute() and ".." not in relative.parts,
                    f"{name}: unsafe test path")
            test_file = ROOT / relative
            require(test_file.is_file(), f"{name}: missing test source: {test_path}")
            if separator:
                require(test_file.suffix == ".rs" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", test_name) is not None,
                        f"{name}: invalid Rust test identity")
                require(re.search(r"\bfn\s+" + re.escape(test_name) + r"\s*\(",
                                  test_file.read_text(encoding="utf-8")) is not None,
                        f"{name}: missing Rust test: {test_name}")
    qualification = source.get("qualification") or {}
    workflow = qualification.get("requiredWorkflow")
    require(isinstance(workflow, str) and (ROOT / workflow).is_file(), "missing workflow")
    commands = qualification.get("commands")
    require(isinstance(commands, list) and commands, "qualification commands missing")


def build_current(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "hepta.inference-control-current-state.v1",
        "schemaVersion": 1,
        "module": source["module"],
        "generatedFrom": str(SOURCE_PATH.relative_to(ROOT)),
        "sourceManifestSha256": sha256_bytes(SOURCE_PATH.read_bytes()),
        "provenance": source["provenance"],
        "ownership": source["ownership"],
        "status": source["status"],
        "safetyInvariants": source["safetyInvariants"],
        "operations": source["operations"],
        "qualification": source["qualification"],
        "repositoryControlledGaps": source["repositoryControlledGaps"],
        "externalEvidenceGates": source["externalEvidenceGates"],
    }


def build_map(source: dict[str, Any]) -> dict[str, Any]:
    status = source["status"]
    ownership = source["ownership"]
    operations = []
    for operation in source["operations"]:
        operations.append(
            {
                **operation,
                "designOperation": operation["operation"],
                "mappingClass": "owner_native",
                "sourcePathExists": True,
                "authority": "none_minted_by_execution_owner",
            }
        )
    repository_gaps = source["repositoryControlledGaps"]
    return {
        "schema": "hepta.module-implementation-map.v3",
        "schemaVersion": 3,
        "sourceBase": {
            "commit": source["provenance"]["baselineCommit"],
            "tree": source["provenance"]["baselineTree"],
            "kind": "integration_provenance_anchor",
        },
        "sourceIdentityPolicy": "exact_ci_receipt_v1",
        "laneId": source["laneId"],
        "module": source["module"],
        "owner": source["owner"],
        "deputy": source["deputy"],
        "technicalGuide": "docs/modules/inference.control/TECHNICAL.md",
        "generatedStatus": str(TECHNICAL_STATUS_PATH.relative_to(ROOT)),
        "currentState": str(CURRENT_PATH.relative_to(ROOT)),
        "declaredRoots": ownership["declaredRoots"],
        "resolvedRoots": ownership["declaredRoots"],
        "sourceRoot": ownership["declaredRoots"],
        "sourceRootPresent": True,
        "sourceEvidenceRoots": ownership["sourceEvidenceRoots"],
        "productionImplementation": status["productionImplementation"],
        "productCallerState": status["productCallerState"],
        "productionWriterState": status["productionWriterState"],
        "productCallerBindingPolicy": "closed_world",
        "productCallerBindings": [
            {
                "callerPath": "codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs",
                "mustContain": "run_authorized",
            },
            {
                "callerPath": "codex-rs/hepta-infer-worker-host/src/native_run_control.rs",
                "mustContain": "bind_native_execution",
            },
        ],
        "productionWriterBindingPolicy": "closed_world",
        "productionWriterBindings": [
            {
                "sourcePath": "codex-rs/hepta-infer-core/src/durable_control.rs",
                "mustContain": "DurableInferenceControl",
            },
            {
                "sourcePath": "codex-rs/hepta-infer-core/src/native_control_v2_control_c.rs",
                "mustContain": "compact_native_journal_inner",
            },
        ],
        "operations": operations,
        "claimBoundary": {
            "implementedOperationMappingComplete": True,
            "nativeSourceMappingComplete": True,
            "repositoryControlledSourceBoundaryGapsClosed": not bool(
                repository_gaps
            ),
            "sourceRootPresent": True,
            "productionImplementation": status["productionImplementation"],
            "productExecutionProved": status["productExecutionProved"],
            "targetHostQualification": status["targetHostQualification"],
            "independentAcceptance": status["independentAcceptance"],
            "activation": status["activation"],
            "release": status["release"],
        },
        "repositoryControlledGaps": repository_gaps,
        "externalEvidenceGates": source["externalEvidenceGates"],
    }


def render_status(source: dict[str, Any]) -> str:
    status = source["status"]
    lines = [
        "<!-- GENERATED BY scripts/hepta-inference-control-current-state.py; DO NOT EDIT -->",
        "# inference.control generated implementation status",
        "",
        f"Source: `{SOURCE_PATH.relative_to(ROOT)}`.",
        "Exact candidate success is not stored here; it is carried by a CI evidence receipt.",
        "",
        "## Current source facts",
        "",
        f"- Source implementation: `{status['sourceImplementation']}`",
        f"- Product caller: `{status['productCallerState']}`",
        f"- Production writer: `{status['productionWriterState']}`",
        f"- Production implementation qualified: `{str(status['productionImplementation']).lower()}`",
        f"- Product execution proved: `{str(status['productExecutionProved']).lower()}`",
        f"- Target-host qualification: `{str(status['targetHostQualification']).lower()}`",
        f"- Independent acceptance: `{str(status['independentAcceptance']).lower()}`",
        f"- Activation: `{str(status['activation']).lower()}`",
        f"- Release: `{str(status['release']).lower()}`",
        "",
        "## Formal roots",
        "",
    ]
    lines.extend(f"- `{root}`" for root in source["ownership"]["declaredRoots"])
    lines.extend(
        [
            "",
            "## Operation inventory",
            "",
            "| Operation | State | Source | Tests |",
            "| --- | --- | --- | ---: |",
        ]
    )
    for operation in source["operations"]:
        lines.append(
            f"| `{operation['operation']}` | `{operation['state']}` | "
            f"`{operation['sourcePath']}` | {len(operation['tests'])} |"
        )
    lines.extend(["", "## Repository-controlled gaps", ""])
    lines.extend(f"- {gap}" for gap in source["repositoryControlledGaps"])
    lines.extend(["", "## External evidence gates", ""])
    lines.extend(f"- {gate}" for gate in source["externalEvidenceGates"])
    return "\n".join(lines) + "\n"


def render_dossier(source: dict[str, Any]) -> str:
    lines = [
        "<!-- GENERATED BY scripts/hepta-inference-control-current-state.py; DO NOT EDIT -->",
        "# inference.control current-state execution dossier",
        "",
        f"Parent design: `docs/modules/inference.control/TECHNICAL.md`. Lane: `{source['laneId']}`.",
        "This projection records source facts and required evidence. It is not an acceptance or release receipt.",
        "",
        "## Safety case",
        "",
    ]
    lines.extend(f"- {value}" for value in source["safetyInvariants"])
    lines.extend(["", "## Required exact-candidate commands", ""])
    lines.extend(f"- `{value}`" for value in source["qualification"]["commands"])
    lines.extend(["", "## Required lanes", ""])
    lines.extend(f"- `{value}`" for value in source["qualification"]["requiredLanes"])
    lines.extend(
        [
            "",
            "## Evidence rule",
            "",
            "A qualifying run must emit `hepta.inference-control-evidence.v1` binding source SHA, tested SHA, base SHA, candidate tree, lane, check-run URLs and hashed command records. A base-merge lane must test the synthetic merge SHA, not the source head.",
            "",
            "Independent acceptance, activation and release remain externally governed even when all repository checks pass.",
        ]
    )
    return "\n".join(lines) + "\n"


def projections(source: dict[str, Any]) -> dict[Path, str]:
    return {
        CURRENT_PATH: canonical_json(build_current(source)),
        MAP_PATH: canonical_json(build_map(source)),
        TECHNICAL_STATUS_PATH: render_status(source),
        DOSSIER_STATUS_PATH: render_dossier(source),
    }


def sync() -> None:
    source = load_json(SOURCE_PATH)
    validate_source(source)
    for path, rendered in projections(source).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "generated": [
                    str(path.relative_to(ROOT)) for path in projections(source)
                ]
            },
            ensure_ascii=False,
        )
    )


def check() -> None:
    source = load_json(SOURCE_PATH)
    validate_source(source)
    failures: list[str] = []
    for path, expected in projections(source).items():
        if not path.is_file():
            failures.append(f"missing generated file: {path.relative_to(ROOT)}")
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            failures.append(f"stale generated file: {path.relative_to(ROOT)}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        json.dumps(
            {
                "checked": [
                    str(path.relative_to(ROOT)) for path in projections(source)
                ]
            },
            ensure_ascii=False,
        )
    )


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def command_record(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    require(raw, f"empty command record: {path}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid command record {path}: {exc}") from exc
    exit_code = None
    if isinstance(parsed, dict):
        for key in ("exit_code", "exitCode", "returncode", "returnCode"):
            if key in parsed:
                exit_code = parsed[key]
                break
    return {
        "name": path.name,
        "sha256": sha256_bytes(raw),
        "bytes": len(raw),
        "exitCode": exit_code,
    }



# Match the actual command inventories of hepta-inference-maintenance.yml.
# This receipt is a CI observation, never independent release authorization.
OWNER_RECORDS = {
    "00-candidate.json", "01-current-state.json", "01a-ownership.json",
    "01b-actor-migration.json", "01c-boundary-planning.json", "02-implementation-maps.json",
    "03-runner.json", "04-controls-scope.json", "05-cargo-metadata.json",
    "06-tests.json", "07-clippy.json", "08-maintenance-scale.json", "09-format.json",
}
NATIVE_RECORDS = {
    "00-current-state.json", "00a-ownership.json", "00b-actor-migration.json",
    "00c-boundary-planning.json", "01-implementation-maps.json", "02-native-host.json",
    "03-durable-faults.json", "04-checkpoint-tamper.json", "05-process-crash.json",
    "06-expired-recovery.json", "07-clippy.json", "08-format.json",
}


def record_failures(paths: list[Path], args: argparse.Namespace) -> list[str]:
    """Reject partial, stale, dirty or log-detached claims of a full lane pass."""
    failures = []
    names = [path.name for path in paths]
    expected = NATIVE_RECORDS if args.lane == "native-host" else OWNER_RECORDS
    if len(names) != len(set(names)) or set(names) != expected:
        failures.append("command record inventory is incomplete, duplicated or unexpected")
    for path in paths:
        value = load_json(path)
        identity = {"source_sha": args.source_sha, "tested_sha": args.tested_sha,
                    "base_sha": args.base_sha, "lane": args.lane}
        if any(value.get(key) != expected_value for key, expected_value in identity.items()):
            failures.append(f"{path.name}: command identity mismatch")
        if type(value.get("exit_code")) is not int or value["exit_code"] != 0 or value.get("status") != "passed":
            failures.append(f"{path.name}: command did not pass")
        for phase in ("before", "after"):
            observed = value.get(phase) or {}
            if observed.get("commit") != args.tested_sha or observed.get("tree") != args.candidate_tree or observed.get("dirty") is not False:
                failures.append(f"{path.name}: {phase} source is stale or dirty")
        log_name = value.get("log_file")
        if not isinstance(log_name, str) or Path(log_name).name != log_name or log_name in {"", ".", ".."}:
            failures.append(f"{path.name}: invalid log path")
            continue
        log = path.parent / log_name
        if not log.is_file() or log.is_symlink():
            failures.append(f"{path.name}: missing regular command log")
            continue
        raw = log.read_bytes()
        if type(value.get("log_bytes")) is not int or len(raw) != value["log_bytes"] or sha256_bytes(raw) != value.get("log_sha256"):
            failures.append(f"{path.name}: log identity mismatch")
        if value.get("timed_out") is not False or value.get("output_limit_exceeded") is not False:
            failures.append(f"{path.name}: command timed out or exceeded output bound")
    return failures


def evidence(args: argparse.Namespace) -> None:
    for label, value in (
        ("source SHA", args.source_sha),
        ("tested SHA", args.tested_sha),
        ("base SHA", args.base_sha),
        ("candidate tree", args.candidate_tree),
    ):
        require(SHA_PATTERN.fullmatch(value) is not None, f"invalid {label}")
    require(args.lane in {"source-head", "base-merge", "native-host"}, "invalid lane")
    if args.lane == "source-head":
        require(args.source_sha == args.tested_sha, "source-head must test source SHA")
    if args.lane == "base-merge":
        require(args.source_sha != args.tested_sha, "base-merge must test synthetic merge SHA")
    records = [command_record(Path(value)) for value in args.command_record]
    require(records, "at least one command record is required")
    failures = record_failures([Path(value) for value in args.command_record], args)
    all_zero = not failures
    current = load_json(CURRENT_PATH)
    receipt = {
        "schema": "hepta.inference-control-evidence.v1",
        "schemaVersion": 1,
        "module": "inference.control",
        "lane": args.lane,
        "sourceSha": args.source_sha,
        "testedSha": args.tested_sha,
        "baseSha": args.base_sha,
        "candidateTree": args.candidate_tree,
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "workflowRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "checkRunUrls": args.check_run_url,
        "currentStateSha256": sha256_bytes(CURRENT_PATH.read_bytes()),
        "sourceManifestSha256": current["sourceManifestSha256"],
        "commandRecords": records,
        "failureReasons": failures,
        "repositoryQualificationPassed": all_zero,
        "claims": {
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_json(receipt), encoding="utf-8")
    print(json.dumps({"evidence": str(output), "passed": all_zero}))
    if not all_zero:
        raise SystemExit("; ".join(failures))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    subcommands = value.add_subparsers(dest="command", required=True)
    subcommands.add_parser("sync")
    subcommands.add_parser("check")
    evidence_parser = subcommands.add_parser("evidence")
    evidence_parser.add_argument("--lane", required=True)
    evidence_parser.add_argument("--source-sha", required=True)
    evidence_parser.add_argument("--tested-sha", required=True)
    evidence_parser.add_argument("--base-sha", required=True)
    evidence_parser.add_argument("--candidate-tree", required=True)
    evidence_parser.add_argument("--check-run-url", action="append", default=[])
    evidence_parser.add_argument("--command-record", action="append", default=[])
    evidence_parser.add_argument("--output", required=True)
    return value


def main() -> None:
    args = parser().parse_args()
    try:
        if args.command == "sync":
            sync()
        elif args.command == "check":
            check()
        else:
            evidence(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
