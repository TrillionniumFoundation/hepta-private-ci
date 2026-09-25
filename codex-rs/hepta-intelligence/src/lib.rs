//! Bounded intelligence composition and abstention.
//!
//! The output is a plan receipt. It cannot invoke a model, tool or provider,
//! execute an effect, activate a learned artifact, promote or release. The opt-in
//! evaluated shadow adapter can append Decisions to a host-owned durable ledger.

#![forbid(unsafe_code)]

mod canonical;

pub use canonical::AdvisoryDecisionReceiptV1;
pub use canonical::AdvisoryDecisionV1;
pub use canonical::CanonicalBudgetV1;
pub use canonical::CanonicalFreshnessOracleV1;
pub use canonical::CanonicalIntelligenceError;
pub use canonical::CanonicalIntelligenceRunRequestV1;
pub use canonical::CanonicalIntelligenceSnapshotV1;
pub use canonical::CanonicalOwnerPortsV1;
pub use canonical::CanonicalPortDecisionV1;
pub use canonical::CanonicalPortFailureClassV1;
pub use canonical::CanonicalPortFailureV1;
pub use canonical::CanonicalPortInputV1;
pub use canonical::CanonicalPortReceiptV1;
pub use canonical::CanonicalRunOutcomeV1;
pub use canonical::CanonicalSnapshotRequestV1;
pub use canonical::CanonicalStageTraceV1;
pub use canonical::CanonicalStageV1;
pub use canonical::CanonicalTerminalReceiptV1;
pub use canonical::ContextAssemblyReceiptV1;
pub use canonical::CurrentOwnerStateV1;
pub use canonical::IntelligenceHostEnvelopeV1;
pub use canonical::LegalActionCandidateSetRequestV1;
pub use canonical::LegalActionCandidateSetV1;
pub use canonical::LegalActionCandidateV1;
pub use canonical::OwnerBindingV1;
pub use canonical::assemble_context;
pub use canonical::build_legal_candidates;
pub use canonical::decide_boundary;
pub use canonical::prepare_intelligence_run;
pub use canonical::validate_current_snapshot;

mod evaluated_shadow;
mod ndu_stochastic_admission;
mod neuron_runtime;
mod outcome_credit_v2;

pub use evaluated_shadow::EvaluatedShadowError;
pub use evaluated_shadow::EvaluatedShadowReceiptV1;
pub use evaluated_shadow::EvaluatedShadowRequestV1;
pub use evaluated_shadow::evaluated_candidate_signing_payload_v1;
pub use evaluated_shadow::evaluated_candidate_signing_payload_v2;
pub use evaluated_shadow::evaluated_shadow_production_decision_v2;
pub use evaluated_shadow::run_evaluated_shadow_v1;
pub use outcome_credit_v2::ObservedOutcomeRequestV2;
pub use outcome_credit_v2::OutcomeCreditClosureErrorV2;
pub use outcome_credit_v2::OutcomeCreditClosureReceiptV2;
pub use outcome_credit_v2::OutcomeCreditClosureRequestV2;
pub use outcome_credit_v2::append_observed_outcome_v2;
pub use outcome_credit_v2::append_outcome_credit_v2;

mod objective_run;

pub use ndu_stochastic_admission::NduStochasticAdmissionError;
pub use ndu_stochastic_admission::NduStochasticAdmissionReceiptV1;
pub use ndu_stochastic_admission::NduStochasticAdmissionRequestV1;
pub use ndu_stochastic_admission::admit_ndu_stochastic_candidate_v1;
pub use ndu_stochastic_admission::canonical_ndu_stochastic_solver_digest_v1;
pub use objective_run::ObjectiveRunBindingsV1;
pub use objective_run::ObjectiveRunError;
pub use objective_run::PublishedObjectiveRunV1;
pub use objective_run::compile_and_publish_objective_run_v1;

mod plasticity_product;

