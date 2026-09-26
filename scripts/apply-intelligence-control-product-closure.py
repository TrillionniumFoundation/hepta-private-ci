#!/usr/bin/env python3
"""Apply the reviewed intelligence.control product-closure source edits.

Every edit is fail-closed: the expected old fragment must occur exactly once.
The script is intentionally branch-local and is deleted by the apply workflow
once the resulting source candidate has been committed.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one match, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1))


def append_once(relative: str, marker: str, addition: str) -> None:
    path = ROOT / relative
    text = path.read_text()
    if addition in text:
        return
    count = text.count(marker)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one append marker, found {count}")
    path.write_text(text.replace(marker, marker + addition, 1))


# ---------------------------------------------------------------------------
# One generation/fence contract, enforced by the run owner.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "use std::collections::BTreeMap;\n\nuse codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;",
    "use std::collections::BTreeMap;\n\nuse sha2::Digest as _;\nuse sha2::Sha256;\n\nuse codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "pub struct RuntimeComposition {\n    pub agent_id: String,\n    pub supervisor_generation: u64,\n    pub agentd_generation: u64,\n    pub configuration_digest: String,\n    pub ports_digest: String,\n    pub max_active_runs: usize,\n}\n",
    "pub struct RuntimeComposition {\n    pub agent_id: String,\n    pub supervisor_generation: u64,\n    pub agentd_generation: u64,\n    pub configuration_digest: String,\n    pub ports_digest: String,\n    pub max_active_runs: usize,\n}\n\nimpl RuntimeComposition {\n    #[must_use]\n    pub fn expected_run_fence_digest(&self) -> String {\n        run_fence_digest(\n            &self.agent_id,\n            self.supervisor_generation,\n            self.agentd_generation,\n        )\n    }\n}\n\n/// The only run-fence construction in Agentd. `supervisor_generation` is the\n/// immutable process-launch generation; `agentd_generation` is the current\n/// Fleet lifecycle generation served by that process.\npub(crate) fn run_fence_digest(\n    agent_id: &str,\n    supervisor_generation: u64,\n    agentd_generation: u64,\n) -> String {\n    let mut bytes = b\"hepta:agentd:objective-fence:v1\\0\".to_vec();\n    bytes.extend_from_slice(agent_id.as_bytes());\n    bytes.extend_from_slice(&supervisor_generation.to_be_bytes());\n    bytes.extend_from_slice(&agentd_generation.to_be_bytes());\n    format!(\"{:x}\", Sha256::digest(&bytes))\n}\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "    ArithmeticOverflow,\n    InvalidRunStart(&'static str),\n}",
    "    ArithmeticOverflow,\n    InvalidRunStart(&'static str),\n    InvalidCompositionIdentity(&'static str),\n}",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "    pub fn composition(&self) -> &RuntimeComposition {\n        &self.composition\n    }\n\n    pub fn admissions_open(&self) -> bool {",
    "    pub fn composition(&self) -> &RuntimeComposition {\n        &self.composition\n    }\n\n    /// Advance to the exact Fleet lifecycle generation served by this process.\n    /// The launch generation stays immutable and remains part of every fence.\n    pub fn bind_agentd_generation(&mut self, generation: u64) -> Result<(), AgentRunError> {\n        if generation == 0\n            || generation < self.composition.supervisor_generation\n            || generation < self.composition.agentd_generation\n        {\n            return Err(AgentRunError::InvalidGeneration);\n        }\n        self.composition.agentd_generation = generation;\n        Ok(())\n    }\n\n    pub fn admissions_open(&self) -> bool {",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "        if !self.accepting_runs {\n            return Err(AgentRunError::AdmissionClosed);\n        }",
    "        if snapshot.generation != self.composition.agentd_generation {\n            return Err(AgentRunError::InvalidCompositionIdentity(\n                \"agentd generation\",\n            ));\n        }\n        if snapshot.fence_digest != self.composition.expected_run_fence_digest() {\n            return Err(AgentRunError::InvalidCompositionIdentity(\"run fence\"));\n        }\n        if !self.accepting_runs {\n            return Err(AgentRunError::AdmissionClosed);\n        }",
)
append_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "fn validate_snapshot_fields(value: &RunSnapshot) -> Result<(), AgentRunError> {",
    "",
)

# Keep the coordinator's current lifecycle epoch synchronized without retaining
# the runtime mutex while acquiring the run mutex.
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    """        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.current_generation != record.lifecycle.generation
            || runtime.lifecycle != record.lifecycle.lifecycle
        {
            runtime.current_generation = record.lifecycle.generation;
            runtime.lifecycle = record.lifecycle.lifecycle;
            if runtime.lifecycle != AgentLifecycle::Running {
                runtime.admission_open = false;
            }
            if matches!(
                runtime.lifecycle,
                AgentLifecycle::Draining | AgentLifecycle::Stopped | AgentLifecycle::Failed
            ) {
                runtime.app_server_ready = false;
                runtime.required_ports_ready = false;
            }
            if runtime.lifecycle == AgentLifecycle::Running
                && runtime.app_server_ready
                && runtime.critical_stores_ready
                && runtime.revocation_ready
                && runtime.required_ports_ready
                && !runtime.fenced
            {
                runtime.admission_open = true;
            }
            self.events
                .lock()
                .map_err(poisoned_state)?
                .push(AgentdEventKind::Lifecycle {
                    lifecycle: record.lifecycle.lifecycle,
                    generation: record.lifecycle.generation,
                });
            if runtime.lifecycle == AgentLifecycle::Draining {
                self.runs
                    .lock()
                    .map_err(poisoned_state)?
                    .begin_drain(unix_now_ms()?, "supervisor_draining")
                    .map_err(run_error)?;
            }
        }
