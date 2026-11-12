//! Real B Source/Cell/ledger joins with explicit fixture signing custody.
//! Wrong Decision fields have valid original signatures, not edited journals.
//! Observer measurement references retain their independent signed semantics.

use super::*;
use codex_hepta_learning_ledger::LedgerEvent;
use material::evaluation_provider::DecisionBinding;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_b_refuses_validly_signed_decision_for_another_policy_or_publication()
-> anyhow::Result<()> {
    for fault in [
        DecisionBinding::WrongPolicy,
        DecisionBinding::WrongPublication,
    ] {
        let (original, mut b, retention, registration) = Box::pin(preregistered()).await?;
        Box::pin(b.populate_with_decision_binding(
            &original,
            ObservationMode::Complete,
            /*changed_candidate_action*/ false,
            fault,
        ))
        .await?;
        let config = b.config(&original, &registration)?;
        let owners = b.owners();
        // The Generator, independent Observer and Evaluator signatures are
        // accepted by the actual ledger. Only the Source join rejects them.
        let frozen = owners.ledger.freeze_dataset(
            config.freeze_plan.clone(),
            &config.freeze_evidence,
            b.at,
        )?;
        assert_eq!(frozen.snapshot.pending_outcomes, 0);
        assert_eq!(frozen.snapshot.censored_outcomes, 0);
        let before = b.all_source_bytes()?;
        assert!(
            matches!(
                CohortAt::read(owners, config, b.at),
                Err(OriginalCircuitEvaluationProviderErrorV1::Binding(
                    "exact original policy and independent terminal Outcome"
                ))
            ),
            "{fault:?}"
        );
        assert_eq!(b.all_source_bytes()?, before);
        drop(b);
        drop(retention);
        original.finish().await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_b_accepts_distinct_nonzero_observer_measurement_references() -> anyhow::Result<()>
{
    let (original, mut b, retention, registration) = Box::pin(preregistered()).await?;
    Box::pin(b.populate(
        &original,
        ObservationMode::Complete,
        /*changed_candidate_action*/ false,
    ))
    .await?;
    let config = b.config(&original, &registration)?;
    let owners = b.owners();
    let records = owners.ledger.records()?;
    let mut measurements = std::collections::BTreeSet::new();
    for record in &records {
        let LedgerEvent::AuthenticatedOutcomeV2(outcome) = &record.event else {
            continue;
        };
        let decision = records
            .iter()
            .find_map(|record| match &record.event {
                LedgerEvent::AuthenticatedDecisionV2(decision)
                    if decision.episode_id == outcome.episode_id =>
                {
                    Some(decision)
                }
                _ => None,
            })
            .expect("same-episode original Decision");
        let source = owners
            .sources
            .iter()
            .find(|source| source.run_id == decision.record_id)
            .expect("same original B Source");
        let publication = source
            .source
            .read_run_publication(&source.identity, &source.run_id)?;
        assert_eq!(
            decision.policy_digest,
            Digest32::of_bytes(publication.output())
        );
        assert_eq!(decision.support_digest, publication.publication_digest());
        assert_eq!(
            decision.run_snapshot_digest,
            publication.input().ndu_snapshot_digest
        );
        assert!(!outcome.support_digest.is_zero());
        assert_ne!(outcome.support_digest, publication.publication_digest());
        measurements.insert(outcome.support_digest);
    }
    assert_eq!(
        measurements.len(),
        b.rule.history.len() + b.rule.targets.len()
    );
    let before = b.all_source_bytes()?;
    let mut cohort = CohortAt::read(owners, config, b.at)?;
    let manifest = cohort.original.observed_manifest_digest()?;
    let bytes = cohort.bytes()?;
    assert_eq!(cohort.current()?, manifest);
    assert_eq!(cohort.bytes()?, bytes);
    assert_eq!(b.all_source_bytes()?, before);
    drop(cohort);
    drop(b);
    drop(retention);
    original.finish().await
}
