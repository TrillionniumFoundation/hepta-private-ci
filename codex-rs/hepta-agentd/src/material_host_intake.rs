//! Lossless public signed-data decoding and observation output. These DTOs do
//! not construct an opaque Source, admission, committed trace or Task receipt.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_ledger::{AuthenticatedOutcomeV1, CandidateSetCompletenessReceiptV1,
    OutcomeTerminalityV1, OutcomeWatermarkV1, ProductionDecisionV2, RunStartObjectiveDispositionV1};
use codex_hepta_types::{FixedQ32, ProbabilityQ32};
use serde::Deserialize;
use serde_json::{Value, json};
use crate::{AgentdError, CircuitTaskSourcePublicationV1, OriginalCircuitExperienceRequestV1};
use super::{config::{digest, id}, invalid, trust::{Evidence, Principal}};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignedExperience {
    expected_predecessor: String,
    decision: Decision,
    decision_evidence: Evidence,
    outcome: Outcome,
    outcome_evidence: Evidence,
}
impl SignedExperience {
    pub(super) fn original(self) -> Result<OriginalCircuitExperienceRequestV1, AgentdError> {
        Ok(OriginalCircuitExperienceRequestV1 { expected_predecessor: digest(&self.expected_predecessor)?,
            decision: self.decision.original()?, decision_evidence: self.decision_evidence.original()?,
            outcome: self.outcome.original()?, outcome_evidence: self.outcome_evidence.original()? })
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Decision {
    record_id: String, episode_id: String, run_snapshot_digest: String, objective_digest: String,
    policy_digest: String, candidate_ids: Vec<String>, selected_candidate_id: String,
    selected_propensity_raw: u64, completeness: Completeness, support_digest: String,
}
impl Decision {
    fn original(self) -> Result<ProductionDecisionV2, AgentdError> {
        if self.candidate_ids.is_empty() || self.candidate_ids.len() > 128 {
            return Err(invalid("original candidate completeness bound differs"));
        }
        Ok(ProductionDecisionV2 { record_id: id(&self.record_id)?, episode_id: id(&self.episode_id)?,
            run_snapshot_digest: digest(&self.run_snapshot_digest)?, objective_digest: digest(&self.objective_digest)?,
            policy_digest: digest(&self.policy_digest)?, candidate_ids: self.candidate_ids.iter().map(|s| id(s)).collect::<Result<_, _>>()?,
            selected_candidate_id: id(&self.selected_candidate_id)?, selected_propensity: ProbabilityQ32::from_raw(self.selected_propensity_raw).map_err(invalid)?,
            completeness: self.completeness.original()?, support_digest: digest(&self.support_digest)? })
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Completeness {
    set_id: String, state_digest: String, generator_id: String, generator_code_digest: String,
    grammar_digest: String, hard_filter_digest: String, truncation_digest: String, candidates_digest: String,
    candidate_count: u32, omitted_count_bound: u32, canonical_order_digest: String, complete_for_generator: bool,
}
impl Completeness {
    fn original(self) -> Result<CandidateSetCompletenessReceiptV1, AgentdError> {
        Ok(CandidateSetCompletenessReceiptV1 { set_id: id(&self.set_id)?, state_digest: digest(&self.state_digest)?,
            generator_id: id(&self.generator_id)?, generator_code_digest: digest(&self.generator_code_digest)?,
            grammar_digest: digest(&self.grammar_digest)?, hard_filter_digest: digest(&self.hard_filter_digest)?,
            truncation_digest: digest(&self.truncation_digest)?, candidates_digest: digest(&self.candidates_digest)?,
            candidate_count: self.candidate_count, omitted_count_bound: self.omitted_count_bound,
            canonical_order_digest: digest(&self.canonical_order_digest)?, complete_for_generator: self.complete_for_generator })
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Outcome {
    record_id: String, outcome_id: String, episode_id: String, observer: Principal,
    observed_at: Option<u64>, value_raw: Option<i64>, unit_profile_digest: String,
    support_digest: String, watermark: Watermark,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Watermark {
    latest_observable_at: u64, expected_delay_profile_digest: String, terminality: Terminality,
    censoring_reason: Option<String>, correction_predecessor: Option<String>, finalized_at: Option<u64>,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Terminality { Pending, Censored, Terminal }
impl Outcome {
    fn original(self) -> Result<AuthenticatedOutcomeV1, AgentdError> {
        let watermark = self.watermark;
        Ok(AuthenticatedOutcomeV1 { record_id: id(&self.record_id)?, outcome_id: id(&self.outcome_id)?,
            episode_id: id(&self.episode_id)?, observer: self.observer.original()?, observed_at: self.observed_at,
            value: self.value_raw.map(FixedQ32::from_raw), unit_profile_digest: digest(&self.unit_profile_digest)?,
            support_digest: digest(&self.support_digest)?, watermark: OutcomeWatermarkV1 {
                latest_observable_at: watermark.latest_observable_at,
                expected_delay_profile_digest: digest(&watermark.expected_delay_profile_digest)?,
                terminality: match watermark.terminality { Terminality::Pending => OutcomeTerminalityV1::Pending,
                    Terminality::Censored => OutcomeTerminalityV1::Censored, Terminality::Terminal => OutcomeTerminalityV1::Terminal },
                censoring_reason: watermark.censoring_reason.as_deref().map(id).transpose()?,
                correction_predecessor: watermark.correction_predecessor.as_deref().map(id).transpose()?, finalized_at: watermark.finalized_at,
            } })
    }
}

/// Complete original public record/input/output data for the real Generator.
/// This output has no decoder into Source custody and asserts no new authority.
pub(super) fn publication(value: &CircuitTaskSourcePublicationV1) -> Value {
    let record = value.original_record();
    let input = value.input();
    let auth = &record.authentication;
    let admission = &record.admission;
    let snapshot = &record.snapshot;
    json!({
        "run_start": {
            "authentication": { "issuer_id": auth.issuer_id.as_str(), "key_epoch": auth.key_epoch,
                "message_id": auth.message_id.as_str(), "sequence": auth.sequence, "expires_at_ms": auth.expires_at_ms,
                "scope_digest": auth.scope_digest.to_string(), "signed_body_digest": auth.signed_body_digest.to_string(),
                "signature": STANDARD_NO_PAD.encode(auth.signature) },
            "admission": { "profile_id": admission.profile_id.as_str(), "profile_revision": admission.profile_revision,
                "profile_digest": admission.profile_digest.to_string(), "supplied_source_digest": admission.supplied_source_digest.to_string(),
                "intent_digest": admission.intent_digest.to_string(), "admitted_source_digest": admission.admitted_source_digest.to_string(),
                "observed_at_unix_micros": admission.observed_at_unix_micros, "deadline_unix_micros": admission.deadline_unix_micros,
                "authority_wire_mask": admission.authority.flags().wire_mask() },
            "disposition": match record.disposition { RunStartObjectiveDispositionV1::Compiled => "compiled",
                RunStartObjectiveDispositionV1::ExplicitAbstain => "explicit_abstain" },
            "snapshot": { "run_id": snapshot.run_id.as_str(), "objective_digest": snapshot.objective_digest.to_string(),
                "hard_constraint_digest": snapshot.hard_constraint_digest.to_string(), "preference_state_digest": snapshot.preference_state_digest.to_string(),
                "model_tuple_digest": snapshot.model_tuple_digest.to_string(), "prompt_registry_digest": snapshot.prompt_registry_digest.to_string(),
                "artifact_set_digest": snapshot.artifact_set_digest.to_string(), "authority_epoch": snapshot.authority_epoch,
                "generation": snapshot.generation, "fence_digest": snapshot.fence_digest.to_string() },
            "runtime_body_digest": record.runtime_body_digest.to_string(), "objective_semantic_bytes": STANDARD_NO_PAD.encode(&record.objective_semantic_bytes),
            "objective_function_v1_digest": record.objective_function_v1_digest.to_string(),
            "objective_function_v1_bytes": STANDARD_NO_PAD.encode(&record.objective_function_v1_bytes),
        },
        "input": { "operation_id": input.operation_id.as_str(),
            "scope": { "agent_id": input.scope.agent_id.as_str(), "cell_id": input.scope.cell_id.as_str(),
                "run_id": input.scope.run_id.as_str(), "principal_digest": input.scope.principal_digest.to_string() },
            "source_frontier": input.source_frontier.to_string(), "objective_digest": input.objective_digest.to_string(),
            "ndu_snapshot_digest": input.ndu_snapshot_digest.to_string(), "monotonic_micros": input.monotonic_micros,
            "deadline_micros": input.deadline_micros, "observation": STANDARD_NO_PAD.encode(&input.observation),
            "candidates": input.candidates.iter().map(|c| json!({"candidate_id":c.candidate_id.as_str(),"allowed":c.allowed})).collect::<Vec<_>>() },
        "output": STANDARD_NO_PAD.encode(value.output()), "history_digest": value.history_digest().as_str(),
        "publication_digest": value.publication_digest().to_string(), "bundle_digest": value.bundle_digest().to_string(),
        "checkpoint_digest": value.checkpoint_digest().to_string(), "original_result_bytes": STANDARD_NO_PAD.encode(value.result_bytes()),
    })
}
