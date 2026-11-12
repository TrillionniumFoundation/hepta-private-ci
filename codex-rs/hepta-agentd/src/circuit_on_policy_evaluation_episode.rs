//! Original per-episode authentication. Each on-policy arm has its own actual
//! Decision, independent terminal Outcome and Source publication. No labels,
//! propensities, clocks or initial checkpoints are synthesized by this reader.

use std::collections::BTreeMap;
use codex_hepta_intelligence_eval::OpeAction;
use codex_hepta_intelligence_eval::OpeRow;
use codex_hepta_learning_ledger::AuthenticatedDecisionRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use super::Error;
use super::OriginalCircuitOnPolicyCohortConfigV1;
use super::Publications;
use crate::OriginalCircuitEvaluationEpisodeV1;
use crate::OriginalCircuitEvaluationSourceV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::circuit_learning_run_id_v1;
use crate::circuit_task::CircuitTaskPolicyProjectionV1;

pub(super) struct Episode<'a> {
    pub(super) decision: &'a AuthenticatedDecisionRecordV2,
    pub(super) outcome: &'a AuthenticatedOutcomeRecordV2,
    pub(super) evidence: Digest32,
    pub(super) source: &'a CircuitTaskSourcePublicationV1,
    pub(super) policy: CircuitTaskPolicyProjectionV1,
    pub(super) value: FixedQ32,
    pub(super) observed_at: u64,
    pub(super) admitted_at: u64,
    pub(super) principal: StableId,
    pub(super) lineage: StableId,
}

