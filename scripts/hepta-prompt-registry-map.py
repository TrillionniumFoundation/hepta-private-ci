#!/usr/bin/env python3
"""Generate (--write) or read-only verify (--check, default) the prompt map.

Source is committed before generation; the following map-only commit can then
verify the same source observation without a self-referential SHA. The map is
navigation/source identity evidence, never a substitute for compiler/tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/prompt.registry/IMPLEMENTATION_MAP.json"
STATUS_TOOL = ROOT / "scripts/hepta-prompt-registry-status.py"
CORE = "codex-rs/hepta-prompt-registry"
DURABLE = CORE + "/src/durable.rs"
MAINTENANCE = CORE + "/src/durable_maintenance.rs"
MAINTENANCE_TESTS = CORE + "/src/durable_maintenance_tests.rs"
RUNTIME = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
RUNTIME_TESTS = "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"
FINAL_USE = "codex-rs/hepta-agentd/src/prompt_final_use.rs"
FINAL_USE_TESTS = "codex-rs/hepta-agentd/src/prompt_final_use_tests.rs"
EXTENSION = "codex-rs/ext/hepta-prompt/src/lib.rs"
EXTENSION_TESTS = "codex-rs/ext/hepta-prompt/src/lib_tests.rs"
SOURCE_BASE = {
    "commit": "a126987b84737dbc2ee2592442a314117bddb4a2",
    "tree": "a22fd0074c45ae6f3cef2092cd6e273bf9c26c30",
}
INPUTS = [
    CORE,
    "codex-rs/hepta-prompt-optimizer",
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs",
    FINAL_USE,
    FINAL_USE_TESTS,
    "codex-rs/hepta-agentd/src/prompt_final_use_store.rs",
    "codex-rs/hepta-agentd/Cargo.toml",
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "codex-rs/hepta-intelligence/Cargo.toml",
    "codex-rs/ext/hepta-prompt",
    "codex-rs/hepta-codex-adapter/Cargo.toml",
    "codex-rs/hepta-codex-adapter/src/lib.rs",
    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
    "scripts/hepta-implementation-maps.py",
    "scripts/hepta_module_source_roots.py",
    "scripts/hepta-prompt-registry-map.py",
    "scripts/hepta-prompt-registry-qualify.py",
    "scripts/hepta-prompt-registry-harness-tests.py",
    "scripts/hepta-prompt-registry-aggregate.py",
    "scripts/hepta-prompt-registry-status.py",
    "scripts/hepta-prompt-registry-accept.py",
    ".github/workflows/hepta-prompt-registry-qualification.yml",
    ".github/workflows/hepta-prompt-registry-acceptance.yml",
    "docs/modules/prompt.registry/TECHNICAL.md",
    "docs/modules/prompt.registry/API_CONTRACT.md",
    "docs/modules/prompt.registry/OPERATIONS.md",
    "docs/modules/prompt.registry/PERFORMANCE.md",
    "docs/modules/prompt.registry/ARCHITECTURE.md",
    "docs/modules/prompt.registry/ACCEPTANCE.md",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def checked_symbol(path: str, symbol: str) -> None:
    leaf = symbol.rsplit("::", 1)[-1]
    text = (ROOT / path).read_text(encoding="utf-8")
    if not re.search(r"\b(?:fn|struct|enum)\s+" + re.escape(leaf) + r"\b", text):
        raise ValueError(f"missing native/test symbol: {path}::{symbol}")


def source_blob(path: str) -> str:
    data = (ROOT / path).read_bytes()
    actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    committed = git("rev-parse", f"HEAD:{path}")
    if actual != committed:
        raise ValueError(f"uncommitted mapped source: {path}")
    return actual


def operation(name: str, symbol: str, path: str, test: str, authority: str) -> dict:
    checked_symbol(path, symbol)
    test_path, _, test_symbol = test.partition("::")
    if test_symbol:
        checked_symbol(test_path, test_symbol)
    source_blob(test_path)
    return {
        "operation": name, "designOperation": name,
        "nativeSymbol": symbol, "sourcePath": path,
        "sourceBlob": source_blob(path), "sourcePathExists": True,
        "state": "source_implemented_qualification_pending",
        "authority": authority, "tests": [test],
        "mappingClass": "owner_native" if path.startswith(CORE + "/") else "composed_boundary",
        "delegatedCallees": [],
    }


def build(observation: dict[str, str]) -> dict:
    if git("rev-parse", observation["commit"] + "^{tree}") != observation["tree"]:
        raise ValueError("invalid source observation tree")
    subprocess.run(["git", "merge-base", "--is-ancestor", observation["commit"], "HEAD"], cwd=ROOT, check=True)
    committed_paths = git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    paths = sorted(path for path in committed_paths
                   if any(path == item or path.startswith(item + "/") for item in INPUTS))
    if not paths:
        raise ValueError("empty source inventory")
    for required in INPUTS:
        if not (ROOT / required).exists() or not any(p == required or p.startswith(required + "/") for p in paths):
            raise ValueError(f"missing tracked input: {required}")
    if git("diff", "--name-only", observation["commit"], "HEAD", "--", *INPUTS):
        raise ValueError("mapped source changed after observation; regenerate in a source-authoring commit")
    entries = [{"path": path, "blobSha": source_blob(path)} for path in paths]
    operations = []
    for name in ["open_state_dir", "register_factor_final_use", "admit_factor_final_use",
                 "register_factor_relation_final_use", "register_realization_payload_final_use_v2",
                 "retire_factor_final_use", "revoke_factor_final_use", "snapshot_v2",
                 "read_compatible_v2", "dereference_realization_v2"]:
        operations.append(operation(name, "DurablePromptRegistry::" + name, DURABLE,
            DURABLE if name == "open_state_dir" else (CORE + "/src/v2_tests.rs" if name.endswith("v2") else CORE + "/src/lib_tests.rs"),
            "read_evidence_only" if name in {"snapshot_v2", "read_compatible_v2", "dereference_realization_v2"} else "exclusive_owner_and_operation_bound_authority"))
    for name, test in [
        ("operational_metrics", "operational_poisoned_owner_exposes_diagnostics_but_not_authority"),
        ("export_consistent_checkpoint", "operational_consistent_export_reopens_exactly"),
        ("checkpoint_compacted", "operational_compaction_retry_is_idempotent_and_conflicting_destination_is_untouched"),
        ("verify_restore_checkpoint", "operational_stale_restore_is_rejected_after_revocation"),
        ("probe_fsync", "operational_fsync_probe_is_bounded_and_cleans_up"),
    ]:
        operations.append(operation(name, "DurablePromptRegistry::" + name, MAINTENANCE,
            MAINTENANCE_TESTS + "::" + test, "local_diagnostic_or_checkpoint_no_activation"))
    operations.append(operation("collect_payload_garbage", "DurablePromptRegistry::collect_payload_garbage", CORE + "/src/durable_gc.rs",
        CORE + "/src/durable_gc_tests.rs::gc_reclaims_inactive_raw_bytes_but_preserves_audit_and_revocation_after_restart", "exclusive_owner_inactive_payloads_only_audit_retained"))
    operations.append(operation("failure_recovery", "DurableRegistryError::failure", CORE + "/src/failure.rs",
        CORE + "/src/failure.rs::read_integrity_failures_never_become_recompile_or_availability_retries", "redacted_diagnostics_no_retry_authority"))
    operations.extend([
        operation("current_use_gate", "PromptFinalUseLeaseV1::validate_at_boundary", FINAL_USE,
            FINAL_USE_TESTS + "::final_use_revocation_precedes_snapshot_error_and_survives_restart", "deny_without_current_owner_validation"),
        operation("prepare_current_attachment", "AgentdPromptPipelineOwner::prepare_final_use", RUNTIME,
            RUNTIME_TESTS + "::named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host", "same_owner_current_use_gate"),
        operation("record_current_dispatch", "AgentdPromptPipelineOwner::record_dispatch_final_use", RUNTIME,
            RUNTIME_TESTS + "::named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host", "locked_durable_dispatch_claim_not_terminal_success"),
        operation("revalidate_cached_attachment", "resolve", EXTENSION,
            EXTENSION_TESTS + "::cached_prompt_revalidates_owner_withdrawal_before_provider_begin", "same_host_current_use_gate"),
    ])
    callers = []
    for path, symbol in [(RUNTIME, "AgentdPromptPipelineOwner"),
                         (FINAL_USE, "PromptFinalUseValidator"),
                         ("codex-rs/hepta-intelligence/src/prompt_delivery.rs", "compile_prompt_registry_v2"),
                         (EXTENSION, "PromptRuntimeExtension")]:
        checked_symbol(path, symbol)
        callers.append({"sourcePath": path, "nativeSymbol": symbol, "blobSha": source_blob(path), "state": "source_composed_activation_not_proved"})
    return {
        "schema": "hepta.module-implementation-map.v3", "schemaVersion": 3,
        "module": "prompt.registry", "owner": "intelligence-platform", "deputy": "cognitive-platform",
        "laneId": "LANE-C-MEMORY", "technicalGuide": "docs/modules/prompt.registry/TECHNICAL.md",
        "declaredRoots": [CORE], "resolvedRoots": [CORE], "sourceRoot": [CORE],
        "sourceRootPresent": True, "productionImplementation": False,
        "productCallerState": "source_composed", "productionWriterState": "not_activated",
        "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
        "mappingSourceIdentityMode": "exact_blob", "sourceBase": SOURCE_BASE,
        "observedAtHead": observation, "observedSourcePaths": sorted(INPUTS),
        "exactSourceEvidence": {"kind": "path_blob_manifest_v1", "entries": entries},
        "sourceObjects": [{"path": path, "object": git("rev-parse", f"HEAD:{path}")} for path in sorted(set(paths + [CORE]))],
        "closedWorldPublicFunctions": False,
        "mappingCoverage": "curated_owner_and_boundary_operations_not_all_public_functions",
        "activePersistentSchemas": [4, 5], "semanticSchema": 4, "payloadGenerationSchema": 5, "operations": operations, "productCallers": callers,
        "status": {"implemented": True, "composed": True, "qualified": False},
        "lifecycleStates": {"sourceImplemented": True, "sourceComposed": True, "productActivated": False, "accepted": False, "released": False},
        "claimBoundary": {"nativeSourceMappingComplete": False, "sourceRootPresent": True,
            "productionImplementation": False, "productExecutionProved": False,
            "independentAcceptance": False, "activation": False, "release": False,
            "implementedOperationMappingComplete": True},
        "repositoryControlledGaps": [
            "Require passing exact-head and bound-base synthetic-merge execution receipts for this candidate.",
            "Prove actual transport/stream/final-output revocation behavior beyond the durable dispatch-claim boundary.",
            "In-place inactive payload collection is implemented; external checkpoint handoff and backup disposal still require fenced retention decisions.",
            "Oldest-reclaimable age requires a durable timestamp/schema policy; current value is unknown, not zero.",
        ],
        "externalEvidenceGates": ["independent security/semantic review", "target-host and deployed provider qualification", "operator activation, acceptance and release"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="generate after committing source; never used in qualification")
    mode.add_argument("--check", action="store_true", help="read-only verification (default)")
    args = parser.parse_args()
    if args.write:
        observation = {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}
        row = build(observation)
        MAP.write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        subprocess.run([sys.executable, str(STATUS_TOOL), "--write"], cwd=ROOT, check=True)
        print("generated prompt.registry map and status; commit both before qualification")
    else:
        row = json.loads(MAP.read_text(encoding="utf-8"))
        observation = row.get("observedAtHead")
        if not isinstance(observation, dict):
            raise ValueError("missing current source observation")
        if row != build(observation):
            raise ValueError("stale/incomplete prompt.registry implementation map")
        subprocess.run([sys.executable, str(STATUS_TOOL), "--check"], cwd=ROOT, check=True)
        print(f"prompt.registry map verified read-only: {len(row['operations'])} operations, {len(row['exactSourceEvidence']['entries'])} source blobs")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"prompt.registry map rejected: {error}") from error