""",
    """        let mut lifecycle_change = None;
        let mut begin_drain = false;
        {
            let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
            if runtime.current_generation != record.lifecycle.generation
                || runtime.lifecycle != record.lifecycle.lifecycle
            {
                runtime.current_generation = record.lifecycle.generation;
                runtime.lifecycle = record.lifecycle.lifecycle;
                if runtime.lifecycle != AgentLifecycle::Running {
                    runtime.admission_open = false;
                }
                if matches!(
                    runtime.lifecycle,
                    AgentLifecycle::Draining | AgentLifecycle::Stopped | AgentLifecycle::Failed
                ) {
                    runtime.app_server_ready = false;
                    runtime.required_ports_ready = false;
                }
                if runtime.lifecycle == AgentLifecycle::Running
                    && runtime.app_server_ready
                    && runtime.critical_stores_ready
                    && runtime.revocation_ready
                    && runtime.required_ports_ready
                    && !runtime.fenced
                {
                    runtime.admission_open = true;
                }
                lifecycle_change = Some((runtime.lifecycle, runtime.current_generation));
                begin_drain = runtime.lifecycle == AgentLifecycle::Draining;
            }
        }
        if let Some((lifecycle, generation)) = lifecycle_change {
            self.runs
                .lock()
                .map_err(poisoned_state)?
                .bind_agentd_generation(generation)
                .map_err(run_error)?;
            self.events
                .lock()
                .map_err(poisoned_state)?
                .push(AgentdEventKind::Lifecycle {
                    lifecycle,
                    generation,
                });
            if begin_drain {
                self.runs
                    .lock()
                    .map_err(poisoned_state)?
                    .begin_drain(unix_now_ms()?, "supervisor_draining")
                    .map_err(run_error)?;
            }
        }
