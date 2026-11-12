//! Explicit fixture keys/measurements; no production signer or adoption claim.

use super::*;
use crate::circuit_cell::tests::support::checked;
use crate::circuit_cell::tests::support::d;
use crate::circuit_cell::tests::support::id;
use crate::circuit_task::cell_q24_dataset_source_test_support as source;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_types::FixedQ32;
use pretty_assertions::assert_eq;

#[path = "circuit_credit_ledger_test_support.rs"]
mod ledger;

fn request(
    writer: &LedgerWriter,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<OriginalCircuitExperienceRequestV1> {
    let policy = publication.original_policy()?;
    let mut candidates = policy
        .entries()
        .iter()
        .map(|p| p.candidate_id.clone())
        .collect::<Vec<_>>();
    candidates.sort();
    let decision = ProductionDecisionV2 {
        record_id: publication.input().scope.run_id.clone(),
        episode_id: id("episode"),
        run_snapshot_digest: publication.input().ndu_snapshot_digest,
        objective_digest: publication.input().objective_digest,
        policy_digest: Digest32::of_bytes(publication.output()),
        candidate_ids: candidates.clone(),
        selected_candidate_id: policy.selected().clone(),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id("set"),
            state_digest: d("fixture-state"),
            generator_id: id("generator"),
            generator_code_digest: d("fixture-code"),
            grammar_digest: d("fixture-grammar"),
            hard_filter_digest: d("fixture-filter"),
            truncation_digest: d("fixture-truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: candidates.len() as u32,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: publication.publication_digest(),
    };
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: id("episode"),
        observer: ledger::trusted(LearningEvidenceRoleV1::Observer).principal,
        observed_at: Some(40),
        value: Some(FixedQ32::ONE),
        unit_profile_digest: d("fixture-measurement-units"),
        support_digest: publication.publication_digest(),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: d("fixture-delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    };
    Ok(OriginalCircuitExperienceRequestV1 {
        expected_predecessor: writer.snapshot()?.head_digest,
        decision_evidence: ledger::sign(
            writer,
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&decision)?,
        ),
        outcome_evidence: ledger::sign(
            writer,
            LearningEvidenceRoleV1::Observer,
            &outcome_signing_payload_v2(&outcome),
        ),
        decision,
        outcome,
    })
}

#[tokio::test]
async fn signed_pair_replays_without_adding_or_rewriting_original_bytes() -> anyhow::Result<()> {
    for revoke in [false, true] {
        let root = tempfile::tempdir()?;
        let mut fixture = ledger::LedgerFixture::with_unlearning_authority("experience-intake");
        let (_, bundle) = source::model(root.path())?;
        let identity = crate::circuit_task::source_test_support::identity(root.path())?;
        let run = circuit_learning_run_id_v1(&fixture.writer, &identity.agent_id, &id("episode"))?;
        let (identity, original) =
            source::completed(root.path(), &bundle, &run, &source::observation([0, 0])).await?;
        let source = original.readback();
        let request = request(
            &fixture.writer,
            &source.read_run_publication(&identity, &run)?,
        )?;
        let first =
            append_with_clock(&source, &identity, &mut fixture.writer, &request, || Ok(50))?;
        let snapshot = fixture.writer.read_current_durable_snapshot()?;
        let bytes = fixture.bytes();
        let replay =
            append_with_clock(&source, &identity, &mut fixture.writer, &request, || Ok(50))?;
        assert_eq!(replay.outcome.chain_digest, first.outcome.chain_digest);
        assert_eq!(fixture.writer.read_current_durable_snapshot()?, snapshot);
        assert_eq!(fixture.bytes(), bytes);
        assert_eq!(snapshot.records().len(), 2);
        if revoke {
            let plan = codex_hepta_learning_ledger::DatasetFreezePlanV2 {
                snapshot_id: id("revoked-outcome-dataset"),
                objective_digest: request.decision.objective_digest,
                inclusion_policy_digest: d("explicit-fixture-freeze"),
            };
            let evidence = ledger::sign(
                &fixture.writer,
                LearningEvidenceRoleV1::Evaluator,
                &codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2(&snapshot, &plan)?,
            );
            let dataset = fixture.writer.freeze_dataset(plan, &evidence, /*now*/ 50)?;
            let removal = codex_hepta_learning_ledger::UnlearningLineageRequestV1 {
                record_id: id("remove-only-outcome"),
                lineage_id: id("outcome-removal-lineage"),
                source_record_id: request.outcome.record_id.clone(),
                dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
                dataset_digest: dataset.snapshot.dataset_digest,
                artifact_id: id("explicit-derived-fixture-artifact"),
                reason_digest: d("withdrawn-fixture-measurement"),
            };
            let evidence = ledger::sign(
                &fixture.writer,
                LearningEvidenceRoleV1::UnlearningAuthority,
                &codex_hepta_learning_ledger::unlearning_signing_payload_v1(&removal),
            );
            fixture.writer.append_unlearning(
                snapshot.head_digest,
                removal,
                &dataset,
                &evidence,
                /*now*/ 50,
            )?;
            fixture.writer.verify_active_decision_binding(
                &request.decision.record_id,
                &request.decision.episode_id,
            )?;
        } else {
            let mut correction = request.outcome.clone();
            correction.record_id = id("corrected-outcome-record");
            correction.outcome_id = id("corrected-outcome");
            correction.watermark.correction_predecessor = Some(request.outcome.outcome_id.clone());
            correction.value = Some(FixedQ32::ZERO);
            let correction_evidence = ledger::sign(
                &fixture.writer,
                LearningEvidenceRoleV1::Observer,
                &outcome_signing_payload_v2(&correction),
            );
            fixture.writer.append_outcome(
                snapshot.head_digest,
                correction,
                &correction_evidence,
                /*now*/ 50,
            )?;
        }
        let corrected_bytes = fixture.bytes();
        assert!(
            append_with_clock(&source, &identity, &mut fixture.writer, &request, || Ok(50))
                .is_err()
        );
        assert_eq!(fixture.bytes(), corrected_bytes);
        original.withdraw_source(&run)?;
        assert!(
            append_with_clock(&source, &identity, &mut fixture.writer, &request, || Ok(50))
                .is_err()
        );
        assert_eq!(fixture.bytes(), corrected_bytes);
    }
    Ok(())
}

#[tokio::test]
async fn exact_request_continues_a_previously_committed_decision() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let mut fixture = ledger::LedgerFixture::new("experience-partial");
    let (_, bundle) = source::model(root.path())?;
    let identity = crate::circuit_task::source_test_support::identity(root.path())?;
    let run = circuit_learning_run_id_v1(&fixture.writer, &identity.agent_id, &id("episode"))?;
    let (identity, original) =
        source::completed(root.path(), &bundle, &run, &source::observation([0, 0])).await?;
    let source = original.readback();
    let request = request(
        &fixture.writer,
        &source.read_run_publication(&identity, &run)?,
    )?;
    fixture.writer.append_decision(
        request.expected_predecessor,
        request.decision.clone(),
        &request.decision_evidence,
        /*now*/ 50,
    )?;
    let before = fixture.writer.read_current_durable_snapshot()?;
    append_with_clock(&source, &identity, &mut fixture.writer, &request, || Ok(50))?;
    let after = fixture.writer.read_current_durable_snapshot()?;
    assert_eq!(&after.records()[..1], before.records());
    assert_eq!(after.records().len(), 2);
    Ok(())
}

#[tokio::test]
async fn untrusted_or_wrong_source_measurements_cannot_append_a_decision() -> anyhow::Result<()> {
    for mutation in 0..4 {
        let root = tempfile::tempdir()?;
        let mut fixture = ledger::LedgerFixture::new("experience-reject");
        let (_, bundle) = source::model(root.path())?;
        let identity = crate::circuit_task::source_test_support::identity(root.path())?;
        let run = circuit_learning_run_id_v1(&fixture.writer, &identity.agent_id, &id("episode"))?;
        let (identity, original) =
            source::completed(root.path(), &bundle, &run, &source::observation([0, 0])).await?;
        let source = original.readback();
        let mut request = request(
            &fixture.writer,
            &source.read_run_publication(&identity, &run)?,
        )?;
        match mutation {
            0 => request.outcome.value = Some(FixedQ32::ZERO), // No replacement Observer signature.
            1 => request.decision.support_digest = d("different-original-source"),
            2 => {
                request.outcome.observer =
                    ledger::trusted(LearningEvidenceRoleV1::Generator).principal
            }
            3 => request.outcome.watermark.finalized_at = Some(51),
            _ => unreachable!(),
        }
        if mutation != 0 {
            request.decision_evidence = ledger::sign(
                &fixture.writer,
                LearningEvidenceRoleV1::Generator,
                &decision_signing_payload_v2(&request.decision)?,
            );
            request.outcome_evidence = ledger::sign(
                &fixture.writer,
                LearningEvidenceRoleV1::Observer,
                &outcome_signing_payload_v2(&request.outcome),
            );
        }
        let before = fixture.bytes();
        assert!(
            append_with_clock(&source, &identity, &mut fixture.writer, &request, || Ok(50))
                .is_err()
        );
        assert_eq!(fixture.bytes(), before);
    }
    Ok(())
}

#[tokio::test]
async fn expiry_after_decision_keeps_partial_pair_unacknowledged_without_resigning()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let mut fixture = ledger::LedgerFixture::new("experience-expiry");
    let (_, bundle) = source::model(root.path())?;
    let identity = crate::circuit_task::source_test_support::identity(root.path())?;
    let run = circuit_learning_run_id_v1(&fixture.writer, &identity.agent_id, &id("episode"))?;
    let (identity, original) =
        source::completed(root.path(), &bundle, &run, &source::observation([0, 0])).await?;
    let source = original.readback();
    let request = request(
        &fixture.writer,
        &source.read_run_publication(&identity, &run)?,
    )?;
    let mut times = [50, 50, 91].into_iter();
    assert!(
        append_with_clock(&source, &identity, &mut fixture.writer, &request, || Ok(
            times.next().expect("bounded fixture clock")
        ))
        .is_err()
    );
    assert_eq!(fixture.writer.snapshot()?.records().len(), 1);
    let bytes = fixture.bytes();
    assert!(
        append_with_clock(&source, &identity, &mut fixture.writer, &request, || Ok(91)).is_err()
    );
    assert_eq!(fixture.bytes(), bytes);
    Ok(())
}
