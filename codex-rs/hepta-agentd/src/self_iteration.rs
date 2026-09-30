//! Durable orchestration of externally generated and independently evaluated
//! runtime candidates. This owner never signs or invents evaluation evidence.

use std::sync::Arc;

use codex_hepta_agent_components::intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_agent_components::intelligence_eval::decide_with_signed_evidence_v2;
use codex_hepta_agent_components::learning_artifacts::IterationEnvelopeV1;
use codex_hepta_agent_components::learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agent_components::learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_agent_components::learning_ledger::verify_signed_actor_separation;
use codex_hepta_agent_components::types::Digest32;

use crate::AgentdError;
use crate::AgentdNeuronRuntimeV2Host;
use crate::AgentdSignedEvaluationV1;

#[path = "self_iteration_codec.rs"]
mod codec;

#[path = "self_iteration_artifacts.rs"]
mod artifacts;
pub use artifacts::AgentdSelfIterationArtifactFileV1;
pub use artifacts::AgentdSelfIterationArtifactKindV1;
pub use artifacts::AgentdSelfIterationArtifactManifestV1;
pub use artifacts::AgentdSelfIterationArtifactReadinessV1;
pub use artifacts::inspect_self_iteration_artifacts_v1;

#[path = "self_iteration_pending_model.rs"]
mod pending_model;
pub use pending_model::AgentdSelfIterationPendingProposalV1;
pub use pending_model::assess_self_iteration_pending_inputs_v1;

#[path = "self_iteration_measurement.rs"]
mod measurement;
pub use measurement::AgentdSelfIterationPhysicalMeasurementV1;
pub use measurement::AgentdSelfIterationQualificationCaseV1;
pub use measurement::measure_self_iteration_qualification_v1;

#[path = "self_iteration_signer.rs"]
mod signer;
pub use signer::AgentdSelfIterationLocalSignerV1;

#[path = "self_iteration_contracts.rs"]
mod contracts;
pub use contracts::*;

#[path = "self_iteration_cycle.rs"]
mod cycle;
pub use cycle::AgentdSelfIterationCandidateAssemblerV1;
pub use cycle::AgentdSelfIterationIndependentOwnersV1;
pub use cycle::AgentdSelfIterationModelCycleV1;
pub use cycle::envelope_digest as self_iteration_envelope_digest_v1;

#[path = "self_iteration_parameter_factory.rs"]
mod parameter_factory;
pub use parameter_factory::AgentdGovernedParameterCandidateAssemblerV1;
pub use parameter_factory::AgentdGovernedParameterGenerationCompilerV1;

#[path = "self_iteration_payload.rs"]
mod payload;
pub use payload::self_iteration_canary_payload_v1;
pub use payload::self_iteration_candidate_payload_v1;
pub use payload::self_iteration_stage_payload_v1;

#[path = "self_iteration_apply.rs"]
mod apply;
#[path = "self_iteration_journal.rs"]
mod journal;
#[path = "self_iteration_runtime.rs"]
mod runtime;
use journal::IterationJournal;
pub use runtime::AgentdSelfIterationHandleV1;
pub use runtime::AgentdSelfIterationRuntimeConfigV1;

struct FrozenCandidate {
    request: AgentdSelfIterationCandidateV1,
    record: AgentdSelfIterationRecordV1,
    generator: VerifiedLearningEvidenceV1,
    evaluator: Option<VerifiedLearningEvidenceV1>,
    selector: Option<VerifiedLearningEvidenceV1>,
}

struct SelfIterationOwner {
    journal: IterationJournal,
    trust: Arc<ActivatedLearningTrustV1>,
    host: Arc<AgentdNeuronRuntimeV2Host>,
    current: Option<FrozenCandidate>,
    cancellation: tokio_util::sync::CancellationToken,
}

impl SelfIterationOwner {
    fn open(
        journal: IterationJournal,
        trust: Arc<ActivatedLearningTrustV1>,
        host: Arc<AgentdNeuronRuntimeV2Host>,
    ) -> Result<Self, AgentdError> {
        if journal.unresolved_apply() {
            // A restart never turns an unobserved candidate into accepted service.
            host.quarantine_iteration()?;
        }
        Ok(Self {
            journal,
            trust,
            host,
            current: None,
            cancellation: tokio_util::sync::CancellationToken::new(),
        })
    }

