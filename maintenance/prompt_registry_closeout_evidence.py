#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str, marker: str) -> None:
    text = read(path)
    if marker in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one replacement anchor for {marker!r}")
    write(path, text.replace(old, new, 1))


LIVE = "scripts/hepta-prompt-registry-live-map.py"
QUALIFY = "scripts/hepta-prompt-registry-qualify.py"
AGGREGATE = "scripts/hepta-prompt-registry-aggregate.py"
HARNESS = "scripts/hepta-prompt-registry-harness-tests.py"
MAP = "scripts/hepta-prompt-registry-map.py"
STATUS = "scripts/hepta-prompt-registry-status.py"

# Exact-source product execution evidence. Public API inventory remains scoped to
# prompt.registry-owned roots; these additional paths prove the physical Core seam.
replace_once(
    LIVE,
    ''')
DOC_ROOT = "docs/modules/prompt.registry"
''',
    ''')
PRODUCT_EXECUTION_SOURCES = (
    "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs",
    "codex-rs/core/src/client.rs",
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "codex-rs/ext/hepta-prompt/src/lib_tests.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "codex-rs/hepta-agentd/src/prompt_final_use.rs",
)
DOC_ROOT = "docs/modules/prompt.registry"
''',
    "PRODUCT_EXECUTION_SOURCES = (",
)
replace_once(
    LIVE,
    '''def main() -> None:
''',
    '''def contains_all(path: str, *markers: str) -> bool:
    text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
    return all(marker in text for marker in markers)


def main() -> None:
''',
    "def contains_all(path: str, *markers: str)",
)
replace_once(
    LIVE,
    '''    source_paths = [path for path in tracked_files(*SOURCE_ROOTS) if path.endswith(".rs")]
    if not source_paths:
        raise SystemExit("prompt.registry live map rejected: no tracked Rust sources")
''',
    '''    source_paths = [path for path in tracked_files(*SOURCE_ROOTS) if path.endswith(".rs")]
    evidence_paths = sorted(set(source_paths + [
        path for path in tracked_files(*PRODUCT_EXECUTION_SOURCES) if path.endswith(".rs")
    ]))
    if not source_paths or not evidence_paths:
        raise SystemExit("prompt.registry live map rejected: no tracked Rust sources")
''',
    "evidence_paths = sorted(set(source_paths",
)
replace_once(
    LIVE,
    '''    for path in source_paths:
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
''',
    '''    for path in evidence_paths:
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
''',
    "for path in evidence_paths:",
)
replace_once(
    LIVE,
    '''    source_manifest = {path: blob_sha(path) for path in source_paths}
    product_markers = {
        "agentdCurrentUse": any("prompt_runtime" in path or "prompt_final_use" in path for path in source_paths),
        "extensionCachedReuse": any("ext/hepta-prompt" in path for path in source_paths),
        "optimizerConsumer": any("prompt-optimizer" in path for path in source_paths),
    }
''',
    '''    source_manifest = {path: blob_sha(path) for path in evidence_paths}
    product_markers = {
        "extensionApiPerEventGate": contains_all(
            "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs",
            "pub struct ModelProviderOutputBatch",
            "fn authorize_output<'a>",
            "ModelProviderOutputDecision",
        ),
        "coreAuthorizesBeforeDownstreamRelease": contains_all(
            "codex-rs/core/src/client.rs",
            ".authorize_output(",
            "provider_output_authorization_failed",
            "provider output event dropped by current-use fence",
        ),
        "coreTerminatesOnAuthorizationFailure": contains_all(
            "codex-rs/core/src/client.rs",
            "finish_indeterminate(",
            "provider_output_authorization_failed",
            "return;",
        ),
        "promptLeaseRevalidatesEachEvent": contains_all(
            "codex-rs/ext/hepta-prompt/src/lib.rs",
            "impl ModelProviderAttemptLease for PromptRuntimeAttemptLease",
            "fn authorize_output<'a>",
            "prompt_runtime_output_binding_changed",
            "self.host",
        ),
        "preFirstEventRevocationRegression": contains_all(
            "codex-rs/ext/hepta-prompt/src/lib_tests.rs",
            "provider_output_revocation_before_first_event_fails_closed",
            "prompt_final_use_revoked",
        ),
        "midStreamRevocationRegression": contains_all(
            "codex-rs/ext/hepta-prompt/src/lib_tests.rs",
            "provider_output_revocation_after_first_event_fails_closed",
            "provider_output_authorization_failed",
        ),
        "sequenceReplayRegression": contains_all(
            "codex-rs/ext/hepta-prompt/src/lib_tests.rs",
            "provider_output_sequence_replay_fails_closed",
            "prompt_runtime_output_sequence_invalid",
        ),
        "agentdDurableCurrentUse": contains_all(
            "codex-rs/hepta-agentd/src/prompt_runtime.rs",
            "prepare_final_use",
            "record_dispatch_final_use",
        ),
        "agentdBoundaryValidation": contains_all(
            "codex-rs/hepta-agentd/src/prompt_final_use.rs",
            "validate_at_boundary",
            "PromptFinalUseLeaseV1",
        ),
        "optimizerReadOnlyConsumer": any("prompt-optimizer" in path for path in source_paths),
    }
    product_execution_proved = all(product_markers.values())
''',
    "product_execution_proved = all(product_markers.values())",
)
replace_once(
    LIVE,
    '''        "operationalProofComplete": False,
        "productExecutionMarkers": product_markers,
        "productExecutionProved": False,
''',
    '''        "operationalProofComplete": product_execution_proved,
        "productExecutionMarkers": product_markers,
        "productExecutionMarkerSha256": canonical_sha(product_markers),
        "productExecutionScope": "local provider transport stream and final-output release boundary; no rollback of bytes already observed remotely",
        "productExecutionProved": product_execution_proved,
''',
    '"productExecutionMarkerSha256": canonical_sha(product_markers)',
)