""",
)
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    """pub(crate) fn objective_run_fence(identity: &AgentdIdentity, current_generation: u64) -> String {
    let mut bytes = b"hepta:agentd:objective-fence:v1\\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Sha256Digest::for_bytes(&bytes).as_str().to_string()
}
""",
    """pub(crate) fn objective_run_fence(identity: &AgentdIdentity, current_generation: u64) -> String {
    crate::lane_b_runtime::run_fence_digest(
        identity.agent_id.as_str(),
        identity.spawn_generation,
        current_generation,
    )
}
""",
)

# ---------------------------------------------------------------------------
# Exact durable RunStart inheritance and a concrete host-owned provider seam.
# ---------------------------------------------------------------------------
(ROOT / "codex-rs/hepta-agentd/src/intelligence_ingress.rs").write_text(
    r'''//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective. It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material. A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;

/// Exact durable ObjectiveStart identity inherited by the prepared run.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceRunStartBindingV1 {
    pub request_digest: Digest32,
    pub runtime_body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub fence_digest: Digest32,
    pub run_start_binding_digest: Digest32,
    pub generation: u64,
    pub deadline_ms: u64,
}

impl AgentdIntelligenceRunStartBindingV1 {
    pub fn from_record(record: &RunStartRecordV1) -> Result<Self, AgentdError> {
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .ok_or_else(|| AgentdError::Invalid("objective deadline overflow".to_string()))?;
        if record.snapshot.generation == 0 || deadline_ms == 0 {
            return Err(AgentdError::Invalid(
                "objective run-start generation or deadline is invalid".to_string(),
            ));
        }
        Ok(Self {
            request_digest: record.admission.admitted_source_digest,
            runtime_body_digest: record.runtime_body_digest,
            artifact_set_digest: record.snapshot.artifact_set_digest,
            fence_digest: record.snapshot.fence_digest,
            run_start_binding_digest: run_start_binding_digest(record)?,
            generation: record.snapshot.generation,
            deadline_ms,
        })
    }
}

pub struct AgentdIntelligenceInvocationV1 {
    pub request: CanonicalIntelligenceRunRequestV1,
    pub inputs: AgentdIntelligenceOwnerInputsV1,
}

impl AgentdIntelligenceInvocationV1 {
    pub(crate) fn validate(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        let snapshot = &record.snapshot;
        let run_start = AgentdIntelligenceRunStartBindingV1::from_record(record)?;
        let expected_fence = crate::lane_b_runtime::run_fence_digest(
            identity.agent_id.as_str(),
            identity.spawn_generation,
            snapshot.generation,
        );
        if record.disposition != RunStartObjectiveDispositionV1::Compiled
            || self.request.run_id != snapshot.run_id
            || self.request.snapshot.objective_digest() != snapshot.objective_digest
            || self.request.snapshot.authority_epoch() != snapshot.authority_epoch
            || self.request.snapshot.body_generation().get() != snapshot.generation
            || self.request.snapshot.configuration_digest() != run_start.run_start_binding_digest
            || self.request.legal_candidates.state_digest != snapshot.objective_digest
            || self.inputs.run_start != run_start
            || run_start.fence_digest.to_string() != expected_fence
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation does not match the durable RunStart identity"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

fn run_start_binding_digest(record: &RunStartRecordV1) -> Result<Digest32, AgentdError> {
    let mut bytes = b"hepta.agentd.intelligence-run-start-binding.v1\0".to_vec();
    push_id(&mut bytes, &record.snapshot.run_id)?;
    for digest in [
        record.snapshot.objective_digest,
        record.snapshot.hard_constraint_digest,
        record.snapshot.preference_state_digest,
        record.snapshot.model_tuple_digest,
        record.snapshot.prompt_registry_digest,
        record.snapshot.artifact_set_digest,
        record.snapshot.fence_digest,
        record.runtime_body_digest,
        record.admission.profile_digest,
        record.admission.supplied_source_digest,
        record.admission.intent_digest,
        record.admission.admitted_source_digest,
        record.objective_function_v1_digest,
        record.authentication.scope_digest,
        record.authentication.signed_body_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &record.admission.profile_id)?;
    bytes.extend_from_slice(&record.admission.profile_revision.to_be_bytes());
    bytes.extend_from_slice(&record.admission.observed_at_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&record.admission.deadline_unix_micros.to_be_bytes());
    bytes.push(u8::from(record.admission.authority.grants_any()));
    bytes.extend_from_slice(&record.snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&record.snapshot.generation.to_be_bytes());
    push_id(&mut bytes, &record.authentication.issuer_id)?;
    bytes.extend_from_slice(&record.authentication.key_epoch.to_be_bytes());
    push_id(&mut bytes, &record.authentication.message_id)?;
    bytes.extend_from_slice(&record.authentication.sequence.to_be_bytes());
    bytes.extend_from_slice(&record.authentication.expires_at_ms.to_be_bytes());
    bytes.extend_from_slice(&record.authentication.signature);
    bytes.push(match record.disposition {
        RunStartObjectiveDispositionV1::Compiled => 0,
        RunStartObjectiveDispositionV1::ExplicitAbstain => 1,
    });
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), AgentdError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| AgentdError::Invalid("run-start identity is too long".to_string()))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

/// Composition seam for the seven canonical intelligence owners.
///
/// Implementations are host-owned and must derive current stage inputs from
/// their authoritative owners. Request/wire callers cannot provide this object.
pub trait AgentdIntelligenceInvocationProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>;
}
'''
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "pub struct AgentdIntelligenceOwnerInputsV1 {\n    pub objective_envelope: ObjectiveSourceEnvelopeV1,",
    "pub struct AgentdIntelligenceOwnerInputsV1 {\n    pub run_start: crate::AgentdIntelligenceRunStartBindingV1,\n    pub objective_envelope: ObjectiveSourceEnvelopeV1,",
)

# Order-independent candidate closure and inherited run identity.
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    """        let candidate_ids = request
            .legal_candidates
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        let intuition_ids = inputs
            .intuition_request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        if candidate_ids != intuition_ids {
""",
    """        let mut candidate_ids = request
            .legal_candidates
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        let mut intuition_ids = inputs
            .intuition_request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        candidate_ids.sort();
        intuition_ids.sort();
        if candidate_ids != intuition_ids {
""",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    """        // Freeze the identity of the existing owner, never a new coordinator
        // or a caller-selected body/model generation. Agentd validates this
        // fence again at the actual admission and attachment boundary.
        let generation = composition.agentd_generation;
        let mut fence_bytes = b"hepta:agentd:objective-fence:v1\\0".to_vec();
        fence_bytes.extend_from_slice(composition.agent_id.as_bytes());
        fence_bytes.extend_from_slice(&generation.to_be_bytes());
        fence_bytes.extend_from_slice(&generation.to_be_bytes());
        let fence_digest = Digest32::of_bytes(&fence_bytes).to_string();
        let snapshot = request.snapshot.clone();
        let timeout_micros = request.budget.total_micros;
        let started_ms = wall_clock_ms()?;
        let timeout_ms = timeout_micros.saturating_add(999) / 1_000;
        let deadline_ms = started_ms
            .checked_add(timeout_ms.max(1))
            .ok_or(AgentdIntelligenceProductError::Clock)?;
""",
    """        // Inherit the exact durable ObjectiveStart identity. The cognition
        // worker may not synthesize request/body/artifact/deadline identities.
        let run_start = inputs.run_start.clone();
        let snapshot = request.snapshot.clone();
        if run_start.generation != composition.agentd_generation
            || run_start.fence_digest.to_string() != composition.expected_run_fence_digest()
            || run_start.run_start_binding_digest != snapshot.configuration_digest()
            || run_start.generation != snapshot.body_generation().get()
        {
            return Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::InvalidCompositionIdentity(
                    "durable intelligence run-start",
                ),
            ));
        }
        let timeout_micros = request.budget.total_micros;
        let started_ms = wall_clock_ms()?;
        if run_start.deadline_ms <= started_ms {
            return Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::InvalidDeadline,
            ));
        }
