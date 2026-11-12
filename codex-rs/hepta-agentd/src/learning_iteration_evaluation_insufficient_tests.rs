//! Evidence-poor evaluations must not acquire a successful learning receipt.
//! These synthetic cohorts exercise real signatures, original journal files,
//! cold reopen and framed reads. They are not independent learning benefits.

use std::io::Read;
use std::time::Duration;

use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::CellLearningEvaluationErrorV1;

#[tokio::test]
async fn insufficient_evaluation_never_claims_a_receipt_before_or_after_cold_reopen()
-> anyhow::Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut fixture = LearningFixture::new_at(
        IndependentEvaluationDispositionV1::InsufficientEvidence,
        now,
    );
    let config = receipt_config(&fixture)?;
    let path = tempfile::tempdir()?;
    let mut owner = OriginalCellEvaluationReceiptOwnerV1::create(
        receipt_file(&path.path().join("owner"))?,
        receipt_witness(path.path(), &config)?,
        config.clone(),
        SigningKey::from_bytes(&[42; 32]),
    )?;
    let original = [
        std::fs::read(path.path().join("owner"))?,
        std::fs::read(path.path().join("witness"))?,
    ];
    let original_trainer =
        trainer_fixture(&fixture, config.training.receipts.last().expect("Training"))?;
    let (client, mut server) = original_trainer.client()?;
    server.set_nonblocking(true)?;
    for reopened in [false, true] {
        if reopened {
            drop(owner);
            owner = OriginalCellEvaluationReceiptOwnerV1::recover(
                receipt_file(&path.path().join("owner"))?,
                receipt_witness(path.path(), &config)?,
                config.clone(),
                SigningKey::from_bytes(&[42; 32]),
            )?;
        }
        assert!(matches!(
            owner.read_original_execution(fixture.receipt_owner_sources(&client)),
            Err(OriginalCellEvaluationReceiptErrorV1::Preparation(
                CellLearningEvaluationErrorV1::InsufficientEvidence
            ))
        ));
        let result = tokio::time::timeout(
            Duration::from_secs(3),
            owner.attest_original_completion(fixture.receipt_owner_sources(&client)),
        )
        .await?;
        assert!(matches!(
            result,
            Err(OriginalCellEvaluationReceiptErrorV1::Preparation(
                CellLearningEvaluationErrorV1::InsufficientEvidence
            ))
        ));
        assert!(matches!(
            owner.readback(fixture.receipt_owner_sources(&client)).await,
            Err(OriginalCellEvaluationReceiptErrorV1::Preparation(
                CellLearningEvaluationErrorV1::InsufficientEvidence
            ))
        ));
        assert_eq!(
            [
                std::fs::read(path.path().join("owner"))?,
                std::fs::read(path.path().join("witness"))?,
            ],
            original
        );
        assert_eq!(
            server
                .read(&mut [0])
                .expect_err("no Trainer request")
                .kind(),
            ErrorKind::WouldBlock
        );
        assert_eq!(fixture.snapshot, config.training);
        assert_eq!(
            LearningIterationCoordinatorV1::from_snapshot(fixture.snapshot.clone())?.next_stage(),
            Some(LearningIterationStageV1::Evaluation)
        );
    }
    Ok(())
}

#[tokio::test]
async fn insufficient_qualification_refuses_legacy_no_update_histories_before_owner_io()
-> anyhow::Result<()> {
    let current = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    for original_at in [current, current - 400] {
        let mut fixture = LearningFixture::new_at(
            IndependentEvaluationDispositionV1::InsufficientEvidence,
            original_at,
        );
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(fixture.snapshot.clone())?;
        // Reproduce the old adapter's incorrect mapping as regression data.
        // The cohort and signatures are synthetic; suffixes only exercise
        // structurally valid recovery cuts and do not prove actual C use.
        let candidate_bundle = coordinator
            .candidate()
            .expect("trained candidate")
            .digest()?;
        let legacy = LearningIterationReceiptV1 {
            operation_id: fixture.snapshot.request.operation_id.clone(),
            predecessor: fixture.snapshot.head_digest,
            actor_id: fixture.snapshot.owners.evaluator.clone(),
            evidence_digest: fixture.qualification.product().evidence_digest,
            observed_unix_seconds: fixture.evidence.evaluator_bundle.issued_at,
            observation: LearningIterationObservationV1::Evaluation {
                candidate_bundle,
                evaluation_profile: fixture.snapshot.request.evaluation_profile,
                disposition: LearningEvaluationDispositionV1::NoUpdate,
            },
        };
        let (training, evaluation) = original_owners(&fixture, legacy.clone())?;
        // A correct key and a valid signature cannot repair the wrong decision.
        fixture.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &evaluation.signature,
            &learning_iteration_receipt_signing_bytes_v1(&legacy)?,
            current,
        )?;
        let mut histories = vec![coordinator.snapshot().clone()];
        coordinator.record(legacy.clone(), legacy.observed_unix_seconds)?;
        histories.push(coordinator.snapshot().clone());
        let retained_bundle = coordinator
            .next_task_bundle()
            .expect("legacy retained bundle")
            .digest()?;
        let selection_digest = Digest32::of_bytes(b"legacy-selection-fixture");
        let iteration_request = &fixture.snapshot.request;
        let partition = CellStatePartitionV1 {
            principal_id: iteration_request.principal_id.clone(),
            agent_id: iteration_request.agent_id.clone(),
            cell_id: iteration_request.cell_id.clone(),
            run_id: StableId::new("legacy-distinct-next-task-fixture")?,
        };
        for observation in [
            LearningIterationObservationV1::Selection {
                candidate_bundle: retained_bundle,
                selection_digest,
            },
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle,
                state_partition: partition,
                checkpoint_digest: Digest32::of_bytes(b"legacy-checkpoint-fixture"),
                selection_digest,
                committed_step_receipt: Digest32::of_bytes(b"legacy-step-fixture"),
                task_owner_publication: Digest32::of_bytes(b"legacy-task-publication-fixture"),
            },
        ] {
            let snapshot = coordinator.snapshot();
            coordinator.record(
                LearningIterationReceiptV1 {
                    operation_id: snapshot.request.operation_id.clone(),
                    predecessor: snapshot.head_digest,
                    actor_id: snapshot.owners.owner(observation.stage()).clone(),
                    evidence_digest: Digest32::of_bytes(b"legacy-recovery-suffix-fixture"),
                    observed_unix_seconds: original_at,
                    observation,
                },
                original_at,
            )?;
            histories.push(coordinator.snapshot().clone());
        }
        let (trainer, mut trainer_server) = training.client()?;
        let (evaluator, mut evaluator_server) = evaluation.client()?;
        trainer_server.set_nonblocking(true)?;
        evaluator_server.set_nonblocking(true)?;
        for history in histories {
            LearningIterationCoordinatorV1::from_snapshot(history.clone())?;
            fixture.snapshot = history.clone();
            let result = tokio::time::timeout(
                Duration::from_secs(3),
                read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator),
            )
            .await?;
            assert!(matches!(
                result,
                Err(CellLearningEvaluationReadbackErrorV1::Preparation(
                    CellLearningEvaluationErrorV1::InsufficientEvidence
                ))
            ));
            assert_eq!(fixture.snapshot, history);
            for server in [&mut trainer_server, &mut evaluator_server] {
                assert_eq!(
                    server.read(&mut [0]).expect_err("no owner request").kind(),
                    ErrorKind::WouldBlock
                );
            }
        }
    }
    Ok(())
}
