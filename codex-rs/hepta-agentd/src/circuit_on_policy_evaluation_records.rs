//! Two real original arms, one frozen pair mapping and one cohort consume.
//! Every outcome remains attached to its own independently authenticated
//! Decision/Source. There is no cross-arm label copy or propensity adjustment.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use codex_hepta_intelligence_eval::ClusterAssignment;
use codex_hepta_intelligence_eval::HeldOutTarget;
use codex_hepta_intelligence_eval::OnPolicyArmProvenanceV1;
use codex_hepta_intelligence_eval::OnPolicyEvaluationArmInputsV1;
use codex_hepta_intelligence_eval::OnPolicyPairContractV1;
use codex_hepta_intelligence_eval::OnPolicyPairingContractV1;
use codex_hepta_intelligence_eval::OnPolicyTemporalComparisonInputsV1;
use codex_hepta_intelligence_eval::OutcomeTrainingSample;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use super::Error;
use super::OriginalCircuitOnPolicyCohortConfigV1;
use super::Publications;
use super::episode::Episode;
use crate::OriginalCircuitEvaluationSourceV1;

pub(super) fn assemble(
    config: &OriginalCircuitOnPolicyCohortConfigV1,
    ledger: &LedgerWriter,
    dataset: &DatasetSnapshotReceiptV3,
    records: &[LedgerRecord],
    publications: &Publications,
    sources: &[OriginalCircuitEvaluationSourceV1],
    training_binding: &super::binding::CandidateBinding,
    pairing: &OnPolicyPairingContractV1,
    current: u64,
) -> Result<OnPolicyTemporalComparisonInputsV1, Error> {
    let rule = &config.rule;
    let expected: BTreeSet<_> = rule.history.iter().map(|row| row.episode.episode_id.clone())
        .chain(rule.pairs.iter().flat_map(|row| [
            row.candidate.episode_id.clone(), row.baseline.episode_id.clone(),
        ])).collect();
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
            config, ledger, &requested.episode, &decisions, &outcomes,
            publications, sources, training_binding, current,
        )?;
        if row.admitted_at < rule.history_start_unix_seconds
            || row.admitted_at > rule.candidate_plan.fold.training_watermark
            || row.observed_at > rule.candidate_plan.fold.training_watermark
            || row.outcome.finalized_at.is_none_or(|at| at > rule.candidate_plan.fold.training_watermark)
            || row.source.bundle_digest() != training_binding.baseline
        {
            return Err(Error::Binding("actual earlier original baseline history window"));
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
    let empty_arm = || OnPolicyEvaluationArmInputsV1 {
        targets: Vec::with_capacity(rule.pairs.len()),
        observations: Vec::with_capacity(rule.pairs.len()),
        assignments: Vec::with_capacity(rule.pairs.len()),
        provenance: Vec::with_capacity(rule.pairs.len()),
    };
    let mut candidate = empty_arm();
    let mut baseline = empty_arm();
    for requested in &rule.pairs {
        let pair = pairing.pairs.iter().find(|pair| pair.pair_id == requested.pair_id)
            .ok_or(Error::Binding("exact frozen original pair identity"))?;
        let left = Episode::read_episode(
            config, ledger, &requested.candidate, &decisions, &outcomes,
            publications, sources, training_binding, current,
        )?;
        let right = Episode::read_episode(
            config, ledger, &requested.baseline, &decisions, &outcomes,
            publications, sources, training_binding, current,
        )?;
        if left.decision.record_id == right.decision.record_id
            || left.outcome.outcome_id == right.outcome.outcome_id
            || left.evidence == right.evidence
            || left.source.input().operation_id == right.source.input().operation_id
            || left.source.publication_digest() == right.source.publication_digest()
            || left.source.history_digest() == right.source.history_digest()
            || left.principal != right.principal
            || left.source.bundle_digest() != training_binding.candidate
            || right.source.bundle_digest() != training_binding.baseline
        {
            return Err(Error::Binding("independent original arm executions, Outcomes and model bindings"));
        }
        append_arm(&mut candidate, &left, pair, &rule.holdout_window_id,
            rule.candidate_plan.fold.evaluation_start, rule.evaluation_end_unix_seconds)?;
        append_arm(&mut baseline, &right, pair, &rule.holdout_window_id,
            rule.candidate_plan.fold.evaluation_start, rule.evaluation_end_unix_seconds)?;
    }
    Ok(OnPolicyTemporalComparisonInputsV1 {
        training, candidate, baseline,
        snapshot_ids: vec![dataset.snapshot.snapshot_id.clone()],
        future_window_ids: vec![rule.holdout_window_id.clone()],
    })
}

fn append_arm(
    arm: &mut OnPolicyEvaluationArmInputsV1,
    row: &Episode<'_>,
    pair: &OnPolicyPairContractV1,
    window: &StableId,
    evaluation_start: u64,
    evaluation_end: u64,
) -> Result<(), Error> {
    if row.admitted_at < evaluation_start
        || row.observed_at > evaluation_end
        || row.outcome.finalized_at.is_none_or(|at| at > evaluation_end)
        || !row.policy.checkpoint_before().is_zero()
    {
        return Err(Error::Binding("actual held-out on-policy run window and FreshEmpty state"));
    }
    arm.observations.push(super::episode::observation(row)?);
    arm.targets.push(HeldOutTarget {
        decision_id: row.decision.record_id.clone(),
        principal_lineage: row.principal.clone(),
        episode_lineage: row.lineage.clone(),
        window_id: window.clone(),
        decision_at: row.admitted_at,
        actions: row.decision.candidate_ids.clone(),
    });
    arm.assignments.push(ClusterAssignment {
        decision_id: row.decision.record_id.clone(),
        cluster_id: row.principal.clone(),
    });
    arm.provenance.push(OnPolicyArmProvenanceV1 {
        decision_id: row.decision.record_id.clone(),
        episode_lineage: row.lineage.clone(),
        behavior_run_id: row.source.input().scope.run_id.clone(),
        model_digest: row.source.bundle_digest(),
        input_digest: pair.input_digest,
        protocol_digest: pair.protocol_digest,
        checkpoint_before: row.policy.checkpoint_before(),
        source_evidence_digest: row.source.publication_digest(),
        execution_evidence_digest: history_digest(row.source.history_digest())?,
    });
    Ok(())
}


fn history_digest(value: &codex_hepta_contracts::Sha256Digest) -> Result<Digest32, Error> {
    let digest = value.as_str().parse::<Digest32>()
        .map_err(|_| Error::Binding("canonical original Circuit execution digest"))?;
    if digest.is_zero() {
        return Err(Error::Binding("nonzero actual Circuit execution history"));
    }
    Ok(digest)
}
