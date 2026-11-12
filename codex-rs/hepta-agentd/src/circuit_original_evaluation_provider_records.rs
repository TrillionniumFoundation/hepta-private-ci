//! Exact joins of the current authenticated ledger and original task policies.
//! Rewards come only from independent terminal Outcome facts. The original
//! temporal evaluator fits its outcome model from the earlier history below.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_intelligence_eval::ClusterAssignment;
use codex_hepta_intelligence_eval::HeldOutTarget;
use codex_hepta_intelligence_eval::OpeAction;
use codex_hepta_intelligence_eval::OpeRow;
use codex_hepta_intelligence_eval::OutcomeTrainingSample;
use codex_hepta_intelligence_eval::TemporalComparisonInputsV1;
use codex_hepta_learning_ledger::AuthenticatedDecisionRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use super::Error;
use super::OriginalCircuitEvaluationCohortConfigV1;
use super::OriginalCircuitEvaluationEpisodeV1;
use super::OriginalCircuitEvaluationSourceV1;
use super::Publications;
use crate::CircuitTaskSourcePublicationV1;
use crate::circuit_learning_run_id_v1;
use crate::circuit_task::CircuitTaskPolicyProjectionV1;

struct Episode<'a> {
    decision: &'a AuthenticatedDecisionRecordV2,
    outcome: &'a AuthenticatedOutcomeRecordV2,
    evidence: Digest32,
    source: &'a CircuitTaskSourcePublicationV1,
    policy: CircuitTaskPolicyProjectionV1,
    value: FixedQ32,
    observed_at: u64,
    admitted_at: u64,
    principal: StableId,
    lineage: StableId,
}

pub(super) fn assemble(
    config: &OriginalCircuitEvaluationCohortConfigV1,
    ledger: &LedgerWriter,
    dataset: &DatasetSnapshotReceiptV3,
    records: &[LedgerRecord],
    publications: &Publications,
    sources: &[OriginalCircuitEvaluationSourceV1],
    training_binding: &super::binding::CandidateBinding,
    current: u64,
) -> Result<TemporalComparisonInputsV1, Error> {
    let rule = &config.rule;
    let expected: BTreeSet<_> = rule
        .history
        .iter()
        .map(|row| row.episode_id.clone())
        .chain(
            rule.targets
                .iter()
                .map(|row| row.episode.episode_id.clone()),
        )
        .collect();
    let mut decisions = BTreeMap::new();
    let mut outcomes = BTreeMap::new();
    let mut credits = BTreeMap::new();
    for record in records {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => {
                if decisions.insert(value.episode_id.clone(), value).is_some() {
                    return Err(Error::Binding("one active original Decision per episode"));
                }
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                if outcomes
                    .insert(value.episode_id.clone(), (value, record.event_digest))
                    .is_some()
                {
                    return Err(Error::Binding("one active original Outcome per episode"));
                }
            }
            LedgerEvent::CreditBatchV2(value) => {
                if credits.insert(value.episode_id.clone(), value).is_some() {
                    return Err(Error::Binding("one original terminal credit lineage"));
                }
            }
            _ => {
                return Err(Error::Binding(
                    "authenticated Decision, Outcome and optional credit only",
                ));
            }
        }
    }
    if decisions.keys().cloned().collect::<BTreeSet<_>>() != expected
        || outcomes.keys().cloned().collect::<BTreeSet<_>>() != expected
    {
        return Err(Error::Binding(
            "all preregistered historical and held-out episodes",
        ));
    }
    for (episode, credit) in credits {
        let (outcome, _) = outcomes
            .get(&episode)
            .ok_or(Error::Binding("credit episode"))?;
        if credit.outcome_id != outcome.outcome_id
            || Some(credit.terminal_outcome) != outcome.value
            || credit.authentication_digest.is_zero()
        {
            return Err(Error::Binding(
                "credit belongs to the same original Outcome",
            ));
        }
    }

    let mut training = Vec::with_capacity(rule.history.len());
    for requested in &rule.history {
        let row = Episode::read_episode(
            config,
            ledger,
            requested,
            &decisions,
            &outcomes,
            publications,
            sources,
            training_binding,
            current,
        )?;
        if row.admitted_at < rule.history_start_unix_seconds
            || row.admitted_at > rule.candidate_plan.fold.training_watermark
            || row.observed_at > rule.candidate_plan.fold.training_watermark
            || row
                .outcome
                .finalized_at
                .is_none_or(|at| at > rule.candidate_plan.fold.training_watermark)
        {
            return Err(Error::Binding("actual earlier historical outcome window"));
        }
        training.push(OutcomeTrainingSample {
            decision_id: row.decision.record_id.clone(),
            principal_lineage: row.principal,
            episode_lineage: row.lineage,
            window_id: rule.history_window_id.clone(),
            action_id: row.decision.selected_candidate_id.clone(),
            outcome: row.value,
            observed_at: row.observed_at,
            evidence_digest: row.evidence,
        });
    }

    let mut targets = Vec::with_capacity(rule.targets.len());
    let mut candidate_observations = Vec::with_capacity(rule.targets.len());
    let mut baseline_observations = Vec::with_capacity(rule.targets.len());
    let mut assignments = Vec::with_capacity(rule.targets.len());
    for requested in &rule.targets {
        let row = Episode::read_episode(
            config,
            ledger,
            &requested.episode,
            &decisions,
            &outcomes,
            publications,
            sources,
            training_binding,
            current,
        )?;
        if row.admitted_at < rule.candidate_plan.fold.evaluation_start
            || row.observed_at > rule.evaluation_end_unix_seconds
            || row
                .outcome
                .finalized_at
                .is_none_or(|at| at > rule.evaluation_end_unix_seconds)
            || row.source.bundle_digest() != training_binding.baseline
        {
            return Err(Error::Binding(
                "actual held-out baseline and observation window",
            ));
        }
        let candidate = publications
            .get(&requested.candidate_run_id)
            .ok_or(Error::Binding("actual candidate task"))?;
        let baseline = publications
            .get(&requested.baseline_run_id)
            .ok_or(Error::Binding("actual baseline task"))?;
        require_arm(config, &row, candidate, training_binding.candidate)?;
        require_arm(config, &row, baseline, training_binding.baseline)?;
        if candidate.input().operation_id == baseline.input().operation_id {
            return Err(Error::Binding("two distinct original arm executions"));
        }
        let candidate_policy = CircuitTaskSourcePublicationV1::original_policy(candidate)?;
        let baseline_policy = CircuitTaskSourcePublicationV1::original_policy(baseline)?;
        candidate_observations.push(observation(&row, &candidate_policy)?);
        baseline_observations.push(observation(&row, &baseline_policy)?);
        targets.push(HeldOutTarget {
            decision_id: row.decision.record_id.clone(),
            principal_lineage: row.principal.clone(),
            episode_lineage: row.lineage,
            window_id: rule.holdout_window_id.clone(),
            // This is the original authenticated admission lower bound, not
            // an invented completion time or the unrelated Cell clock.
            decision_at: row.admitted_at,
            actions: row.decision.candidate_ids.clone(),
        });
        assignments.push(ClusterAssignment {
            decision_id: row.decision.record_id.clone(),
            // Repeated observations of one actual principal remain dependent.
            // Neither a row index nor an operation ID can split this cluster.
            cluster_id: row.principal,
        });
    }
    Ok(TemporalComparisonInputsV1 {
        training,
        targets,
        candidate_observations,
        baseline_observations,
        assignments,
        snapshot_ids: vec![dataset.snapshot.snapshot_id.clone()],
        future_window_ids: vec![rule.holdout_window_id.clone()],
    })
}

