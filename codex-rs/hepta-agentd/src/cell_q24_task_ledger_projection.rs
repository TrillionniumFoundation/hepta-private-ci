//! Shared data projections of the actual original task and signed facts.
//! These functions grant no writer, signing or historical learning authority.

use super::*;
use crate::CircuitTaskSourceInputV1;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::ProbabilityQ32;

pub(super) fn configuration_digest(
    config: &OriginalCellQ24TaskLedgerConfigV1,
    task: Digest32,
    ledger_binding: Digest32,
    trust_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.agentd.original-q24-task-ledger.v1\0".to_vec();
    for digest in [
        task,
        ledger_binding,
        trust_digest,
        config.generator_code_digest,
        config.grammar_digest,
        config.hard_filter_digest,
        config.truncation_digest,
        config.unit_profile_digest,
        config.expected_delay_profile_digest,
    ] {
        if digest.is_zero() {
            return Err(Error::Binding("nonzero original task ledger profile"));
        }
        bytes.extend_from_slice(digest.as_array());
    }
    for id in [
        identity.agent_id.as_str(),
        config.episode_id.as_str(),
        config.candidate_set_id.as_str(),
        config.outcome_record_id.as_str(),
        config.outcome_id.as_str(),
        config.generator.principal.principal_id.as_str(),
        config.observer.principal.principal_id.as_str(),
    ] {
        bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(id.as_bytes());
    }
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&config.generator.verifying_key);
    bytes.extend_from_slice(&config.observer.verifying_key);
    bytes.extend_from_slice(&config.claim_deadline_unix_seconds.to_be_bytes());
    bytes.extend_from_slice(&config.maximum_signature_lifetime_seconds.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) fn decision(
    config: &OriginalCellQ24TaskLedgerConfigV1,
    definition: &CellDefinitionV1,
    source: &CircuitTaskSourceInputV1,
    publication: &CircuitTaskSourcePublicationV1,
    original: &CellDecisionReceiptV1,
) -> Result<ProductionDecisionV2, Error> {
    let mut candidates = original
        .policy
        .iter()
        .map(|entry| entry.candidate_id.clone())
        .collect::<Vec<_>>();
    candidates.sort();
    let mut declared = definition
        .candidates
        .iter()
        .map(|entry| entry.candidate_id.clone())
        .collect::<Vec<_>>();
    declared.sort();
    if candidates != declared
        || publication.input().scope != source.scope
        || publication.input().objective_digest != source.objective_digest
        || publication.bundle_digest() != definition.bundle_digest
        || original.policy.iter().any(|entry| {
            entry.probability_ppm
                != if entry.candidate_id == original.selected_candidate {
                    1_000_000
                } else {
                    0
                }
        })
        || !original
            .policy
            .iter()
            .any(|entry| entry.candidate_id == original.selected_candidate && entry.allowed)
    {
        return Err(Error::Binding("complete original finite Cell decision"));
    }
    let request = ProductionDecisionV2 {
        record_id: publication.input().scope.run_id.clone(),
        episode_id: config.episode_id.clone(),
        run_snapshot_digest: crate::cell_q24_dataset_run_snapshot_digest_v1(publication),
        objective_digest: publication.input().objective_digest,
        policy_digest: Digest32::of_bytes(publication.output()),
        selected_candidate_id: original.selected_candidate.clone(),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: config.candidate_set_id.clone(),
            state_digest: original.semantic_request_digest,
            generator_id: config.generator.principal.principal_id.clone(),
            generator_code_digest: config.generator_code_digest,
            grammar_digest: config.grammar_digest,
            hard_filter_digest: config.hard_filter_digest,
            truncation_digest: config.truncation_digest,
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: u32::try_from(candidates.len())
                .map_err(|_| Error::Binding("candidate count"))?,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        candidate_ids: candidates,
        support_digest: publication.publication_digest(),
    };
    if decision_signing_payload_v2(&request)?.len() > 16_384 {
        return Err(Error::Binding("bounded original Decision signature"));
    }
    Ok(request)
}

pub(super) fn require_outcome(
    config: &OriginalCellQ24TaskLedgerConfigV1,
    publication: &CircuitTaskSourcePublicationV1,
    outcome: &AuthenticatedOutcomeV1,
) -> Result<(), Error> {
    if outcome.record_id != config.outcome_record_id
        || outcome.outcome_id != config.outcome_id
        || outcome.episode_id != config.episode_id
        || outcome.observer != config.observer.principal
        || outcome.support_digest != publication.publication_digest()
        || outcome.unit_profile_digest != config.unit_profile_digest
        || outcome.watermark.expected_delay_profile_digest != config.expected_delay_profile_digest
        || outcome.watermark.terminality != OutcomeTerminalityV1::Terminal
        || outcome.watermark.censoring_reason.is_some()
        || outcome.watermark.correction_predecessor.is_some()
        || outcome.observed_at.is_none()
        || outcome.watermark.finalized_at.is_none()
        || outcome
            .value
            .is_none_or(|value| !(-(8_i64 << 32)..=(8_i64 << 32)).contains(&value.raw()))
    {
        return Err(Error::Binding(
            "original independent Terminal business observation",
        ));
    }
    Ok(())
}

pub(super) fn outcome_event(
    outcome: &AuthenticatedOutcomeV1,
    signed: &SignedLearningEvidenceV1,
    observer: &TrustedLearningSignerV1,
) -> LedgerEvent {
    LedgerEvent::AuthenticatedOutcomeV2(AuthenticatedOutcomeRecordV2 {
        record_id: outcome.record_id.clone(),
        outcome_id: outcome.outcome_id.clone(),
        episode_id: outcome.episode_id.clone(),
        observer_id: observer.principal.principal_id.clone(),
        observer_controller_id: observer.controller_id.clone(),
        observer_credential_chain_digest: observer.principal.credential_chain_digest,
        observer_signing_key_digest: observer.principal.signing_key_digest,
        observer_scope_digest: observer.principal.scope_digest,
        observer_authority_epoch: observer.principal.authority_epoch,
        observed_at: outcome.observed_at,
        value: outcome.value,
        unit_profile_digest: outcome.unit_profile_digest,
        support_digest: outcome.support_digest,
        latest_observable_at: outcome.watermark.latest_observable_at,
        expected_delay_profile_digest: outcome.watermark.expected_delay_profile_digest,
        terminality: match outcome.watermark.terminality {
            OutcomeTerminalityV1::Pending => AuthenticatedOutcomeTerminality::Pending,
            OutcomeTerminalityV1::Censored => AuthenticatedOutcomeTerminality::Censored,
            OutcomeTerminalityV1::Terminal => AuthenticatedOutcomeTerminality::Terminal,
        },
        censoring_reason: outcome.watermark.censoring_reason.clone(),
        correction_predecessor: outcome.watermark.correction_predecessor.clone(),
        finalized_at: outcome.watermark.finalized_at,
        authentication_digest: binding::authentication_digest(signed),
    })
}