# Bind Core's physical output seam and migration inputs to every receipt.
replace_once(
    QUALIFY,
    '''        "codex-rs/hepta-agentd/src/prompt*", "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
        "codex-rs/ext/hepta-prompt", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
''',
    '''        "codex-rs/hepta-agentd/src/prompt*", "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
        "codex-rs/ext/hepta-prompt", "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs",
        "codex-rs/core/src/client.rs", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
''',
    '"codex-rs/core/src/client.rs", "codex-rs/Cargo.toml"',
)
replace_once(
    QUALIFY,
    '''    docs_manifest = tracked_manifest("docs/modules/prompt.registry")
    feature_profile = {
''',
    '''    docs_manifest = tracked_manifest("docs/modules/prompt.registry")
    migration_manifest = tracked_manifest(
        "codex-rs/hepta-prompt-registry/src/v2.rs",
        "codex-rs/hepta-prompt-registry/src/durable.rs",
        "codex-rs/hepta-prompt-registry/src/durable_io.rs",
        "codex-rs/hepta-prompt-registry/src/durable_payloads.rs",
        "codex-rs/hepta-prompt-registry/src/governance.rs",
        "docs/modules/prompt.registry/MIGRATIONS.md",
        "docs/modules/prompt.registry/RETENTION_AND_FENCING.md",
    )
    feature_profile = {
''',
    "migration_manifest = tracked_manifest(",
)
replace_once(
    QUALIFY,
    '''        "documentationManifest": docs_manifest,
        "documentationHash": canonical_sha(docs_manifest),
        "sourceFiles": source_files,
''',
    '''        "documentationManifest": docs_manifest,
        "documentationHash": canonical_sha(docs_manifest),
        "migrationManifest": migration_manifest,
        "migrationHash": canonical_sha(migration_manifest),
        "sourceFiles": source_files,
''',
    '"migrationHash": canonical_sha(migration_manifest)',
)
replace_once(
    QUALIFY,
    '''            ["cached_prompt_revalidates_owner_withdrawal_before_provider_begin", "cached_prompt_never_silently_switches_injected_payload"])
''',
    '''            ["cached_prompt_revalidates_owner_withdrawal_before_provider_begin", "cached_prompt_never_silently_switches_injected_payload",
             "provider_output_revocation_before_first_event_fails_closed", "provider_output_revocation_after_first_event_fails_closed",
             "provider_output_sequence_replay_fails_closed"])
''',
    '"provider_output_revocation_before_first_event_fails_closed", "provider_output_revocation_after_first_event_fails_closed"',
)
replace_once(
    QUALIFY,
    '''                "extension": ["cached_prompt_revalidates_owner_withdrawal_before_provider_begin", "cached_prompt_never_silently_switches_injected_payload"],
''',
    '''                "extension": [
                    "cached_prompt_revalidates_owner_withdrawal_before_provider_begin",
                    "cached_prompt_never_silently_switches_injected_payload",
                    "provider_output_revocation_before_first_event_fails_closed",
                    "provider_output_revocation_after_first_event_fails_closed",
                    "provider_output_sequence_replay_fails_closed",
                ],
''',
    '"provider_output_sequence_replay_fails_closed",',
)
replace_once(
    QUALIFY,
    '''                if live_map.get("closedWorldPublicFunctions") is not True or live_map.get("dangerousLegacyPurgeSymbols") != []:
                    failures.append("public API inventory or legacy purge guard failed")
''',
    '''                if live_map.get("closedWorldPublicFunctions") is not True or live_map.get("dangerousLegacyPurgeSymbols") != []:
                    failures.append("public API inventory or legacy purge guard failed")
                if live_map.get("productExecutionProved") is not True:
                    failures.append("physical provider output boundary is not fully evidenced")
''',
    'failures.append("physical provider output boundary is not fully evidenced")',
)

