//! Explicit fixture signing custody for independent original B outcomes.
//! Values below are test measurements declared before inference; no model
//! output or successful completion is converted into a reward.
use super::*;
use pretty_assertions::assert_eq;

/// Faults are signed before the original ledger append; no retained row or
/// signature is edited. They exercise the B consumer's own Source join.
#[derive(Clone, Copy, Debug)]
pub(in super::super) enum DecisionBinding {
    ExactSource,
    WrongPolicy,
    WrongPublication,
}

pub(in super::super) fn decision(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    episode: &StableId,
    publication: &crate::CircuitTaskSourcePublicationV1,
    at: u64,
    binding: DecisionBinding,
) -> anyhow::Result<()> {
    let input = publication.input();
    let policy = publication.original_policy()?;
    let mut candidates = policy
        .entries()
        .iter()
        .map(|entry| entry.candidate_id.clone())
        .collect::<Vec<_>>();
    candidates.sort();
    let mut value = ProductionDecisionV2 {
        record_id: input.scope.run_id.clone(),
        episode_id: episode.clone(),
        run_snapshot_digest: input.ndu_snapshot_digest,
        objective_digest: input.objective_digest,
        policy_digest: Digest32::of_bytes(publication.output()),
        candidate_ids: candidates.clone(),
        selected_candidate_id: policy.selected().clone(),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id(&format!("B-actions:{episode}")),
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
        support_digest: publication.publication_digest(),
    };
    match binding {
        DecisionBinding::ExactSource => {}
        DecisionBinding::WrongPolicy => {
            value.policy_digest = d("validly-signed-unrelated-B-policy");
            assert_ne!(
                value.policy_digest,
                Digest32::of_bytes(publication.output())
            );
        }
        DecisionBinding::WrongPublication => {
            value.support_digest = d("validly-signed-unrelated-B-publication");
            assert_ne!(value.support_digest, publication.publication_digest());
        }
    }
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
