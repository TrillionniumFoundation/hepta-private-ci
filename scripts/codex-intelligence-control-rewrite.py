#!/usr/bin/env python3
"""One-shot exact rewrite for the intelligence.control closure branch.

Every replacement is asserted. Source drift fails rather than silently editing
another control path. The script is idempotent after its target patch lands.
"""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{path}: expected one rewrite target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_exact(path: str, old: str, new: str, expected: int) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and text.count(new) == expected:
        return
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} rewrite targets, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    tests = "codex-rs/hepta-agentd/src/intelligence_product_tests.rs"
    replace_once(
        tests,
        '        supervisor_generation: 1,\n        agentd_generation: 1,',
        '        supervisor_generation: 1,\n        agentd_generation: 2,',
    )
    replace_once(
        tests,
        '        body_generation: generation(7),',
        '        body_generation: generation(2),',
    )
    replace_once(
        tests,
        '    Fixture {\n        request: CanonicalIntelligenceRunRequestV1 {',
        '''    let run_identity = crate::AgentdIntelligenceRunIdentityV1 {
        run_id: id("run:agentd-intelligence"),
        request_digest: digest("durable-run-start-identity"),
        objective_digest,
        body_digest: digest("body"),
        artifact_set_digest: digest("artifact-set"),
        authority_epoch: 11,
        generation: 2,
        fence_digest: crate::objective_run_fence_digest_v1("agent.product", 1, 2),
        deadline_ms: u64::MAX - 1,
    };

    Fixture {
        request: CanonicalIntelligenceRunRequestV1 {''',
    )
    replace_once(
        tests,
        '        inputs: AgentdIntelligenceOwnerInputsV1 {\n            objective_envelope: envelope,',
        '        inputs: AgentdIntelligenceOwnerInputsV1 {\n            run_identity: Some(run_identity),\n            objective_envelope: envelope,',
    )

    replace_once(
        "codex-rs/hepta-agentd/src/state.rs",
        '                let admitted = runs\n                    .start_run(',
        '                let admitted = runs\n                    .start_bound_run(',
    )
    replace_once(
        "codex-rs/hepta-agentd/src/state.rs",
        '''pub(crate) fn objective_run_fence(identity: &AgentdIdentity, current_generation: u64) -> String {
    let mut bytes = b"hepta:agentd:objective-fence:v1\\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Sha256Digest::for_bytes(&bytes).as_str().to_string()
}''',
        '''pub(crate) fn objective_run_fence(identity: &AgentdIdentity, current_generation: u64) -> String {
    crate::objective_run_fence_digest_v1(
        identity.agent_id.as_str(),
        identity.spawn_generation,
        current_generation,
    )
    .to_string()
}''',
    )
    replace_once(
        "codex-rs/hepta-agentd/src/objective_runtime.rs",
        '''fn objective_fence(identity: &AgentdIdentity, current_generation: u64) -> Digest32 {
    let mut bytes = b"hepta:agentd:objective-fence:v1\\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}''',
        '''fn objective_fence(identity: &AgentdIdentity, current_generation: u64) -> Digest32 {
    crate::objective_run_fence_digest_v1(
        identity.agent_id.as_str(),
        identity.spawn_generation,
        current_generation,
    )
}''',
    )
    replace_once(
        "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
        '        self.start_run(\n            now_ms,\n            RunSnapshot {',
        '        self.start_bound_run(\n            now_ms,\n            RunSnapshot {',
    )

    lib = "codex-rs/hepta-agentd/src/lib.rs"
    replace_once(
        lib,
        "mod intelligence_ingress;\nmod intelligence_product;",
        "mod intelligence_ingress;\nmod intelligence_learning;\nmod intelligence_observability;\nmod intelligence_product;",
    )
    replace_once(
        lib,
        '''pub use intelligence_ingress::objective_run_fence_digest_v1;
pub use intelligence_product::AgentdEvaluationBindingV1;''',
        '''pub use intelligence_ingress::objective_run_fence_digest_v1;
pub use intelligence_learning::AgentdIntelligenceDecisionAppendV1;
pub use intelligence_learning::AgentdIntelligenceLearningDispositionV1;
pub use intelligence_learning::AgentdIntelligenceLearningErrorV1;
pub use intelligence_learning::AgentdIntelligenceLearningHostV1;
pub use intelligence_learning::AgentdIntelligenceLearningReceiptV1;
pub use intelligence_learning::AgentdIntelligenceOutcomeAppendV1;
pub use intelligence_learning::append_intelligence_decision_v1;
pub use intelligence_learning::append_intelligence_outcome_v1;
pub use intelligence_learning::intelligence_physical_terminal_binding_digest_v1;
pub use intelligence_learning::intelligence_run_snapshot_digest_v1;
pub use intelligence_observability::AgentdIntelligenceStageTelemetrySnapshotV1;
pub use intelligence_observability::AgentdIntelligenceTelemetrySnapshotV1;
pub use intelligence_observability::AgentdIntelligenceTelemetryV1;
pub use intelligence_product::AgentdEvaluationBindingV1;''',
    )

    learning = "codex-rs/hepta-agentd/src/intelligence_learning.rs"
    replace_once(
        learning,
        "use codex_hepta_operations::DurableOperationState;\n",
        "",
    )

    product = "codex-rs/hepta-agentd/src/intelligence_product.rs"
    replace_once(
        product,
        "use std::path::PathBuf;\nuse std::str::FromStr;",
        "use std::path::PathBuf;\nuse std::str::FromStr;\nuse std::sync::Arc;",
    )
    replace_once(
        product,
        '''struct FileBackedFreshnessOracleV1 {
    path: PathBuf,
    verifier: IntelligenceAuthorityVerifierV1,
}''',
        '''struct FileBackedFreshnessOracleV1 {
    path: PathBuf,
    verifier: IntelligenceAuthorityVerifierV1,
    telemetry: Option<Arc<crate::AgentdIntelligenceTelemetryV1>>,
}''',
    )
    replace_once(
        product,
        '''    fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {
        Self { path, verifier }
    }
''',
        '''    fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {
        Self {
            path,
            verifier,
            telemetry: None,
        }
    }

    fn new_observed(
        path: PathBuf,
        verifier: IntelligenceAuthorityVerifierV1,
        telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    ) -> Self {
        Self {
            path,
            verifier,
            telemetry: Some(telemetry),
        }
    }
''',
    )
    replace_once(
        product,
        '''        if file.schema_version != 1 || file.authority_epoch == 0 {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        let frontier = Digest32::from_str(&file.revocation_frontier_digest)''',
        '''        if file.schema_version != 1 || file.authority_epoch == 0 {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        if let Some(telemetry) = self.telemetry.as_ref() {
            telemetry.record_authority_manifest(file.authority_epoch);
        }
        let frontier = Digest32::from_str(&file.revocation_frontier_digest)''',
    )
    replace_once(
        product,
        '''struct AgentdOwnerPortsV1 {
    objective_envelope: Option<ObjectiveSourceEnvelopeV1>,''',
        '''struct AgentdOwnerPortsV1 {
    telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    objective_envelope: Option<ObjectiveSourceEnvelopeV1>,''',
    )
    replace_once(
        product,
        '''    fn new(
        value: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
    ) -> Self {
        Self {
            objective_envelope: Some(value.objective_envelope),''',
        '''    fn new(
        value: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
        telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    ) -> Self {
        Self {
            telemetry,
            objective_envelope: Some(value.objective_envelope),''',
    )
    replace_once(
        product,
        '''    fn within_budget(
        input: &CanonicalPortInputV1,
        started: Instant,
    ) -> Result<(), CanonicalPortFailureV1> {
        let elapsed = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        if elapsed > input.budget_micros {''',
        '''    fn within_budget(
        &self,
        input: &CanonicalPortInputV1,
        started: Instant,
    ) -> Result<(), CanonicalPortFailureV1> {
        let elapsed = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        self.telemetry.record_stage_latency(input.stage, elapsed);
        if elapsed > input.budget_micros {''',
    )
    replace_exact(
        product,
        "        Self::within_budget(input, started)?;",
        "        self.within_budget(input, started)?;",
        7,
    )
    replace_once(
        product,
        '''pub struct AgentdIntelligenceProductRunnerV1 {
    worker_slots: std::sync::Arc<tokio::sync::Semaphore>,
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
    evaluation_trust: Option<std::sync::Arc<codex_hepta_learning_ledger::ActivatedLearningTrustV1>>,
}''',
        '''pub struct AgentdIntelligenceProductRunnerV1 {
    worker_slots: std::sync::Arc<tokio::sync::Semaphore>,
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
    evaluation_trust: Option<std::sync::Arc<codex_hepta_learning_ledger::ActivatedLearningTrustV1>>,
    telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    hard_timeout_process_exit_grace: Option<Duration>,
}''',
    )

    runtime = "codex-rs/hepta-agentd/src/runtime.rs"
    replace_once(
        runtime,
        '''    if let Some(provider) = intelligence_invocation {
        state.intelligence_invocation.set(provider).map_err(|_| {
            AgentdError::Invalid("intelligence invocation provider already attached".to_string())
        })?;
    }''',
        '''    if let Some(provider) = intelligence_invocation {
        state.intelligence_invocation.set(provider).map_err(|_| {
            AgentdError::Invalid("intelligence invocation provider already attached".to_string())
        })?;
        if let Some(runner) = state.intelligence_product.get() {
            runner.telemetry().set_provider_configured(true);
        }
    }''',
    )


if __name__ == "__main__":
    main()