""",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    """                let mut bytes = b"hepta.agentd.intelligence-dispatch-proposal.v1\\0".to_vec();
                bytes.extend_from_slice(envelope.envelope_digest.as_array());
                bytes.extend_from_slice(snapshot.revocation_frontier_digest().as_array());
                let dispatch_proposal_digest = Digest32::of_bytes(&bytes);
                let mut body = b"hepta.agentd.intelligence-body.v1\\0".to_vec();
                body.extend_from_slice(snapshot.digest().as_array());
                body.extend_from_slice(&snapshot.body_generation().get().to_be_bytes());
                let body_digest = Digest32::of_bytes(&body);
                let run_snapshot = crate::AgentRunSnapshot {
                    run_id: envelope.run_id.to_string(),
                    request_digest: envelope.trace_digest.to_string(),
                    objective_digest: envelope.objective_digest.to_string(),
                    body_digest: body_digest.to_string(),
                    artifact_set_digest: snapshot.digest().to_string(),
                    authority_epoch: snapshot.authority_epoch(),
                    generation,
                    fence_digest,
                    deadline_ms,
                };
""",
    """                let mut bytes = b"hepta.agentd.intelligence-dispatch-proposal.v1\\0".to_vec();
                bytes.extend_from_slice(envelope.envelope_digest.as_array());
                bytes.extend_from_slice(run_start.run_start_binding_digest.as_array());
                bytes.extend_from_slice(snapshot.revocation_frontier_digest().as_array());
                let dispatch_proposal_digest = Digest32::of_bytes(&bytes);
                let run_snapshot = crate::AgentRunSnapshot {
                    run_id: envelope.run_id.to_string(),
                    request_digest: run_start.request_digest.to_string(),
                    objective_digest: envelope.objective_digest.to_string(),
                    body_digest: run_start.runtime_body_digest.to_string(),
                    artifact_set_digest: run_start.artifact_set_digest.to_string(),
                    authority_epoch: snapshot.authority_epoch(),
                    generation: run_start.generation,
                    fence_digest: run_start.fence_digest.to_string(),
                    deadline_ms: run_start.deadline_ms,
                };