impl<'a> Episode<'a> {
    fn read_episode(
        config: &OriginalCircuitEvaluationCohortConfigV1,
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
        // Ledger candidates are a canonical set; the signed Source policy
        // retains its original action order and is never reordered here.
        let mut canonical_candidates = policy
            .entries()
            .iter()
            .map(|entry| entry.candidate_id.clone())
            .collect::<Vec<_>>();
        canonical_candidates.sort();
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
            || decision.policy_digest != Digest32::of_bytes(source.output())
            || decision.support_digest != source.publication_digest()
            || decision.selected_candidate_id != *policy.selected()
            || decision.selected_propensity != ProbabilityQ32::ONE
            || decision.candidate_ids != canonical_candidates
            || decision.candidate_completeness_digest.is_zero()
            || decision.authentication_digest.is_zero()
            || decision.support_digest.is_zero()
            || outcome.authentication_digest.is_zero()
            // The Observer signs its own measurement evidence. The episode
            // joins that event to the source-bound Decision; its support need
            // not equal the Source publication or use any particular encoding.
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
        let principal = StableId::new(format!("principal:{}", input.scope.principal_digest))
            .map_err(|_| Error::Binding("original principal lineage"))?;
        let lineage = StableId::new(format!(
            "episode:{}",
            Digest32::of_parts(&[
                b"hepta.circuit.original-evaluation-episode.v1\0",
                ledger.binding_digest().as_array(),
                requested.episode_id.as_str().as_bytes(),
            ])
        ))
        .map_err(|_| Error::Binding("original episode lineage"))?;
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

fn require_arm(
    config: &OriginalCircuitEvaluationCohortConfigV1,
    behavior: &Episode<'_>,
    arm: &CircuitTaskSourcePublicationV1,
    bundle: Digest32,
) -> Result<(), Error> {
    let left = behavior.source.input();
    let right = arm.input();
    let admitted_at = arm
        .original_record()
        .admission
        .observed_at_unix_micros
        .div_ceil(1_000_000);
    if arm.bundle_digest() != bundle
        || left.scope.principal_digest != right.scope.principal_digest
        || left.observation != right.observation
        || left.source_frontier != right.source_frontier
        || left.ndu_snapshot_digest != right.ndu_snapshot_digest
        || left.objective_digest != right.objective_digest
        || left.candidates != right.candidates
        || behavior.source.original_record().objective_semantic_bytes
            != arm.original_record().objective_semantic_bytes
        || behavior
            .source
            .original_record()
            .objective_function_v1_bytes
            != arm.original_record().objective_function_v1_bytes
        || admitted_at < config.rule.candidate_plan.fold.evaluation_start
        || admitted_at > config.rule.evaluation_end_unix_seconds
    {
        return Err(Error::Binding(
            "same held-out input and actual original arm bundle",
        ));
    }
    Ok(())
}

fn observation(
    row: &Episode<'_>,
    evaluation: &CircuitTaskPolicyProjectionV1,
) -> Result<OpeRow, Error> {
    if row.policy.entries().len() != evaluation.entries().len() {
        return Err(Error::Binding("complete policy comparison"));
    }
    let mut actions = Vec::with_capacity(row.policy.entries().len());
    for (behavior, evaluated) in row.policy.entries().iter().zip(evaluation.entries()) {
        if behavior.candidate_id != evaluated.candidate_id || behavior.allowed != evaluated.allowed
        {
            return Err(Error::Binding("same complete original action support"));
        }
        actions.push(OpeAction {
            action_id: behavior.candidate_id.clone(),
            behavior_probability: probability(behavior.probability_ppm)?,
            evaluation_probability: probability(evaluated.probability_ppm)?,
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