    fn freeze(
        &mut self,
        request: AgentdSelfIterationCandidateV1,
        now: u64,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let payload = self_iteration_candidate_payload_v1(&request)?;
        let frozen_digest = Digest32::of_bytes(&payload);
        let exact_recovery = self.journal.record().is_some_and(|previous| {
            previous.frozen_digest == frozen_digest && self.journal.pending()
        });
        if !exact_recovery
            && (request.envelope.expiry_unix_seconds <= now / 1_000
                || request.envelope.expiry_unix_seconds > (now / 1_000).saturating_add(3_600))
        {
            return Err(invalid("new iteration expired or exceeds lifetime"));
        }
        let generator = self
            .trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Generator,
                &request.generator_attestation,
                &payload,
                now,
            )
            .map_err(|error| invalid(error.to_string()))?;
        if generator.principal().principal_id != request.candidate.generator_identity
            || generator.objective_digest() != request.envelope.objective_digest
        {
            return Err(invalid("generator binding"));
        }
        if let Some(current) = self.current.as_ref() {
            if current.record.frozen_digest != frozen_digest {
                return Err(invalid("iteration busy with another frozen candidate"));
            }
            return Ok(current.record.clone());
        }
        let mut record = AgentdSelfIterationRecordV1 {
            candidate_id: request.candidate.candidate_id.to_string(),
            frozen_digest,
            objective_digest: request.envelope.objective_digest,
            base_generation: request.base_generation,
            successor_generation: request.base_generation + 1,
            rollback_generation: request.base_generation + 2,
            successor_configuration: request.successor.configuration_digest(),
            successor_body: request
                .successor
                .body_bundle_digest()
                .ok_or_else(|| invalid("successor durable body"))?,
            rollback_configuration: request.rollback_successor.configuration_digest(),
            rollback_body: request
                .rollback_successor
                .body_bundle_digest()
                .ok_or_else(|| invalid("rollback durable body"))?,
            expires_at: request.envelope.expiry_unix_seconds,
            phase: AgentdSelfIterationPhaseV1::Frozen,
            evaluation_digest: None,
            selection_digest: None,
            canary_operation_digest: None,
            canary_checkpoint_digest: None,
            canary_observation: None,
            observer_digest: None,
        };
        if let Some(previous) = self.journal.record() {
            if previous.frozen_digest == frozen_digest {
                if previous.candidate_id != record.candidate_id
                    || previous.objective_digest != record.objective_digest
                    || previous.base_generation != record.base_generation
                    || previous.successor_generation != record.successor_generation
                    || previous.rollback_generation != record.rollback_generation
                    || previous.successor_configuration != record.successor_configuration
                    || previous.rollback_configuration != record.rollback_configuration
                    || previous.successor_body != record.successor_body
                    || previous.rollback_body != record.rollback_body
                    || previous.expires_at != record.expires_at
                {
                    return Err(invalid("recovery changed frozen material"));
                }
                record = previous.clone();
            } else if self.journal.pending() {
                return Err(invalid("unresolved iteration requires exact recovery"));
            }
        }
        let actual = self.host.generation_snapshot()?;
        let expected = match record.phase {
            AgentdSelfIterationPhaseV1::Frozen
            | AgentdSelfIterationPhaseV1::Evaluated
            | AgentdSelfIterationPhaseV1::Rejected => record.base_generation,
            AgentdSelfIterationPhaseV1::Accepted => record.successor_generation,
            AgentdSelfIterationPhaseV1::RolledBack => record.rollback_generation,
            AgentdSelfIterationPhaseV1::Applying
            | AgentdSelfIterationPhaseV1::Canary
            | AgentdSelfIterationPhaseV1::RollingBack => actual.active_generation,
        };
        if actual.active_generation != expected
            || ![
                record.base_generation,
                record.successor_generation,
                record.rollback_generation,
            ]
            .contains(&actual.active_generation)
        {
            return Err(invalid("recovered iteration generation is not current"));
        }
        if record.phase == AgentdSelfIterationPhaseV1::Accepted
            && actual.active.body_bundle_digest
                != request
                    .successor
                    .body_bundle_digest()
                    .map(|digest| digest.to_string())
            || record.phase == AgentdSelfIterationPhaseV1::RolledBack
                && actual.active.body_bundle_digest
                    != request
                        .rollback_successor
                        .body_bundle_digest()
                        .map(|digest| digest.to_string())
        {
            return Err(invalid("recovered terminal configuration changed"));
        }
        self.journal.persist(&record)?;
        if matches!(
            record.phase,
            AgentdSelfIterationPhaseV1::Accepted
                | AgentdSelfIterationPhaseV1::RolledBack
                | AgentdSelfIterationPhaseV1::Rejected
        ) {
            return Ok(record);
        }
        self.current = Some(FrozenCandidate {
            request,
            record: record.clone(),
            generator,
            evaluator: None,
            selector: None,
        });
        if now / 1_000 >= record.expires_at {
            self.expire(now)?;
            return self
                .journal
                .record()
                .cloned()
                .ok_or_else(|| invalid("expired recovery missing"));
        }
        Ok(record)
    }

    fn evaluate(
        &mut self,
        frozen_digest: Digest32,
        signed: AgentdSignedEvaluationV1,
        now: u64,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let current = self
            .current
            .as_mut()
            .ok_or_else(|| invalid("candidate not frozen"))?;
        if current.record.frozen_digest != frozen_digest
            || now / 1_000 >= current.record.expires_at
            || signed.bundle.candidate_id != current.request.candidate.candidate_id
            || signed.bundle.baseline_id
                != *current
                    .request
                    .candidate
                    .predecessor
                    .as_ref()
                    .ok_or_else(|| invalid("baseline missing"))?
            || signed.bundle.objective_digest != current.record.objective_digest
            || signed.bundle.generator != *current.generator.principal()
            || signed.bundle.frozen_plan.plan_digest != current.request.candidate.test_plan_digest
        {
            return Err(invalid("evaluation candidate binding"));
        }
        let expected_evaluator = signed.bundle.evaluator.clone();
        let result = decide_with_signed_evidence_v2(
            signed.bundle,
            signed.roles,
            &signed.evidence,
            self.trust.verifier(),
            now,
        )
        .map_err(|error| invalid(error.to_string()))?;
        if result.decision.authority.grants_any() {
            return Err(invalid("evaluation granted authority"));
        }
        let evaluator = self
            .trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &signed.use_attestation,
                &self_iteration_stage_payload_v1(frozen_digest, result.authentication_digest),
                now,
            )
            .map_err(|error| invalid(error.to_string()))?;
        if evaluator.principal() != &expected_evaluator {
            return Err(invalid(
                "evaluation use signer differs from bundle evaluator",
            ));
        }
        verify_signed_actor_separation(&current.generator, &evaluator, now)
            .map_err(|error| invalid(error.to_string()))?;
        if let Some(previous) = current.record.evaluation_digest
            && previous != result.authentication_digest
        {
            return Err(invalid("recovery changed evaluation"));
        }
        if result.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            // An authenticated failed experiment completes this round. No
            // selection or installation occurred, so the predecessor keeps
            // serving and the next candidate need not wait for expiry.
            if !matches!(
                current.record.phase,
                AgentdSelfIterationPhaseV1::Frozen | AgentdSelfIterationPhaseV1::Evaluated
            ) || self.host.generation_snapshot()?.active_generation
                != current.record.base_generation
            {
                return Err(invalid("rejection predecessor changed"));
            }
            let mut rejected = current.record.clone();
            rejected.evaluation_digest = Some(result.authentication_digest);
            rejected.phase = AgentdSelfIterationPhaseV1::Rejected;
            self.journal.persist(&rejected)?;
            self.current = None;
            return Ok(rejected);
        }
        current.record.evaluation_digest = Some(result.authentication_digest);
        if current.record.phase == AgentdSelfIterationPhaseV1::Frozen {
            current.record.phase = AgentdSelfIterationPhaseV1::Evaluated;
        }
        current.evaluator = Some(evaluator);
        self.journal.persist(&current.record)?;
        Ok(current.record.clone())
    }
}

fn invalid(message: impl Into<String>) -> AgentdError {
    AgentdError::Invalid(message.into())
}
fn control_error(error: crate::AgentdNeuronControlErrorV2) -> AgentdError {
    if matches!(
        error,
        crate::AgentdNeuronControlErrorV2::OwnerBusy
            | crate::AgentdNeuronControlErrorV2::ControllerBusy
            | crate::AgentdNeuronControlErrorV2::PendingRecovery
    ) {
        return AgentdError::Overloaded {
            retry_after_ms: 1_000,
        };
    }
    AgentdError::Protocol(format!("self-iteration runtime: {error}"))
}