pub use plasticity_product::AnchoredPlasticityWriterErrorV1;
pub use plasticity_product::AnchoredPlasticityWriterV1;
pub use plasticity_product::CandidateEvaluationAdmissionV2;
pub use plasticity_product::ParameterPlasticityDispositionV1;
pub use plasticity_product::ParameterPlasticityProductErrorV1;
pub use plasticity_product::ParameterPlasticityProductReceiptV1;
pub use plasticity_product::ParameterPlasticityProductRequestV1;
pub use plasticity_product::PlasticityAdmissionEvidenceV1;
pub use plasticity_product::PlasticityAnchorCommitterV1;
pub use plasticity_product::PlasticityWriterStateV1;
pub use plasticity_product::no_change_disposition_signing_payload_v1;
pub use plasticity_product::plasticity_admission_signing_payload_v1;
pub use plasticity_product::propose_authenticated_parameter_plasticity_v1;

mod topology_canary_product;
mod topology_product;

pub use topology_canary_product::AuthenticatedStructuralCanaryErrorV1;
pub use topology_canary_product::AuthenticatedStructuralCanaryReceiptV1;
pub use topology_canary_product::observe_authenticated_structural_canary_v1;
pub use topology_canary_product::structural_canary_observation_signing_payload_v1;

pub use topology_product::TopologyAdmissionEvidenceV1;
pub use topology_product::TopologyPlasticityProductErrorV1;
pub use topology_product::TopologyPlasticityProductReceiptV1;
pub use topology_product::TopologyPlasticityProductRequestV1;
pub use topology_product::propose_authenticated_topology_plasticity_v1;
pub use topology_product::topology_admission_signing_payload_v1;
pub use topology_product::topology_evaluation_signing_payload_v1;
pub use topology_product::topology_generation_signing_payload_v1;

mod intuition_qualification;
mod intuition_qualification_v3;

pub use intuition_qualification::AuthenticatedIntuitionDecisionV1;
pub use intuition_qualification::AuthenticatedIntuitionDecisionV2;
pub use intuition_qualification::IntuitionQualificationError;
pub use intuition_qualification::IntuitionQualificationEvidenceV1;
pub use intuition_qualification::IntuitionQualificationEvidenceV2;
pub use intuition_qualification::QualifiedEvaluatedShadowError;
pub use intuition_qualification::QualifiedEvaluatedShadowReceiptV2;
pub use intuition_qualification::QualifiedEvaluatedShadowRequestV2;
pub use intuition_qualification::decide_authenticated_intuition_v1;
pub use intuition_qualification::decide_authenticated_intuition_v2;
pub use intuition_qualification::run_qualified_evaluated_shadow_v2;
pub use intuition_qualification_v3::AuthenticatedIntuitionDecisionV3;
pub use intuition_qualification_v3::decide_authenticated_intuition_v3;
pub use neuron_runtime::run_neuron_tick_v1;

mod capability_snapshot;

pub use capability_snapshot::CapabilityBindingV2;
pub use capability_snapshot::CapabilityNecessityV2;
pub use capability_snapshot::CapabilityRequirementV2;
pub use capability_snapshot::CapabilitySnapshotErrorV2;
pub use capability_snapshot::CapabilitySnapshotRequestV2;
pub use capability_snapshot::CapabilitySnapshotV2;

mod prompt_pipeline;

pub use prompt_pipeline::PreparedPromptContextV1;
pub use prompt_pipeline::PreparedPromptDeliveryV1;
pub use prompt_pipeline::PromptContextCompileRequestV1;
pub use prompt_pipeline::PromptDeliveryPrepareRequestV1;
pub use prompt_pipeline::PromptPayloadMaterializationV1;
pub use prompt_pipeline::PromptPipelineErrorV1;
pub use prompt_pipeline::PromptSerializationOccurrenceV1;
pub use prompt_pipeline::PromptSerializationProofV1;
pub use prompt_pipeline::compile_exercised_prompt_context_v1;
pub use prompt_pipeline::observe_prompt_delivery_v1;
pub use prompt_pipeline::prepare_prompt_delivery_v1;

mod pipeline_v2;
mod prompt_delivery;