""",
)

# ---------------------------------------------------------------------------
# Canonical fail-closed membership and propensity invariants.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    "    AuthorityWidening,\n    UnexpectedDecision,\n    Arithmetic,",
    "    AuthorityWidening,\n    UnexpectedDecision,\n    SelectedCandidateNotLegal(StableId),\n    InvalidSelectedPropensity,\n    Arithmetic,",
)
replace_once(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    """pub fn decide_boundary(
    run_id: &StableId,
    candidate_set_digest: Digest32,
    intuition: &CanonicalPortReceiptV1,
) -> Result<AdvisoryDecisionReceiptV1, CanonicalIntelligenceError> {
""",
    """pub fn decide_boundary(
    run_id: &StableId,
    candidate_set: &LegalActionCandidateSetV1,
    intuition: &CanonicalPortReceiptV1,
) -> Result<AdvisoryDecisionReceiptV1, CanonicalIntelligenceError> {
    let candidate_set_digest = candidate_set.candidate_set_digest;
""",
)
replace_once(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    """        CanonicalPortDecisionV1::Selected {
            candidate_id,
            propensity,
        } => AdvisoryDecisionV1::Selected {
            candidate_id: candidate_id.clone(),
            propensity: *propensity,
        },
""",
    """        CanonicalPortDecisionV1::Selected {
            candidate_id,
            propensity,
        } => {
            if propensity.raw() == 0 {
                return Err(CanonicalIntelligenceError::InvalidSelectedPropensity);
            }
            if !candidate_set
                .candidates
                .iter()
                .any(|candidate| &candidate.candidate_id == candidate_id)
            {
                return Err(CanonicalIntelligenceError::SelectedCandidateNotLegal(
                    candidate_id.clone(),
                ));
            }
            AdvisoryDecisionV1::Selected {
                candidate_id: candidate_id.clone(),
                propensity: *propensity,
            }
        }
""",
)
replace_once(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    "let decision = decide_boundary(&request.run_id, legal.candidate_set_digest, &intuition)?;",
    "let decision = decide_boundary(&request.run_id, &legal, &intuition)?;",
)

# ---------------------------------------------------------------------------
# Wire the concrete provider, durable outbox and their public contracts.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod intelligence_ingress;\nmod intelligence_product;",
    "mod intelligence_ingress;\nmod intelligence_invocation_registry;\nmod intelligence_learning_outbox;\nmod intelligence_product;",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use intelligence_ingress::AgentdIntelligenceInvocationV1;\npub use intelligence_product::AgentdEvaluationBindingV1;",
    "pub use intelligence_ingress::AgentdIntelligenceInvocationV1;\npub use intelligence_ingress::AgentdIntelligenceRunStartBindingV1;\npub use intelligence_invocation_registry::MAX_PENDING_INTELLIGENCE_INVOCATIONS;\npub use intelligence_invocation_registry::RegisteredAgentdIntelligenceInvocationProviderV1;\npub use intelligence_learning_outbox::IntelligenceLearningIntentKindV1;\npub use intelligence_learning_outbox::IntelligenceLearningIntentV1;\npub use intelligence_learning_outbox::IntelligenceLearningOutboxError;\npub use intelligence_learning_outbox::IntelligenceLearningOutboxRecordV1;\npub use intelligence_learning_outbox::IntelligenceLearningOutboxStateV1;\npub use intelligence_learning_outbox::IntelligenceLearningOutboxV1;\npub use intelligence_product::AgentdEvaluationBindingV1;",
)

# Remove now-unused digest helper import in state.rs only when the compiler no
# longer needs it elsewhere. The import may still serve other state code, so
# leave it in place until Clippy proves it unused.

# Delete the first-generation patch artifact; this script is the auditable
# deterministic replacement.
patch = ROOT / "qualification/patches/intelligence-control-product-closure.patch"
if patch.exists():
    patch.unlink()