impl<'a> Episode<'a> {
    pub(super) fn read_episode(
        config: &OriginalCircuitOnPolicyCohortConfigV1,
        ledger: &LedgerWriter,
        requested: &OriginalCircuitEvaluationEpisodeV1,
        decisions: &BTreeMap<StableId, &'a AuthenticatedDecisionRecordV2>,
        outcomes: &BTreeMap<StableId, (&'a AuthenticatedOutcomeRecordV2, Digest32)>,
        publications: &'a Publications,
        sources: &[OriginalCircuitEvaluationSourceV1],
        training: &super::binding::CandidateBinding,
        current: u64,
    ) -> Result<Episode<'a>, Error> {
        let decision = *decisions
            .get(&requested.episode_id)
            .ok_or(Error::Binding("original Decision"))?;
        let (outcome, evidence) = *outcomes
            .get(&requested.episode_id)
            .ok_or(Error::Binding("original Outcome"))?;
        let source = publications
            .get(&requested.behavior_run_id)
            .ok_or(Error::Binding("original behavior task"))?;
        let owner = sources
            .iter()
            .find(|owner| owner.run_id == requested.behavior_run_id)
            .ok_or(Error::Binding("original source identity"))?;
        let original_run =
            circuit_learning_run_id_v1(ledger, &owner.identity.agent_id, &requested.episode_id)
                .map_err(|_| Error::Binding("original ledger-bound execution identity"))?;
        let policy = CircuitTaskSourcePublicationV1::original_policy(source)?;
        let input = source.input();
        let admitted_at = source
            .original_record()
            .admission
            .observed_at_unix_micros
            .div_ceil(1_000_000);
        let observed_at = outcome
            .observed_at
            .ok_or(Error::Binding("missing observed outcome time"))?;
        let finalized_at = outcome
            .finalized_at
            .ok_or(Error::Binding("missing finalized outcome time"))?;
        let value = outcome
            .value
            .ok_or(Error::Binding("missing independently observed value"))?;
        if original_run != requested.behavior_run_id
            || decision.record_id != requested.behavior_run_id
            || input.scope.run_id != requested.behavior_run_id
            || source.original_record().snapshot.run_id != requested.behavior_run_id
            || source.original_record().snapshot.objective_digest != config.rule.objective_digest
            || input.objective_digest != config.rule.objective_digest
            || decision.objective_digest != config.rule.objective_digest
            || decision.run_snapshot_digest != input.ndu_snapshot_digest
            || !CircuitTaskPolicyProjectionV1::checkpoint_before(&policy).is_zero()
            || decision.selected_candidate_id != *policy.selected()
            || decision.selected_propensity != ProbabilityQ32::ONE
            || decision.candidate_ids
                != policy
                    .entries()
                    .iter()
                    .map(|entry| entry.candidate_id.clone())
                    .collect::<Vec<_>>()
            || decision.candidate_completeness_digest.is_zero()
            || decision.authentication_digest.is_zero()
            || decision.support_digest.is_zero()
            || outcome.authentication_digest.is_zero()
            || outcome.support_digest.is_zero()
            || outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
            || outcome.censoring_reason.is_some()
            || outcome.unit_profile_digest != config.rule.unit_profile_digest
            || outcome.expected_delay_profile_digest != config.rule.expected_delay_profile_digest
            || training.generator.principal().principal_id == outcome.observer_id
            || training.generator.controller_id() == &outcome.observer_controller_id
            || training.generator.principal().credential_chain_digest
                == outcome.observer_credential_chain_digest
            || training.generator.principal().signing_key_digest
                == outcome.observer_signing_key_digest
            || decision.generator_id == outcome.observer_id
            || decision.generator_controller_id == outcome.observer_controller_id
            || decision.generator_credential_chain_digest
                == outcome.observer_credential_chain_digest
            || decision.generator_signing_key_digest == outcome.observer_signing_key_digest
            || admitted_at == 0
            || admitted_at > observed_at
            || observed_at > outcome.latest_observable_at
            || outcome.latest_observable_at > finalized_at
            || finalized_at > current
            || !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&value)
        {
            return Err(Error::Binding(
                "exact original policy and independent terminal Outcome",
            ));
        }
        let expected = config.rule.source_input(&requested.behavior_run_id)?;
        if input.scope != expected.scope
            || input.source_frontier != expected.source_frontier
            || input.objective_digest != expected.objective_digest
            || input.ndu_snapshot_digest != expected.ndu_snapshot_digest
            || input.monotonic_micros != expected.monotonic_micros
            || input.deadline_micros != expected.deadline_micros
            || input.observation != expected.observation
            || input.candidates != expected.candidates
        {
            return Err(Error::Binding("every original arm input field equals its preregistration"));
        }
        config.rule.protocol.require_publication(source)?;
        let principal = StableId::new(format!("principal:{}", input.scope.principal_digest))
            .map_err(|_| Error::Binding("original principal lineage"))?;
        let lineage = super::binding::episode_lineage(ledger, &requested.episode_id)?;
        Ok(Episode {
            decision,
            outcome,
            evidence,
            source,
            policy,
            value,
            observed_at,
            admitted_at,
            principal,
            lineage,
        })
    }
}

pub(super) fn observation(
    row: &Episode<'_>,
) -> Result<OpeRow, Error> {
    let mut actions = Vec::with_capacity(row.policy.entries().len());
    for behavior in row.policy.entries() {
        actions.push(OpeAction {
            action_id: behavior.candidate_id.clone(),
            behavior_probability: probability(behavior.probability_ppm)?,
            evaluation_probability: probability(behavior.probability_ppm)?,
            // The original temporal evaluator discards and rebuilds this field
            // from historical Outcomes. It is not a predicted reward or label.
            predicted_outcome: FixedQ32::ZERO,
        });
    }
    Ok(OpeRow {
        decision_id: row.decision.record_id.clone(),
        chosen_action: row.decision.selected_candidate_id.clone(),
        complete_candidates: true,
        actions,
        finalized_outcome: Some(row.value),
        outcome_observed_at: row.observed_at,
        outcome_evidence: row.evidence,
        // Rebuilt by evaluate_temporal_holdout, never accepted as input proof.
        outcome_model_evidence: Digest32::ZERO,
    })
}

fn probability(ppm: u32) -> Result<ProbabilityQ32, Error> {
    match ppm {
        0 => Ok(ProbabilityQ32::ZERO),
        1_000_000 => Ok(ProbabilityQ32::ONE),
        _ => Err(Error::Binding("original deterministic policy profile")),
    }
}