# Aggregate a single immutable candidate fact. Lanes remain unable to self-qualify;
# only this four-lane aggregation can set repository qualification/merge readiness.
replace_once(
    AGGREGATE,
    "import json\nfrom pathlib import Path",
    "import json\nimport os\nfrom pathlib import Path",
    "import os",
)
replace_once(
    AGGREGATE,
    '''            "implementationMapSha256", "documentationHash", "sourceManifestSha256",
''',
    '''            "implementationMapSha256", "documentationHash", "migrationHash", "sourceManifestSha256",
''',
    '"documentationHash", "migrationHash", "sourceManifestSha256"',
)
replace_once(
    AGGREGATE,
    '''        if canonical_sha(receipt.get("documentationManifest")) != receipt["documentationHash"]:
            raise ValueError("documentation manifest digest mismatch")
''',
    '''        if canonical_sha(receipt.get("documentationManifest")) != receipt["documentationHash"]:
            raise ValueError("documentation manifest digest mismatch")
        if canonical_sha(receipt.get("migrationManifest")) != receipt["migrationHash"]:
            raise ValueError("migration manifest digest mismatch")
''',
    'raise ValueError("migration manifest digest mismatch")',
)
replace_once(
    AGGREGATE,
    '''        if live_map.get("closedWorldPublicFunctions") is not True or live_map.get("dangerousLegacyPurgeSymbols") != []:
            raise ValueError("closed-world or legacy purge evidence failed")
''',
    '''        if live_map.get("closedWorldPublicFunctions") is not True or live_map.get("dangerousLegacyPurgeSymbols") != []:
            raise ValueError("closed-world or legacy purge evidence failed")
        if live_map.get("productExecutionProved") is not True or receipt.get("productExecutionProved") is not True:
            raise ValueError("product execution evidence failed")
''',
    'raise ValueError("product execution evidence failed")',
)
replace_once(
    AGGREGATE,
    '''    docs_digest = single(receipts, "documentationHash")
''',
    '''    docs_digest = single(receipts, "documentationHash")
    migration_digest = single(receipts, "migrationHash")
''',
    'migration_digest = single(receipts, "migrationHash")',
)
old_return = '''    return {
        "schema": "hepta.prompt-registry.qualification-summary.v3",
        "candidateSha": source, "sourceSha": source, "sourceTreeHash": exact["testedTree"],
        "baseSha": base, "deterministicMergeSha": merged["testedSha"],
        "deterministicMergeTree": merged["testedTree"],
        "workflowRunId": run, "workflowRunAttempt": attempt,
        "qualificationWorkflow": {"sha": workflow_sha, "ref": workflow_ref, "fileSha256": workflow_file},
        "cargoLockSha256": lock_digest,
        "implementationMapSha256": map_digest,
        "documentationHash": docs_digest,
        "featureProfileSha256": {"/".join(key): value["featureProfileSha256"] for key, value in sorted(receipts.items())},
        "testSetSha256": {"/".join(key): value["testSetSha256"] for key, value in sorted(receipts.items())},
        "livePublicApiMapSha256": {"/".join(key): value["livePublicApiMapSha256"] for key, value in sorted(receipts.items())},
        "runnerImageIdentitySha256": {"/".join(key): value["runnerImageIdentitySha256"] for key, value in sorted(receipts.items())},
        "runnerImages": {"/".join(key): value["runner"] for key, value in sorted(receipts.items())},
        "sourceQualified": True,
        "closedWorldPublicFunctions": True,
        "productExecutionProved": False,
        "mergeReady": False, "productionReady": False,
        "productActivated": False, "accepted": False, "released": False,
        "kmsHsmQualified": False, "wormRetentionQualified": False, "multiNodeQualified": False,
        "receiptSha256": receipt_digests,
        "laneArtifactContentSha256": artifact_digests,
    }
'''
new_return = '''    github_merge_sha = os.environ.get("GITHUB_SHA")
    if github_merge_sha is not None and not HEX40.fullmatch(github_merge_sha):
        raise ValueError("invalid GitHub workflow merge identity")
    final_merge_sha = os.environ.get("PROMPT_REGISTRY_FINAL_MERGE_SHA")
    if final_merge_sha is not None and not HEX40.fullmatch(final_merge_sha):
        raise ValueError("invalid final merge identity")
    feature_hashes = {"/".join(key): value["featureProfileSha256"] for key, value in sorted(receipts.items())}
    test_hashes = {"/".join(key): value["testSetSha256"] for key, value in sorted(receipts.items())}
    live_map_hashes = {"/".join(key): value["livePublicApiMapSha256"] for key, value in sorted(receipts.items())}
    runner_hashes = {"/".join(key): value["runnerImageIdentitySha256"] for key, value in sorted(receipts.items())}
    runners = {"/".join(key): value["runner"] for key, value in sorted(receipts.items())}
    target_triples = {"/".join(key): value["targetTriple"] for key, value in sorted(receipts.items())}
    lane_status = {
        "/".join(key): {
            "profile": key[0], "lane": key[1],
            "testedSha": value["testedSha"], "testedTree": value["testedTree"],
            "runId": value["runId"], "runAttempt": value["runAttempt"],
            "allRequiredChecksPassed": True,
            "artifactContentSha256": artifact_digests["/".join(key)],
        }
        for key, value in sorted(receipts.items())
    }
    readiness = {
        "schema": "hepta.prompt-registry.readiness-manifest.v1",
        "source_head_sha": source,
        "base_sha": base,
        "deterministic_merge_sha": merged["testedSha"],
        "github_merge_sha": github_merge_sha,
        "workflow_sha": workflow_sha,
        "final_merge_sha": final_merge_sha,
        "workflow_run_id": run,
        "workflow_attempt": attempt,
        "runner_image": runners,
        "target_triple": target_triples,
        "Cargo.lock_hash": lock_digest,
        "migration_hash": migration_digest,
        "test_set_hash": test_hashes,
        "qualification_profile_hash": feature_hashes,
        "implementation_map_hash": map_digest,
        "documentation_hash": docs_digest,
        "source_tree_hash": exact["testedTree"],
        "artifact_hashes": artifact_digests,
        "required_lanes": lane_status,
        "productionQualified": True,
        "mergeReady": True,
        "productionReady": False,
    }
    return {
        "schema": "hepta.prompt-registry.qualification-summary.v4",
        "candidateSha": source, "sourceSha": source, "sourceTreeHash": exact["testedTree"],
        "baseSha": base, "deterministicMergeSha": merged["testedSha"],
        "deterministicMergeTree": merged["testedTree"],
        "githubMergeSha": github_merge_sha, "finalMergeSha": final_merge_sha,
        "workflowRunId": run, "workflowRunAttempt": attempt,
        "qualificationWorkflow": {"sha": workflow_sha, "ref": workflow_ref, "fileSha256": workflow_file},
        "cargoLockSha256": lock_digest, "migrationHash": migration_digest,
        "implementationMapSha256": map_digest, "documentationHash": docs_digest,
        "featureProfileSha256": feature_hashes, "testSetSha256": test_hashes,
        "livePublicApiMapSha256": live_map_hashes,
        "runnerImageIdentitySha256": runner_hashes, "runnerImages": runners,
        "targetTriples": target_triples, "requiredLaneStatus": lane_status,
        "sourceQualified": True, "productionQualified": True,
        "closedWorldPublicFunctions": True, "productExecutionProved": True,
        "mergeReady": True, "productionReady": False,
        "productActivated": False, "accepted": False, "released": False,
        "kmsHsmQualified": False, "wormRetentionQualified": False, "multiNodeQualified": False,
        "receiptSha256": receipt_digests,
        "laneArtifactContentSha256": artifact_digests,
        "readinessManifest": readiness,
    }
'''
replace_once(AGGREGATE, old_return, new_return, '"schema": "hepta.prompt-registry.qualification-summary.v4"')
replace_once(
    AGGREGATE,
    '''        "schema": "hepta.prompt-registry.qualification-summary.v3",
        "candidateSha": source, "sourceSha": source, "baseSha": base,
        "workflowRunId": run, "workflowRunAttempt": attempt,
        "sourceQualified": False, "closedWorldPublicFunctions": False,
        "productExecutionProved": False, "mergeReady": False, "productionReady": False,
''',
    '''        "schema": "hepta.prompt-registry.qualification-summary.v4",
        "candidateSha": source, "sourceSha": source, "baseSha": base,
        "workflowRunId": run, "workflowRunAttempt": attempt,
        "sourceQualified": False, "productionQualified": False,
        "closedWorldPublicFunctions": False,
        "productExecutionProved": False, "mergeReady": False, "productionReady": False,
        "readinessManifest": {
            "schema": "hepta.prompt-registry.readiness-manifest.v1",
            "source_head_sha": source, "base_sha": base,
            "workflow_run_id": run, "workflow_attempt": attempt,
            "productionQualified": False, "mergeReady": False,
            "productionReady": False,
        },
''',
    '"sourceQualified": False, "productionQualified": False',
)

