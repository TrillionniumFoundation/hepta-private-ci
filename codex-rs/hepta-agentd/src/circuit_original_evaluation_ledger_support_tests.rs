//! Explicit fixture signing custody for independent original B outcomes.
//! Values below are test measurements declared before inference; no model
//! output or successful completion is converted into a reward.
use super::*;
use pretty_assertions::assert_eq;

pub(in super::super) fn decision(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    episode: &StableId,
    input: &crate::CircuitTaskSourceInputV1,
    selected_index: usize,
    at: u64,
) -> anyhow::Result<()> {
    let candidates = input
        .candidates
        .iter()
        .map(|mask| mask.candidate_id.clone())
        .collect::<Vec<_>>();
    let selected = candidates
        .get(selected_index)
        .ok_or_else(|| anyhow::anyhow!("selected action"))?
        .clone();
    let value = ProductionDecisionV2 {
        record_id: input.scope.run_id.clone(),
        episode_id: episode.clone(),
        run_snapshot_digest: input.ndu_snapshot_digest,
        objective_digest: input.objective_digest,
        policy_digest: d("explicit-original-B-policy-contract"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: selected,
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id(&format!("B-actions:{}", episode)),
            state_digest: d("explicit-original-B-decision-state"),
            generator_id: credentials.generator.principal.principal_id.clone(),
            generator_code_digest: d("explicit-original-B-generator"),
            grammar_digest: d("explicit-original-B-grammar"),
            hard_filter_digest: d("explicit-original-B-filter"),
            truncation_digest: d("explicit-original-B-truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: candidates.len().try_into()?,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: d("explicit-original-B-decision-support"),
    };
    let evidence = sign(
        writer.verifier(),
        &credentials.generator,
        /*seed*/ 41,
        &decision_signing_payload_v2(&value)?,
        at,
    );
    writer.append_decision(writer.snapshot()?.head_digest, value, &evidence, at)?;
    assert_eq!(
        writer
            .records()?
            .last()
            .expect("actual Decision")
            .event
            .record_id(),
        &input.scope.run_id
    );
    Ok(())
}

pub(in super::super) fn outcome(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    episode: &StableId,
    at: u64,
    value: FixedQ32,
    unit: Digest32,
    delay: Digest32,
) -> anyhow::Result<()> {
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id(&format!("B-outcome-record:{episode}")),
        outcome_id: id(&format!("B-outcome:{episode}")),
        episode_id: episode.clone(),
        observer: credentials.observer.principal.clone(),
        observed_at: Some(at),
        value: Some(value),
        unit_profile_digest: unit,
        support_digest: d(&format!("explicit-independent-B-measurement:{episode}")),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: at,
            expected_delay_profile_digest: delay,
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(at),
        },
    };
    let evidence = sign(
        writer.verifier(),
        &credentials.observer,
        /*seed*/ 43,
        &outcome_signing_payload_v2(&outcome),
        at,
    );
    writer.append_outcome(writer.snapshot()?.head_digest, outcome, &evidence, at)?;
    Ok(())
}

pub(in super::super) fn freeze(
    writer: &LedgerWriter,
    credentials: &Credentials,
    plan: &DatasetFreezePlanV2,
    at: u64,
) -> anyhow::Result<SignedLearningEvidenceV1> {
    Ok(sign(
        writer.verifier(),
        &credentials.evaluator,
        /*seed*/ 42,
        &dataset_freeze_signing_payload_v2(&writer.snapshot()?, plan)?,
        at,
    ))
}
