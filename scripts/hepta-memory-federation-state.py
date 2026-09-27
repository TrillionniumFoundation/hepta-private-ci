#!/usr/bin/env python3
"""Generate and verify the memory.federation current-state projection.

The generated documents deliberately avoid a Git fixed-point: source files and
runtime documents are committed first, then this tool records that source
commit and exact path objects in metadata-only files.  A later qualification
receipt binds the exact tested metadata candidate without changing source.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE = "memory.federation"
MAP_PATH = ROOT / "docs/modules/memory.federation/IMPLEMENTATION_MAP.json"
STATE_PATH = ROOT / "docs/modules/memory.federation/CURRENT_STATE.json"
VERIFY_PATH = ROOT / "qualification/memory-federation/FINAL_V2_VERIFICATION.md"
DOSSIER_PATH = ROOT / "qualification/module-execution-dossiers/detail/memory.federation.md"
RECEIPT_ROOT = ROOT / "qualification/memory-federation/receipts"
BEGIN = "<!-- BEGIN GENERATED MEMORY.FEDERATION CURRENT STATE -->"
END = "<!-- END GENERATED MEMORY.FEDERATION CURRENT STATE -->"

# These paths are the closed source/document/workflow surface whose exact Git
# objects define the module candidate. Generated metadata and receipts are
# intentionally excluded to avoid self-reference.
SOURCE_PATHS = [
    ".github/workflows/memory-federation-v2-final-verify.yml",
    "codex-rs/Cargo.lock",
    "codex-rs/Cargo.toml",
    "codex-rs/ext/hepta-memory/Cargo.toml",
    "codex-rs/ext/hepta-memory/src/cognitive/federation.rs",
    "codex-rs/hepta-agentd/src/runtime.rs",
    "codex-rs/hepta-memory-federation",
    "codex-rs/hepta-memory-federation/Cargo.toml",
    "codex-rs/hepta-memory-federation/README.md",
    "codex-rs/hepta-memory-federation/src/lib.rs",
    "codex-rs/hepta-memory-federation/src/legacy.rs",
    "codex-rs/hepta-memory-federation/src/v2.rs",
    "codex-rs/hepta-memory-federation/src/v2_tests.rs",
    "codex-rs/hepta-memory-federation/src/wire.rs",
    "codex-rs/hepta-memory/Cargo.toml",
    "codex-rs/hepta-memory/src/cognitive_federation.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_federation/aggregator.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_federation/attempt.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_federation/discovery.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_federation/evidence.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_federation/final_revalidator.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_federation/mod.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_federation/planner.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_federation/telemetry.rs",
    "codex-rs/hepta-memory/src/cognitive_runtime_tests.rs",
    "codex-rs/hepta-memory/src/lib.rs",
    "docs/modules/memory.federation/README.md",
    "docs/modules/memory.federation/TECHNICAL.md",
    "docs/modules/memory.federation/THREAT_MODEL.md",
    "docs/modules/memory.federation/V2_HARDENING.md",
    "docs/modules/memory.federation/WIRE_PROTOCOL_V1.md",
    "docs/modules/memory.federation/memory-federation-wire-v1.schema.json",
    "docs/modules/memory.federation/sequence.mmd",
    "docs/modules/memory.federation/OPERATIONS.md",
    "scripts/hepta-memory-federation-state.py",
]

COMMANDS = [
    "python3 scripts/hepta-implementation-maps.py verify",
    "python3 scripts/hepta-memory-federation-state.py verify",
    "cargo fmt -p codex-hepta-memory-federation -p codex-hepta-memory -p codex-hepta-memory-extension -p codex-hepta-agentd -p codex-app-server -- --check",
    "cargo test -p codex-hepta-memory-federation --lib",
    "cargo test -p codex-hepta-memory-federation --lib --features legacy-v1",
    "cargo test -p codex-hepta-memory --lib cognitive_runtime_tests",
    "cargo test -p codex-hepta-memory --lib cognitive_federation_tests",
    "cargo test -p codex-hepta-memory-extension --lib cognitive::federation",
    "cargo check -p codex-hepta-agentd -p codex-app-server",
    "cargo clippy -p codex-hepta-memory-federation -p codex-hepta-memory -p codex-hepta-memory-extension -p codex-app-server --all-targets -- -D warnings",
    "cargo clippy -p codex-hepta-agentd --lib -- -D warnings",
    "git diff --check",
]


def git(*args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
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
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def identity(ref: str = "HEAD") -> dict[str, str]:
    commit = git("rev-parse", ref)
    return {"commit": commit, "tree": git("rev-parse", f"{commit}^{{tree}}")}


def object_for(path: str, ref: str = "HEAD") -> str:
    return git("rev-parse", f"{ref}:{path}")


def require_clean() -> None:
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise SystemExit("memory.federation state generation requires a clean checkout")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")


def source_objects(ref: str = "HEAD") -> list[dict[str, str]]:
    missing = [path for path in SOURCE_PATHS if not (ROOT / path).exists()]
    if missing:
        raise SystemExit("missing memory.federation source paths: " + ", ".join(missing))
    return [{"path": path, "object": object_for(path, ref)} for path in sorted(SOURCE_PATHS)]


def generated_block(state: dict[str, Any]) -> str:
    claims = state["claims"]
    receipt = state.get("latestQualificationReceipt")
    receipt_text = receipt["path"] if isinstance(receipt, dict) else "pending"
    source = state["sourceObservation"]
    tested = state.get("testedCandidate") or {"commit": "pending", "tree": "pending"}
    return "\n".join(
        [
            BEGIN,
            "## Machine-generated current state",
            "",
            "This block is generated from `docs/modules/memory.federation/CURRENT_STATE.json`.",
            "Hand-written prose cannot override these claim boundaries.",
            "",
            f"- Source observation: `{source['commit']}` / `{source['tree']}`",
            f"- Tested candidate: `{tested['commit']}` / `{tested['tree']}`",
            f"- Qualification receipt: `{receipt_text}`",
            f"- Source implementation complete: `{str(claims['sourceImplementationComplete']).lower()}`",
            f"- Product composition implemented: `{str(claims['productCompositionImplemented']).lower()}`",
            f"- Product execution proved: `{str(claims['productExecutionProved']).lower()}`",
            f"- Cross-host protocol source implemented: `{str(claims['crossHostProtocolSourceImplemented']).lower()}`",
            f"- Physical two-host qualification: `{str(claims['physicalTwoHostQualification']).lower()}`",
            f"- Independent acceptance: `{str(claims['independentAcceptance']).lower()}`",
            f"- Activation: `{str(claims['activation']).lower()}`",
            f"- Release: `{str(claims['release']).lower()}`",
            "",
            "### Remaining external gates",
            "",
            *[f"- {gate}" for gate in state["externalEvidenceGates"]],
            "",
            END,
        ]
    )


def replace_generated_block(path: Path, block: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if pattern.search(text):
        rendered = pattern.sub(block, text, count=1)
    else:
        rendered = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(rendered, encoding="utf-8")


def operations() -> list[dict[str, Any]]:
    return [
        {
            "operation": "execute_once",
            "designOperation": "execute_once",
            "nativeSymbol": "execute_once",
            "sourcePath": "codex-rs/hepta-memory-federation/src/v2.rs",
            "state": "source_hardened_product_composed",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [
                "codex-rs/hepta-memory/src/cognitive_runtime_federation/mod.rs",
                "codex-rs/hepta-memory/src/cognitive_runtime_federation/attempt.rs",
                "codex-rs/hepta-agentd/src/runtime.rs",
                "codex-rs/ext/hepta-memory/src/cognitive/federation.rs",
            ],
            "tests": [
                "codex-rs/hepta-memory-federation/src/v2_tests.rs",
                "codex-rs/hepta-memory/src/cognitive_runtime_tests.rs",
            ],
            "sourcePathExists": True,
        },
        {
            "operation": "execute_once_outcome",
            "designOperation": "execute_once_outcome",
            "nativeSymbol": "execute_once_outcome",
            "sourcePath": "codex-rs/hepta-memory-federation/src/v2.rs",
            "state": "source_hardened_product_composed",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": ["codex-rs/hepta-memory/src/cognitive_runtime_federation/attempt.rs"],
            "tests": ["codex-rs/hepta-memory-federation/src/v2_tests.rs"],
            "sourcePathExists": True,
        },
        {
            "operation": "observe_cancellation",
            "designOperation": "observe_cancellation",
            "nativeSymbol": "observe_cancellation",
            "sourcePath": "codex-rs/hepta-memory-federation/src/v2.rs",
            "state": "source_hardened_product_wired",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [
                "codex-rs/hepta-memory/src/cognitive_runtime_federation/telemetry.rs",
                "codex-rs/ext/hepta-memory/src/cognitive/federation.rs",
            ],
            "tests": ["codex-rs/hepta-memory-federation/src/v2_tests.rs"],
            "sourcePathExists": True,
        },
        {
            "operation": "negotiate_wire_protocol_v1",
            "designOperation": "negotiate_wire_protocol_v1",
            "nativeSymbol": "negotiate_wire_protocol_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
        {
            "operation": "verify_wire_request_v1",
            "designOperation": "verify_wire_request_v1",
            "nativeSymbol": "verify_wire_request_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
        {
            "operation": "verify_wire_response_v1",
            "designOperation": "verify_wire_response_v1",
            "nativeSymbol": "verify_wire_response_v1",
            "sourcePath": "codex-rs/hepta-memory-federation/src/wire.rs",
            "state": "source_implemented_pending_physical_two_host_qualification",
            "authority": "none",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": ["codex-rs/hepta-memory-federation/src/wire.rs"],
            "sourcePathExists": True,
        },
    ]


def build_state(source: dict[str, str], *, passed: bool = False, tested: dict[str, str] | None = None, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": "hepta.memory-federation-current-state.v1",
        "schemaVersion": 1,
        "module": MODULE,
        "generatedBy": "scripts/hepta-memory-federation-state.py",
        "sourceObservation": source,
        "testedCandidate": tested,
        "sourceObjects": source_objects(source["commit"]),
        "claims": {
            "sourceImplementationComplete": True,
            "productCompositionImplemented": True,
            "productExecutionProved": passed,
            "crossHostProtocolSourceImplemented": True,
            "physicalTwoHostQualification": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
        "latestQualificationReceipt": receipt,
        "repositoryControlledChecks": [{"command": command, "status": "passed" if passed else "pending"} for command in COMMANDS],
        "repositoryControlledGaps": ([] if passed else ["Run the exact candidate qualification command set and record an immutable receipt."]),
        "externalEvidenceGates": [
            "physical two-real-host authenticated transport and partition testing",
            "target-host capacity, latency, overload and backpressure qualification",
            "independent semantic and security acceptance",
            "operator canary, rollback rehearsal, promotion and release approval",
        ],
    }


def update_map(state: dict[str, Any]) -> None:
    row = load_json(MAP_PATH)
    source = state["sourceObservation"]
    row.update(
        {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
            "mappingSourceIdentityMode": "exact_blob",
            "sourceBase": source,
            "observedAtHead": source,
            "observedSourcePaths": sorted(SOURCE_PATHS),
            "operations": operations(),
            "sourceObjects": state["sourceObjects"],
            "sourceRootPresent": True,
            "productionImplementation": False,
            "productCallerState": "composed_repository_qualified" if state["claims"]["productExecutionProved"] else "composed_candidate_pending_execution",
            "productionWriterState": "not_applicable_read_only",
            "repositoryControlledGaps": state["repositoryControlledGaps"],
            "externalEvidenceGates": state["externalEvidenceGates"],
        }
    )
    row["claimBoundary"] = {
        "nativeSourceMappingComplete": True,
        "sourceRootPresent": True,
        "productionImplementation": False,
        "productExecutionProved": state["claims"]["productExecutionProved"],
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "implementedOperationMappingComplete": True,
        "crossHostProtocolSourceImplemented": True,
        "physicalTwoHostQualification": False,
    }
    row["currentState"] = "docs/modules/memory.federation/CURRENT_STATE.json"
    row["latestQualificationReceipt"] = state.get("latestQualificationReceipt")
    dump_json(MAP_PATH, row)


def render() -> None:
    require_clean()
    source = identity()
    state = build_state(source)
    dump_json(STATE_PATH, state)
    update_map(state)
    block = generated_block(state)
    replace_generated_block(VERIFY_PATH, block)
    replace_generated_block(DOSSIER_PATH, block)
    print(json.dumps({"status": "rendered", "sourceObservation": source, "state": str(STATE_PATH.relative_to(ROOT))}, sort_keys=True))


def verify() -> None:
    state = load_json(STATE_PATH)
    if state.get("schema") != "hepta.memory-federation-current-state.v1" or state.get("module") != MODULE:
        raise SystemExit("invalid memory.federation current-state schema")
    source = state.get("sourceObservation")
    if not isinstance(source, dict) or identity(source.get("commit", "")) != source:
        raise SystemExit("invalid memory.federation source observation")
    git("merge-base", "--is-ancestor", source["commit"], "HEAD")
    expected = source_objects("HEAD")
    if state.get("sourceObjects") != expected:
        raise SystemExit("memory.federation source object drift; regenerate current state")
    changed = git("diff", "--name-only", source["commit"], "HEAD", "--", *SOURCE_PATHS)
    if changed:
        raise SystemExit("memory.federation source changed after observation: " + changed)
    row = load_json(MAP_PATH)
    if row.get("sourceObjects") != expected or row.get("observedAtHead") != source:
        raise SystemExit("memory.federation implementation map differs from current state")
    block = generated_block(state)
    for path in (VERIFY_PATH, DOSSIER_PATH):
        text = path.read_text(encoding="utf-8")
        match = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), text, re.S)
        if not match or match.group(0) != block:
            raise SystemExit(f"generated current-state block drift: {path.relative_to(ROOT)}")
    receipt = state.get("latestQualificationReceipt")
    if receipt is not None:
        receipt_path = ROOT / receipt["path"]
        if not receipt_path.is_file():
            raise SystemExit("latest qualification receipt is missing")
        body = load_json(receipt_path)
        if body.get("testedCandidate") != state.get("testedCandidate") or body.get("status") != "passed":
            raise SystemExit("latest qualification receipt does not bind the tested candidate")
    print(json.dumps({"status": "PASS_MEMORY_FEDERATION_CURRENT_STATE", "sourceObservation": source, "head": identity(), "receipt": receipt}, sort_keys=True))


def record_pass(tested_sha: str, tested_tree: str, run_id: str, run_attempt: str) -> None:
    state = load_json(STATE_PATH)
    source = state["sourceObservation"]
    actual = identity(tested_sha)
    if actual["tree"] != tested_tree:
        raise SystemExit("tested candidate tree does not match the supplied tree")
    if identity()["commit"] != tested_sha:
        raise SystemExit("record-pass must run at the exact tested candidate")
    receipt_rel = f"qualification/memory-federation/receipts/{tested_sha}.json"
    receipt = {
        "schema": "hepta.memory-federation-qualification-receipt.v1",
        "schemaVersion": 1,
        "module": MODULE,
        "status": "passed",
        "testedCandidate": actual,
        "sourceObservation": source,
        "workflow": {
            "name": "memory federation full closure qualification",
            "runId": run_id,
            "runAttempt": run_attempt,
        },
        "commands": [{"command": command, "status": "passed"} for command in COMMANDS],
        "generatedAtUtc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "claimBoundary": {
            "repositoryControlledQualification": True,
            "physicalTwoHostQualification": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    dump_json(ROOT / receipt_rel, receipt)
    receipt_ref = {"path": receipt_rel, "testedCandidate": actual, "status": "passed"}
    passed_state = build_state(source, passed=True, tested=actual, receipt=receipt_ref)
    dump_json(STATE_PATH, passed_state)
    update_map(passed_state)
    block = generated_block(passed_state)
    replace_generated_block(VERIFY_PATH, block)
    replace_generated_block(DOSSIER_PATH, block)
    print(json.dumps({"status": "recorded", "receipt": receipt_rel, "testedCandidate": actual}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("render")
    sub.add_parser("verify")
    passed = sub.add_parser("record-pass")
    passed.add_argument("--tested-sha", required=True)
    passed.add_argument("--tested-tree", required=True)
    passed.add_argument("--run-id", required=True)
    passed.add_argument("--run-attempt", required=True)
    args = parser.parse_args()
    if args.command == "render":
        render()
    elif args.command == "verify":
        verify()
    else:
        record_pass(args.tested_sha, args.tested_tree, args.run_id, args.run_attempt)


if __name__ == "__main__":
    main()
