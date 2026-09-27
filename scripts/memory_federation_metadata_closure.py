#!/usr/bin/env python3
"""Close memory.federation generated metadata inputs."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one replacement, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_generated_runtime_parent() -> None:
    path = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime.rs"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\nconst PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs\(2\);\n"
        r"const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;\n"
        r"const PRODUCT_FEDERATION_PURPOSE: &\[u8\] = b\"hepta\.cognitive\.federated-recall\.product\.v2\";\n"
        r"static PRODUCT_FEDERATION_ATTEMPT_SEQUENCE: AtomicU64 = AtomicU64::new\(1\);\n"
    )
    text, count = pattern.subn("\n", text, count=1)
    if count != 1:
        raise SystemExit(f"generated runtime legacy constants drift: {count}")
    path.write_text(text, encoding="utf-8")


def patch_generated_cancellation_and_binding() -> None:
    telemetry_path = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime_federation/telemetry.rs"
    telemetry = telemetry_path.read_text(encoding="utf-8")
    telemetry = replace_once(
        telemetry,
        '''        Ok(RegisteredFederationQueryV2 {
            control: self.clone(),
            key,
        })''',
        '''        Ok(RegisteredFederationQueryV2 {
            control: self.clone(),
            key,
            completed: false,
        })''',
        "cancellation registration constructor",
    )
    telemetry = replace_once(
        telemetry,
        '''pub(super) struct RegisteredFederationQueryV2 {
    control: FederationProductControl,
    key: String,
}

impl Drop for RegisteredFederationQueryV2 {
    fn drop(&mut self) {
        if let Ok(mut active) = self.control.inner.active.lock() {
            active.remove(&self.key);
        }
    }
}''',
        '''pub(super) struct RegisteredFederationQueryV2 {
    control: FederationProductControl,
    key: String,
    completed: bool,
}

impl RegisteredFederationQueryV2 {
    pub(super) fn complete(&mut self) {
        if let Ok(mut active) = self.control.inner.active.lock() {
            active.remove(&self.key);
        }
        self.completed = true;
    }
}

impl Drop for RegisteredFederationQueryV2 {
    fn drop(&mut self) {
        if self.completed {
            return;
        }
        let request = self
            .control
            .inner
            .active
            .lock()
            .ok()
            .and_then(|mut active| active.remove(&self.key));
        if let Some(request) = request {
            if let Ok(receipt) = observe_cancellation(request, false) {
                self.control.record_receipt(receipt);
            }
        }
    }
}''',
        "cancellation registration drop receipt",
    )
    telemetry_path.write_text(telemetry, encoding="utf-8")

    attempt_path = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime_federation/attempt.rs"
    attempt = attempt_path.read_text(encoding="utf-8")
    attempt = replace_once(
        attempt,
        "    let registration = match control.register_query(&query) {",
        "    let mut registration = match control.register_query(&query) {",
        "mutable cancellation registration",
    )
    attempt = replace_once(
        attempt,
        '''    )
    .await;
    drop(registration);
    let captured = captured.lock().ok().and_then(|mut batch| batch.take());''',
        '''    )
    .await;
    registration.complete();
    drop(registration);
    let captured = captured.lock().ok().and_then(|mut batch| batch.take());''',
        "normal cancellation registration completion",
    )
    attempt_path.write_text(attempt, encoding="utf-8")

    extension_path = ROOT / "codex-rs/ext/hepta-memory/src/cognitive/federation.rs"
    extension = extension_path.read_text(encoding="utf-8")
    unused_wrapper = re.compile(
        r"\nfn federation_source_binding\(\n.*?\n\}\n\n(?=fn federation_source_binding_with_diagnostics\()",
        re.S,
    )
    extension, count = unused_wrapper.subn("\n", extension, count=1)
    if count != 1:
        raise SystemExit(f"generated unused federation binding wrapper drift: {count}")
    extension_path.write_text(extension, encoding="utf-8")


def patch_generated_diagnostics() -> None:
    telemetry_path = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime_federation/telemetry.rs"
    telemetry = telemetry_path.read_text(encoding="utf-8")
    old_enum_derive = "#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]"
    new_enum_derive = (
        "#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]"
    )
    if telemetry.count(old_enum_derive) != 3:
        raise SystemExit("generated diagnostic enum derive drift")
    telemetry = telemetry.replace(old_enum_derive, new_enum_derive)
    telemetry = replace_once(
        telemetry,
        "#[derive(Clone, Debug, Eq, PartialEq, Serialize)]\npub struct FederatedPeerDiagnosticV2",
        "#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]\npub struct FederatedPeerDiagnosticV2",
        "diagnostic entry ordering",
    )
    telemetry = replace_once(
        telemetry,
        '''    pub fn binding_sha256(&self) -> Result<Sha256Digest, CognitiveStoreError> {
        let bytes = serde_json::to_vec(self).map_err(|error| {''',
        '''    pub(super) fn canonicalize(&mut self) {
        self.entries.sort();
    }

    pub fn binding_sha256(&self) -> Result<Sha256Digest, CognitiveStoreError> {
        let mut canonical = self.clone();
        canonical.canonicalize();
        let bytes = serde_json::to_vec(&canonical).map_err(|error| {''',
        "canonical diagnostic digest",
    )
    telemetry_path.write_text(telemetry, encoding="utf-8")

    module_path = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime_federation/mod.rs"
    module = module_path.read_text(encoding="utf-8")
    module = replace_once(
        module,
        '''    finalize_candidates(&mut candidates, &mut coverage, &mut diagnostics);
    Ok(FederatedProductReadV2 {''',
        '''    finalize_candidates(&mut candidates, &mut coverage, &mut diagnostics);
    diagnostics.canonicalize();
    Ok(FederatedProductReadV2 {''',
        "canonical diagnostic return",
    )
    module_path.write_text(module, encoding="utf-8")

    aggregator_path = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime_federation/aggregator.rs"
    aggregator = aggregator_path.read_text(encoding="utf-8")
    aggregator = replace_once(
        aggregator,
        '''            if result.validity != FederatedValidityV2::Valid {
                diagnostics.push(FederatedPeerDiagnosticV2 {
                    peer_digest: attempt.peer_digest,
                    phase: FederationProductPhaseV2::PostIoAuthority,
                    disposition: FederationProductDispositionV2::Partial,
                    failure: Some(FederationProductFailureV2::AuthorityRejected),
                    cancellation_receipt_digest: None,
                });
                return;
            }''',
        '''            if result.validity != FederatedValidityV2::Valid {
                let (phase, disposition, failure) = match result.validity {
                    FederatedValidityV2::Revoked | FederatedValidityV2::StaleGeneration => (
                        FederationProductPhaseV2::PostIoAuthority,
                        FederationProductDispositionV2::Failed,
                        FederationProductFailureV2::AuthorityRejected,
                    ),
                    FederatedValidityV2::Indeterminate
                        if result.coverage.failures.deadline_or_cancelled > 0 => (
                            FederationProductPhaseV2::Cancellation,
                            FederationProductDispositionV2::Cancelled,
                            FederationProductFailureV2::DeadlineOrCancelled,
                        ),
                    FederatedValidityV2::Indeterminate
                        if result.coverage.failures.transport_unavailable > 0 => (
                            FederationProductPhaseV2::Transport,
                            FederationProductDispositionV2::Failed,
                            FederationProductFailureV2::TransportUnavailable,
                        ),
                    FederatedValidityV2::Indeterminate => (
                        FederationProductPhaseV2::Integrity,
                        FederationProductDispositionV2::Failed,
                        FederationProductFailureV2::IntegrityRejected,
                    ),
                    FederatedValidityV2::Valid => (
                        FederationProductPhaseV2::Aggregation,
                        FederationProductDispositionV2::Failed,
                        FederationProductFailureV2::IntegrityRejected,
                    ),
                };
                diagnostics.push(FederatedPeerDiagnosticV2 {
                    peer_digest: attempt.peer_digest,
                    phase,
                    disposition,
                    failure: Some(failure),
                    cancellation_receipt_digest: None,
                });
                return;
            }''',
        "typed invalid-result diagnostics",
    )
    aggregator = replace_once(
        aggregator,
        "            if result.completeness != FederatedCompletenessV2::Complete {",
        "            if result.completeness == FederatedCompletenessV2::Partial {",
        "empty result diagnostic semantics",
    )
    aggregator_path.write_text(aggregator, encoding="utf-8")


def patch_generated_wire() -> None:
    wire_path = ROOT / "codex-rs/hepta-memory-federation/src/wire.rs"
    wire = wire_path.read_text(encoding="utf-8")
    wire = replace_once(
        wire,
        '''        if self.entries.len() == self.capacity {
            self.entries.pop_front();
        }
        self.entries.push_back(ReplayEntryV1 {''',
        '''        if self.entries.len() == self.capacity {
            return Err(FederationWireError::ReplayWindowFull);
        }
        self.entries.push_back(ReplayEntryV1 {''',
        "fail-closed replay capacity",
    )
    wire = replace_once(
        wire,
        '''    if request.owner_epoch != credential.owner_epoch {
        return Err(FederationWireError::OwnerEpochMismatch);
    }
    validate_window(request.issued_unix_ms, request.expires_unix_ms, now_unix_ms)?;''',
        '''    if request.owner_epoch != credential.owner_epoch {
        return Err(FederationWireError::OwnerEpochMismatch);
    }
    validate_credential_window(
        credential,
        request.issued_unix_ms,
        request.expires_unix_ms,
    )?;
    validate_window(request.issued_unix_ms, request.expires_unix_ms, now_unix_ms)?;''',
        "request credential horizon",
    )
    wire = replace_once(
        wire,
        '''    if response.query_binding_digest != expected_request.query_binding_digest
        || response.source_cut_digest != expected_request.source_cut_digest
    {
        return Err(FederationWireError::BindingMismatch);
    }
    validate_window(response.issued_unix_ms, response.expires_unix_ms, now_unix_ms)?;''',
        '''    if response.query_binding_digest != expected_request.query_binding_digest
        || response.source_cut_digest != expected_request.source_cut_digest
        || response.issued_unix_ms < expected_request.issued_unix_ms
        || response.expires_unix_ms > expected_request.expires_unix_ms
        || response.nonce_digest == expected_request.nonce_digest
    {
        return Err(FederationWireError::BindingMismatch);
    }
    validate_credential_window(
        credential,
        response.issued_unix_ms,
        response.expires_unix_ms,
    )?;
    validate_window(response.issued_unix_ms, response.expires_unix_ms, now_unix_ms)?;''',
        "response request and credential horizon",
    )
    wire = replace_once(
        wire,
        '''fn validate_window(
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    now_unix_ms: u64,
) -> Result<(), FederationWireError> {''',
        '''fn validate_credential_window(
    credential: &FederationPeerCredentialV1,
    issued_unix_ms: u64,
    expires_unix_ms: u64,
) -> Result<(), FederationWireError> {
    if issued_unix_ms < credential.effective_unix_ms
        || expires_unix_ms > credential.expires_unix_ms
    {
        return Err(FederationWireError::CredentialExpired);
    }
    Ok(())
}

fn validate_window(
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    now_unix_ms: u64,
) -> Result<(), FederationWireError> {''',
        "credential window validator",
    )
    wire = replace_once(
        wire,
        "    InvalidReplayCapacity,\n    ReplayDetected,",
        "    InvalidReplayCapacity,\n    ReplayWindowFull,\n    ReplayDetected,",
        "replay window full error",
    )
    wire_path.write_text(wire, encoding="utf-8")

    protocol_path = ROOT / "docs/modules/memory.federation/WIRE_PROTOCOL_V1.md"
    protocol = protocol_path.read_text(encoding="utf-8")
    protocol = replace_once(
        protocol,
        "Full queues evict the oldest unexpired observation only after a valid\nsignature has been checked.",
        "A full window containing only unexpired observations rejects new envelopes;\nit never evicts a live nonce and thereby makes an earlier replay admissible.",
        "wire replay documentation",
    )
    protocol_path.write_text(protocol, encoding="utf-8")


def patch_state_sources() -> None:
    path = ROOT / "scripts/hepta-memory-federation-state.py"
    text = path.read_text(encoding="utf-8")
    anchor = '    ".github/workflows/memory-federation-v2-final-verify.yml",\n'
    additions = (
        anchor
        + '    ".github/workflows/memory-federation-full-closure-bootstrap.yml",\n'
        + '    "scripts/memory_federation_core_closure.py",\n'
        + '    "scripts/memory_federation_runtime_closure.py",\n'
        + '    "scripts/memory_federation_metadata_closure.py",\n'
        + '    "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json",\n'
    )
    if additions not in text:
        if text.count(anchor) != 1:
            raise SystemExit("memory federation state source anchor drift")
        text = text.replace(anchor, additions, 1)

    ancestry = '    git("merge-base", "--is-ancestor", source["commit"], "HEAD")\n'
    object_identity = '    git("cat-file", "-e", f"{source[\'commit\']}^{{commit}}")\n'
    if object_identity not in text:
        if text.count(ancestry) != 1:
            raise SystemExit("memory federation ancestry verifier anchor drift")
        text = text.replace(ancestry, object_identity, 1)

    attestation_anchor = (
        '    row["currentState"] = "docs/modules/memory.federation/CURRENT_STATE.json"\n'
        '    row["latestQualificationReceipt"] = state.get("latestQualificationReceipt")\n'
    )
    attestation_block = '''    try:\n        base_commit = git("merge-base", source["commit"], "origin/main")\n    except subprocess.CalledProcessError:\n        base_commit = git("rev-parse", f"{source['commit']}^")\n    tested = state.get("testedCandidate")\n    row["headAttestation"] = {\n        "candidateBranch": os.environ.get("GITHUB_REF_NAME")\n        or git("rev-parse", "--abbrev-ref", "HEAD"),\n        "baseCommit": base_commit,\n        "candidateHead": source["commit"],\n        "candidateTree": source["tree"],\n        "testedCandidate": tested,\n        "headMeaning": "machine_generated_memory_federation_full_closure_source",\n        "status": (\n            "repository_qualified_external_gates_remaining"\n            if state["claims"]["productExecutionProved"]\n            else "pending_exact_candidate_execution"\n        ),\n        "scope": [\n            "machine_generated_current_state",\n            "bounded_concurrent_discovery",\n            "isolated_peer_attempt_outcomes",\n            "parallel_owner_final_revalidation",\n            "explicit_product_cancellation_receipts",\n            "bounded_peer_diagnostic_ledger",\n            "feature_gated_deprecated_v1",\n            "authenticated_wire_v1_source",\n            "owner_epoch_source_cut_and_replay_binding",\n            "operator_runbook_and_threat_model",\n        ],\n        "productCallsites": [\n            "codex-rs/hepta-agentd/src/runtime.rs",\n            "codex-rs/hepta-memory/src/cognitive_runtime.rs",\n            "codex-rs/hepta-memory/src/cognitive_runtime_federation/mod.rs",\n            "codex-rs/ext/hepta-memory/src/cognitive/federation.rs",\n            "codex-rs/app-server/src/lib.rs",\n        ],\n        "evidencePaths": [\n            ".github/workflows/memory-federation-v2-final-verify.yml",\n            ".github/workflows/memory-federation-full-closure-bootstrap.yml",\n            "docs/modules/memory.federation/CURRENT_STATE.json",\n            "docs/modules/memory.federation/IMPLEMENTATION_MAP.json",\n            "qualification/memory-federation/FINAL_V2_VERIFICATION.md",\n            "qualification/module-execution-dossiers/detail/memory.federation.md",\n        ],\n        "metadataOnlyPaths": [\n            "docs/modules/memory.federation/CURRENT_STATE.json",\n            "docs/modules/memory.federation/IMPLEMENTATION_MAP.json",\n            "qualification/memory-federation/FINAL_V2_VERIFICATION.md",\n            "qualification/module-execution-dossiers/detail/memory.federation.md",\n            "qualification/memory-federation/receipts",\n        ],\n        "note": (\n            "Source and product composition are bound to exact Git objects. "\n            "Physical two-host qualification, independent acceptance, activation, "\n            "promotion and release remain externally governed."\n        ),\n    }\n''' + attestation_anchor
    if attestation_block not in text:
        if text.count(attestation_anchor) != 1:
            raise SystemExit("memory federation head attestation anchor drift")
        text = text.replace(attestation_anchor, attestation_block, 1)
    path.write_text(text, encoding="utf-8")


def patch_profile() -> None:
    path = ROOT / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    def visit(value):
        if isinstance(value, dict):
            if value.get("module") == "memory.federation" or value.get("moduleId") == "memory.federation" or value.get("id") == "memory.federation":
                return value
            for child in value.values():
                found = visit(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found is not None:
                    return found
        return None

    profile = visit(data)
    if profile is None:
        raise SystemExit("memory.federation implementation profile not found")
    native = profile.get("nativeImplementation")
    if not isinstance(native, dict):
        raise SystemExit("memory.federation native implementation profile is missing")
    native["runtimeDocuments"] = [
        "docs/modules/memory.federation/TECHNICAL.md",
        "docs/modules/memory.federation/V2_HARDENING.md",
        "docs/modules/memory.federation/WIRE_PROTOCOL_V1.md",
        "docs/modules/memory.federation/THREAT_MODEL.md",
        "docs/modules/memory.federation/OPERATIONS.md",
        "docs/modules/memory.federation/sequence.mmd",
    ]
    native["remainingWork"] = [
        "Physical two-real-host authenticated transport and partition qualification remains external.",
        "Target-host capacity, latency, overload and backpressure qualification remains external.",
        "Independent semantic/security acceptance and operator canary/promotion/release remain external.",
    ]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    patch_generated_runtime_parent()
    patch_generated_cancellation_and_binding()
    patch_generated_diagnostics()
    patch_generated_wire()
    patch_state_sources()
    patch_profile()
    print("memory.federation metadata closure applied")


if __name__ == "__main__":
    main()
