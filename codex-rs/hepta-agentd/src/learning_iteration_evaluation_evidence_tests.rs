//! Same-UID mechanism fixtures exercise original framed readback only. Public
//! owner admission retains its separate UID/pidfd checks and Root qualification.

use std::io::ErrorKind;

use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::neuron_cell_evaluation::tests::learning::LearningFixture;
use crate::prepare_cell_learning_evaluation_v1;

#[path = "learning_iteration_evaluation_recovery_tests.rs"]
mod recovery;

fn request(
    fixture: &LearningFixture,
) -> CellLearningEvaluationReadbackRequestV1<'_, LockedFileFinalHoldoutCasStoreV1> {
    CellLearningEvaluationReadbackRequestV1 {
        runner: fixture.runner(),
        snapshot: &fixture.snapshot,
        evaluation: &fixture.receipt,
        qualification: &fixture.qualification,
        context: &fixture.context,
        evidence: &fixture.evidence,
        timing: ProductTimingEvidenceV1::Qualification,
        verifier: &fixture.verifier,
    }
}

fn original_owners(
    fixture: &LearningFixture,
    evaluated: LearningIterationReceiptV1,
) -> anyhow::Result<(Fixture, Fixture)> {
    let initial = LearningIterationCoordinatorV1::new(
        fixture.snapshot.request.clone(),
        fixture.snapshot.owners.clone(),
    )?
    .snapshot()
    .clone();
    let training = fixture
        .snapshot
        .receipts
        .last()
        .expect("original Training")
        .clone();
    Ok((
        Fixture {
            initial: initial.clone(),
            signature: fixture.stage_attestation(&training),
            receipt: training,
            verifier: fixture.verifier.clone(),
        },
        Fixture {
            initial,
            signature: fixture.stage_attestation(&evaluated),
            receipt: evaluated,
            verifier: fixture.verifier.clone(),
        },
    ))
}

fn serve(
    mut server: UnixStream,
    fixture: Fixture,
    snapshot_head: Digest32,
    requests: u64,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        let receipt_digest = Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(
            &fixture.receipt,
        )?);
        for request_id in 1..=requests {
            let request = read_request(&mut server)?;
            // Exact field equality also rules out a payload/signing command.
            assert_eq!(
                serde_json::to_value(&request)?,
                serde_json::json!({
                    "schema": 1,
                    "operation": wire::OPERATION,
                    "request_id": request_id,
                    "binding": fixture.initial.head_digest.to_string(),
                    "snapshot_head": snapshot_head.to_string(),
                    "operation_id": fixture.receipt.operation_id.to_string(),
                    "actor_id": fixture.receipt.actor_id.to_string(),
                    "predecessor": fixture.receipt.predecessor.to_string(),
                    "receipt_digest": receipt_digest.to_string(),
                })
            );
            reply(&mut server, &response(request, fixture.evidence()))?;
        }
        Ok(())
    })
}

#[tokio::test]
async fn current_signed_qualification_reads_original_stage_evidence_for_all_decisions()
-> anyhow::Result<()> {
    for disposition in [
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        IndependentEvaluationDispositionV1::Ineligible,
        IndependentEvaluationDispositionV1::InsufficientEvidence,
    ] {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        let fixture = LearningFixture::new_at(disposition, now);
        let prepared = prepare_cell_learning_evaluation_v1(
            fixture.runner(),
            &fixture.snapshot,
            &fixture.receipt,
            &fixture.qualification,
            &fixture.request(now),
        )?;
        let (training, evaluation) = original_owners(&fixture, prepared.clone())?;
        let expected = evaluation.signature.clone();
        let (trainer, trainer_server) = training.client()?;
        let (evaluator, evaluator_server) = evaluation.client()?;
        let head = fixture.snapshot.head_digest;
        let trainer_peer = serve(trainer_server, training, head, /*requests*/ 2);
        let evaluator_peer = serve(evaluator_server, evaluation, head, /*requests*/ 2);
        for _ in 0..2 {
            let authenticated =
                read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator).await?;
            assert_eq!(authenticated.receipt(), &prepared);
            assert_eq!(authenticated.attestation(), &expected);
            assert_eq!(
                authenticated.receipt().observed_unix_seconds,
                fixture.evidence.evaluator_bundle.issued_at
            );
            let after = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
            assert!((now..=after).contains(&authenticated.verified_at_unix_seconds()));
        }
        trainer_peer.join().expect("original trainer readback")?;
        evaluator_peer
            .join()
            .expect("original evaluator readback")?;
    }
    Ok(())
}

#[tokio::test]
async fn product_signature_cannot_replace_the_original_iteration_attestation() -> anyhow::Result<()>
{
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let fixture = LearningFixture::new_at(IndependentEvaluationDispositionV1::Ineligible, now);
    let prepared = prepare_cell_learning_evaluation_v1(
        fixture.runner(),
        &fixture.snapshot,
        &fixture.receipt,
        &fixture.qualification,
        &fixture.request(now),
    )?;
    let (training, mut evaluation) = original_owners(&fixture, prepared.clone())?;
    // This Product signature has just passed qualification revalidation, but
    // its payload belongs to a different domain from the iteration receipt.
    assert_ne!(
        evaluation.signature.payload_digest,
        fixture.evidence.evaluator_bundle.payload_digest
    );
    evaluation.signature = fixture.evidence.evaluator_bundle.clone();
    let (trainer, trainer_server) = training.client()?;
    let (evaluator, evaluator_server) = evaluation.client()?;
    let head = fixture.snapshot.head_digest;
    let trainer_peer = serve(trainer_server, training, head, /*requests*/ 1);
    let evaluator_peer = serve(evaluator_server, evaluation, head, /*requests*/ 1);
    assert!(matches!(
        read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator).await,
        Err(CellLearningEvaluationReadbackErrorV1::Evidence(
            Error::Evidence(SignedEvidenceError::PayloadMismatch)
        ))
    ));
    assert!(matches!(
        evaluator.readback(&fixture.snapshot, &prepared).await,
        Err(Error::OwnerUnavailable(_))
    ));
    trainer_peer.join().expect("original trainer readback")?;
    evaluator_peer
        .join()
        .expect("wrong-domain evaluator fixture")?;
    Ok(())
}

#[tokio::test]
async fn missing_original_trainer_refuses_no_update_before_contacting_evaluator()
-> anyhow::Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let fixture = LearningFixture::new_at(IndependentEvaluationDispositionV1::Ineligible, now);
    let prepared = prepare_cell_learning_evaluation_v1(
        fixture.runner(),
        &fixture.snapshot,
        &fixture.receipt,
        &fixture.qualification,
        &fixture.request(now),
    )?;
    let (training, evaluation) = original_owners(&fixture, prepared)?;
    let (trainer, trainer_server) = training.client()?;
    let (evaluator, mut evaluator_server) = evaluation.client()?;
    drop(trainer_server);
    evaluator_server.set_nonblocking(true)?;
    assert!(matches!(
        read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator).await,
        Err(CellLearningEvaluationReadbackErrorV1::Evidence(
            Error::OwnerUnavailable(_)
        ))
    ));
    assert_eq!(
        evaluator_server
            .read(&mut [0])
            .expect_err("no evaluator request")
            .kind(),
        ErrorKind::WouldBlock
    );
    Ok(())
}