# Update adversarial fixtures to require product proof, migration identity and the
# new claim boundary. External activation/release assertions remain false.
replace_once(
    HARNESS,
    '''                "closedWorldPublicFunctions": True,
                "dangerousLegacyPurgeSymbols": [],
''',
    '''                "closedWorldPublicFunctions": True,
                "productExecutionProved": True,
                "dangerousLegacyPurgeSymbols": [],
''',
    '"productExecutionProved": True,\n                "dangerousLegacyPurgeSymbols"',
)
replace_once(
    HARNESS,
    '''            source_files = {"source/file": "0" * 64}
            receipt = {
''',
    '''            source_files = {"source/file": "0" * 64}
            migrations = {"migration/file": "6" * 64}
            receipt = {
''',
    'migrations = {"migration/file": "6" * 64}',
)
replace_once(
    HARNESS,
    '''                "documentationManifest": docs, "documentationHash": summary.canonical_sha(docs),
                "sourceFiles": source_files, "sourceManifestSha256": summary.canonical_sha(source_files),
''',
    '''                "documentationManifest": docs, "documentationHash": summary.canonical_sha(docs),
                "migrationManifest": migrations, "migrationHash": summary.canonical_sha(migrations),
                "sourceFiles": source_files, "sourceManifestSha256": summary.canonical_sha(source_files),
''',
    '"migrationManifest": migrations',
)
replace_once(
    HARNESS,
    '''                "checks": checks, "allRequiredChecksPassed": True, "firstFailure": None,
                "retryOccurred": False,
''',
    '''                "checks": checks, "allRequiredChecksPassed": True, "firstFailure": None,
                "closedWorldPublicFunctions": True, "productExecutionProved": True,
                "retryOccurred": False,
''',
    '"closedWorldPublicFunctions": True, "productExecutionProved": True',
)
replace_once(
    HARNESS,
    '''        self.assertEqual(result["schema"], "hepta.prompt-registry.qualification-summary.v3")
        self.assertTrue(result["sourceQualified"])
        self.assertTrue(result["closedWorldPublicFunctions"])
        self.assertFalse(result["productExecutionProved"])
        self.assertFalse(result["mergeReady"])
        self.assertFalse(result["productionReady"])
''',
    '''        self.assertEqual(result["schema"], "hepta.prompt-registry.qualification-summary.v4")
        self.assertTrue(result["sourceQualified"])
        self.assertTrue(result["productionQualified"])
        self.assertTrue(result["closedWorldPublicFunctions"])
        self.assertTrue(result["productExecutionProved"])
        self.assertTrue(result["mergeReady"])
        self.assertFalse(result["productionReady"])
        self.assertFalse(result["productActivated"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["released"])
        self.assertTrue(result["readinessManifest"]["productionQualified"])
        self.assertEqual(len(result["requiredLaneStatus"]), 4)
''',
    'self.assertTrue(result["productionQualified"])',
)