pub use pipeline_v2::LaneFRunRequestV2;
pub use pipeline_v2::LaneFShadowPipelineReceiptV2;
pub use pipeline_v2::PipelineErrorV2;
pub use pipeline_v2::run_shadow_pipeline_v2;
pub use prompt_delivery::PromptRegistryCompilationErrorV2;
pub use prompt_delivery::PromptRegistryCompilationRequestV2;
pub use prompt_delivery::PromptRegistryCompiledContextV2;
pub use prompt_delivery::compile_prompt_registry_v2;

mod pipeline;

pub use pipeline::CoherentLaneFSnapshotV1;
pub use pipeline::LaneFBudgetV1;
pub use pipeline::LaneFRunRequestV1;
pub use pipeline::LaneFShadowPipelineReceiptV1;
pub use pipeline::LaneFShadowPortsV1;
pub use pipeline::LaneFStageV1;
pub use pipeline::PipelineDispositionV1;
pub use pipeline::PipelineErrorV1;
pub use pipeline::PortDecisionV1;
pub use pipeline::PortFailureClassV1;
pub use pipeline::PortFailureV1;
pub use pipeline::PortInputV1;
pub use pipeline::PortReceiptV1;
pub use pipeline::StageOutcomeV1;
pub use pipeline::StageTraceV1;
pub use pipeline::run_shadow_pipeline;

mod vertical;

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

pub use vertical::ReadOnlyUtilityContribution;
pub use vertical::ReadOnlyVerticalError;
pub use vertical::ReadOnlyVerticalReceipt;
pub use vertical::ReadOnlyVerticalRequest;
pub use vertical::run_read_only_vertical;

const MAX_CANDIDATES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanCandidate {
    pub candidate_id: StableId,
    pub legal: bool,
    pub hard_veto: bool,
    pub score: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanningRequest {
    pub plan_id: StableId,
    pub objective_digest: Digest32,
    pub context_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub candidates: Vec<PlanCandidate>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AbstentionReason {
    NoEligibleCandidate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlanDecision {
    Selected(StableId),
    Abstained(AbstentionReason),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligencePlanReceipt {
    pub plan_id: StableId,
    pub decision: PlanDecision,
    pub considered_candidates: Vec<StableId>,
    pub plan_digest: Digest32,
    pub effect_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    CandidateLimitExceeded,
    DuplicateCandidate(String),
    EmptySupport(String),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn compose(mut request: PlanningRequest) -> Result<IntelligencePlanReceipt, Error> {
    for (name, digest) in [
        ("objective", request.objective_digest),
        ("context", request.context_digest),
        ("snapshot", request.snapshot_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if request.candidates.len() > MAX_CANDIDATES {
        return Err(Error::CandidateLimitExceeded);
    }
    request
        .candidates
        .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    for candidate in &request.candidates {
        if !seen.insert(candidate.candidate_id.clone()) {
            return Err(Error::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.support_digest.is_zero() {
            return Err(Error::EmptySupport(candidate.candidate_id.to_string()));
        }
    }
    let selected = request
        .candidates
        .iter()
        .filter(|candidate| candidate.legal && !candidate.hard_veto)
        .max_by(|left, right| {
            left.score
                .cmp(&right.score)
                .then_with(|| right.candidate_id.cmp(&left.candidate_id))
        });
    let decision = selected.map_or(
        PlanDecision::Abstained(AbstentionReason::NoEligibleCandidate),
        |candidate| PlanDecision::Selected(candidate.candidate_id.clone()),
    );
    let considered_candidates = request
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intelligence.plan.v1");
    push_id(&mut bytes, &request.plan_id);
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.context_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.hard_veto));
        bytes.extend_from_slice(&candidate.score.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(IntelligencePlanReceipt {
        plan_id: request.plan_id,
        decision,
        considered_candidates,
        plan_digest: Digest32::of_bytes(&bytes),
        effect_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "vertical_tests.rs"]
mod vertical_tests;

#[cfg(test)]
#[path = "plasticity_product_tests.rs"]
mod plasticity_product_tests;