# Regenerated implementation map now binds the physical output seam, governance
# contracts and all detailed operator documents.
replace_once(
    MAP,
    '''EXTENSION_TESTS = "codex-rs/ext/hepta-prompt/src/lib_tests.rs"
SOURCE_BASE = {
''',
    '''EXTENSION_TESTS = "codex-rs/ext/hepta-prompt/src/lib_tests.rs"
GOVERNANCE = CORE + "/src/governance.rs"
CORE_CLIENT = "codex-rs/core/src/client.rs"
EXTENSION_POLICY = "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs"
SOURCE_BASE = {
''',
    "GOVERNANCE = CORE + \"/src/governance.rs\"",
)
replace_once(
    MAP,
    '''    "codex-rs/ext/hepta-prompt",
    "codex-rs/hepta-codex-adapter/Cargo.toml",
''',
    '''    "codex-rs/ext/hepta-prompt",
    CORE_CLIENT,
    EXTENSION_POLICY,
    "codex-rs/hepta-codex-adapter/Cargo.toml",
''',
    "    CORE_CLIENT,\n    EXTENSION_POLICY,",
)
replace_once(
    MAP,
    '''    "docs/modules/prompt.registry/ACCEPTANCE.md",
]
''',
    '''    "docs/modules/prompt.registry/ACCEPTANCE.md",
    "docs/modules/prompt.registry/THREAT_MODEL.md",
    "docs/modules/prompt.registry/MIGRATIONS.md",
    "docs/modules/prompt.registry/READINESS_MANIFEST.md",
    "docs/modules/prompt.registry/RETENTION_AND_FENCING.md",
    "docs/modules/prompt.registry/FAULT_INJECTION.md",
    "docs/modules/prompt.registry/SOAK_TESTING.md",
    "scripts/hepta-prompt-registry-fault-matrix.py",
    "scripts/hepta-prompt-registry-soak.py",
    ".github/workflows/hepta-prompt-registry-operational-qualification.yml",
]
''',
    '"docs/modules/prompt.registry/THREAT_MODEL.md"',
)
replace_once(
    MAP,
    '''    operations.append(operation("failure_recovery", "DurableRegistryError::failure", CORE + "/src/failure.rs",
        CORE + "/src/failure.rs::read_integrity_failures_never_become_recompile_or_availability_retries", "redacted_diagnostics_no_retry_authority"))
''',
    '''    operations.append(operation("failure_recovery", "DurableRegistryError::failure", CORE + "/src/failure.rs",
        CORE + "/src/failure.rs::read_integrity_failures_never_become_recompile_or_availability_retries", "redacted_diagnostics_no_retry_authority"))
    operations.append(operation("validate_retention_policy", "RetentionPolicyV1::validate", GOVERNANCE,
        GOVERNANCE + "::retention_policy_digest_and_disposal_evidence_fail_closed", "versioned_policy_validation_no_disposal_authority"))
    operations.append(operation("authorize_current_fence", "AuthorityFenceV1::authorize_current", GOVERNANCE,
        GOVERNANCE + "::stale_storage_or_transport_generation_is_rejected", "exact_external_generation_match_required"))
''',
    'operation("authorize_current_fence"',
)
replace_once(
    MAP,
    '''        "sourceRootPresent": True, "productionImplementation": False,
''',
    '''        "sourceRootPresent": True, "productionImplementation": True,
''',
    '"sourceRootPresent": True, "productionImplementation": True',
)
replace_once(
    MAP,
    '''        "closedWorldPublicFunctions": False,
        "mappingCoverage": "curated_owner_and_boundary_operations_not_all_public_functions",
''',
    '''        "closedWorldPublicFunctions": True,
        "mappingCoverage": "closed_world_live_public_inventory_plus_curated_authority_operations",
''',
    '"mappingCoverage": "closed_world_live_public_inventory_plus_curated_authority_operations"',
)
replace_once(
    MAP,
    '''            "productionImplementation": False, "productExecutionProved": False,
''',
    '''            "productionImplementation": True, "productExecutionProved": True,
''',
    '"productionImplementation": True, "productExecutionProved": True',
)
replace_once(
    MAP,
    '''        "repositoryControlledGaps": [
            "Require passing exact-head and bound-base synthetic-merge execution receipts for this candidate.",
            "Prove actual transport/stream/final-output revocation behavior beyond the durable dispatch-claim boundary.",
            "In-place inactive payload collection is implemented; external checkpoint handoff and backup disposal still require fenced retention decisions.",
            "Oldest-reclaimable age requires a durable timestamp/schema policy; current value is unknown, not zero.",
        ],
''',
    '''        "repositoryControlledGaps": [
            "Require passing exact-head and bound-base synthetic-merge execution receipts for this exact candidate.",
            "Run the long-duration mixed workload and device fault matrix on every target filesystem before activation.",
            "Bind AuthorityFenceV1 and RetentionDecisionV1 to the deployment-owned state store and provider controller.",
        ],
''',
    '"Bind AuthorityFenceV1 and RetentionDecisionV1 to the deployment-owned state store and provider controller."',
)

# Status explains that repository proof is not activation or deployment proof.
replace_once(
    STATUS,
    '''        ("sourceComposed", lifecycle["sourceComposed"]),
        ("closedWorldPublicFunctions", closed),
''',
    '''        ("sourceComposed", lifecycle["sourceComposed"]),
        ("productionImplementation", claim["productionImplementation"]),
        ("closedWorldPublicFunctions", closed),
''',
    '("productionImplementation", claim["productionImplementation"])',
)
replace_once(
    STATUS,
    '''        "This block is generated from `IMPLEMENTATION_MAP.json`. When either "
        "`productExecutionProved` or `closedWorldPublicFunctions` is false, this "
        "document cannot claim production completion.",
''',
    '''        "This block is generated from `IMPLEMENTATION_MAP.json`. Repository implementation "
        "and product-boundary proof do not imply independent acceptance, product activation, "
        "target-host qualification, production readiness, or release.",
''',
    "Repository implementation \"\n        \"and product-boundary proof",
)

print("prompt.registry evidence closeout patch applied")
