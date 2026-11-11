//! Real native/receipt owner readback with explicit credential and Dataset fixtures.
//! Later history is structural fixture data, not authenticated B/C, product
//! adoption, Root CURRENT custody or a whole-process cold-recovery claim.

use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellQ24TrainingReadbackErrorV1 as ReadError;
use crate::OriginalCellQ24TrainingStageErrorV1 as StageError;
use crate::OriginalCellQ24TrainingStageV1 as Stage;
use crate::read_cell_q24_training_snapshot_v1 as read;

fn retained(f: &ReceiptFixture) -> anyhow::Result<[Vec<u8>; 4]> {
    Ok([
        fs::read(f.root.path().join("job"))?,
        fs::read(f.root.path().join("witness"))?,
        fs::read(f.root.path().join("receipts"))?,
        fs::read(f.root.path().join("receipt-witness"))?,
    ])
}

fn append(
    coordinator: &mut LearningIterationCoordinatorV1,
    observation: LearningIterationObservationV1,
    observed_unix_seconds: u64,
) -> anyhow::Result<()> {
    let snapshot = coordinator.snapshot();
    coordinator.record(
        LearningIterationReceiptV1 {
            operation_id: snapshot.request.operation_id.clone(),
            predecessor: snapshot.head_digest,
            actor_id: snapshot.owners.owner(observation.stage()).clone(),
            evidence_digest: d("structural-training-readback-suffix"),
            observed_unix_seconds,
            observation,
        },
        observed_unix_seconds,
    )?;
    Ok(())
}

fn histories(
    dataset: &LearningIterationSnapshotV1,
    training: &LearningIterationReceiptV1,
) -> anyhow::Result<Vec<LearningIterationSnapshotV1>> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(dataset.clone())?;
    coordinator.record(training.clone(), training.observed_unix_seconds)?;
    let mut cuts = vec![dataset.clone(), coordinator.snapshot().clone()];
    let now = training.observed_unix_seconds;
    let updated = coordinator.next_stage() == Some(LearningIterationStageV1::Evaluation);
    if updated {
        let candidate_bundle = coordinator
            .candidate()
            .expect("native candidate")
            .digest()?;
        append(
            &mut coordinator,
            LearningIterationObservationV1::Evaluation {
                candidate_bundle,
                evaluation_profile: dataset.request.evaluation_profile,
                disposition: LearningEvaluationDispositionV1::Qualified,
            },
            now,
        )?;
        append(
            &mut coordinator,
            LearningIterationObservationV1::Proposal {
                candidate_bundle,
                proposal_id: dataset.request.operation_id.clone(),
                composition_digest: d("structural-model-proposal"),
                disposition: LearningProposalDispositionV1::UpdateCandidates,
            },
            now,
        )?;
    }
    let bundle = coordinator
        .next_task_bundle()
        .expect("decision bundle")
        .digest()?;
    let selection_digest = d("structural-selection");
    append(
        &mut coordinator,
        LearningIterationObservationV1::Selection {
            candidate_bundle: bundle,
            selection_digest,
        },
        now,
    )?;
    let state_partition = CellStatePartitionV1 {
        principal_id: dataset.request.principal_id.clone(),
        agent_id: dataset.request.agent_id.clone(),
        cell_id: dataset.request.cell_id.clone(),
        run_id: StableId::new("structural-distinct-task")?,
    };
    let checkpoint_digest = d("structural-checkpoint");
    let committed_step_receipt = d("structural-step");
    let next = if updated {
        LearningIterationObservationV1::NextUse {
            candidate_bundle: bundle,
            state_partition,
            checkpoint_digest,
            selection_digest,
            committed_step_receipt,
            state_cutover_receipt: d("structural-cutover"),
        }
    } else {
        LearningIterationObservationV1::RetainedModelNextUse {
            retained_bundle: bundle,
            state_partition,
            checkpoint_digest,
            selection_digest,
            committed_step_receipt,
            task_owner_publication: d("structural-task-publication"),
        }
    };
    append(&mut coordinator, next, now)?;
    assert_eq!(coordinator.next_stage(), None);
    cuts.push(coordinator.snapshot().clone());
    Ok(cuts)
}

fn rebuild(snapshot: LearningIterationSnapshotV1) -> anyhow::Result<LearningIterationSnapshotV1> {
    let mut coordinator = LearningIterationCoordinatorV1::new(snapshot.request, snapshot.owners)?;
    for mut receipt in snapshot.receipts {
        receipt.predecessor = coordinator.snapshot().head_digest;
        receipt.actor_id = coordinator
            .snapshot()
            .owners
            .owner(receipt.observation.stage())
            .clone();
        let observed = receipt.observed_unix_seconds;
        coordinator.record(receipt, observed)?;
    }
    Ok(coordinator.snapshot().clone())
}

#[tokio::test]
async fn original_training_snapshot_reads_both_outcomes_and_lost_ack_exactly() -> anyhow::Result<()>
{
    for target in [2 * Q, Q] {
        let f = ReceiptFixture::new(target)?;
        let stage = Stage::from_original_owners(f.create_training()?, f.create_receipts()?).await?;
        let original = stage
            .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(false)))
            .await?;
        let cuts = histories(&f.config.dataset, &original.receipt)?;
        let saved = retained(&f)?;
        for cut in &cuts {
            let completed = read(&stage, cut, &original.receipt).await?;
            assert_eq!(
                result_identity(&completed.outcome)?,
                result_identity(&original.outcome)?
            );
            assert_eq!(
                (&completed.receipt, &completed.attestation),
                (&original.receipt, &original.attestation)
            );
            assert_eq!(retained(&f)?, saved);
        }
        drop(stage);
        let stage =
            Stage::from_original_owners(f.recover_training()?, f.recover_receipts()?).await?;
        let completed = read(
            &stage,
            cuts.last().expect("complete structure"),
            &original.receipt,
        )
        .await?;
        assert_eq!(
            result_identity(&completed.outcome)?,
            result_identity(&original.outcome)?
        );
        assert_eq!(
            (completed.receipt, completed.attestation),
            (original.receipt, original.attestation)
        );
        assert_eq!(retained(&f)?, saved);
    }
    Ok(())
}

#[tokio::test]
async fn original_training_snapshot_refuses_rebuilt_replacement_and_invalid_cuts()
-> anyhow::Result<()> {
    for target in [2 * Q, Q] {
        let f = ReceiptFixture::new(target)?;
        let stage = Stage::from_original_owners(f.create_training()?, f.create_receipts()?).await?;
        let original = stage
            .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(false)))
            .await?;
        let full = histories(&f.config.dataset, &original.receipt)?
            .pop()
            .expect("full structure");
        let saved = retained(&f)?;
        for change_time in [false, true] {
            let mut changed = full.clone();
            if change_time {
                for receipt in changed.receipts.iter_mut().skip(2) {
                    receipt.observed_unix_seconds += 1;
                }
            } else {
                changed.receipts[2].evidence_digest = d("replaced-training");
            }
            let changed = rebuild(changed)?;
            LearningIterationCoordinatorV1::from_snapshot(changed.clone())?;
            for expected in [&original.receipt, &changed.receipts[2]] {
                assert!(matches!(
                    read(&stage, &changed, expected).await,
                    Err(ReadError::Binding(_))
                ));
            }
        }
        let empty = LearningIterationCoordinatorV1::new(full.request.clone(), full.owners.clone())?;
        assert!(matches!(
            read(&stage, empty.snapshot(), &original.receipt).await,
            Err(ReadError::Binding(_))
        ));
        for scenario in 0..3 {
            let mut invalid = full.clone();
            match scenario {
                0 => invalid.head_digest = d("wrong-head"),
                1 => invalid.receipts.last_mut().expect("suffix").predecessor = Digest32::ZERO,
                2 => invalid.receipts.swap(0, 1),
                _ => unreachable!(),
            }
            assert!(matches!(
                read(&stage, &invalid, &original.receipt).await,
                Err(ReadError::Iteration(_))
            ));
        }
        for change_owner in [false, true] {
            let mut foreign = f.config.dataset.clone();
            if change_owner {
                foreign.owners.dataset = StableId::new("foreign-dataset-owner")?;
            } else {
                foreign.request.source_run_id = StableId::new("foreign-source-run")?;
            }
            let foreign = rebuild(foreign)?;
            let mut expected = original.receipt.clone();
            expected.predecessor = foreign.head_digest;
            assert!(matches!(
                read(&stage, &foreign, &expected).await,
                Err(ReadError::Stage(StageError::Binding(_)))
            ));
        }
        for expected in [&full.receipts[0], full.receipts.last().expect("next use")] {
            assert!(matches!(
                read(&stage, &full, expected).await,
                Err(ReadError::Binding(_))
            ));
        }
        assert_eq!(retained(&f)?, saved);
    }
    Ok(())
}

#[tokio::test]
async fn original_training_snapshot_missing_and_pending_never_start_work() -> anyhow::Result<()> {
    let original = ReceiptFixture::new(2 * Q)?;
    let original_stage =
        Stage::from_original_owners(original.create_training()?, original.create_receipts()?)
            .await?;
    let completed = original_stage
        .execute_training(&original.config.dataset, Arc::new(AtomicBool::new(false)))
        .await?;
    for scenario in 0..3 {
        let mut f = ReceiptFixture::new(2 * Q)?;
        f.config = original.config.clone();
        let mut training = f.create_training()?;
        match scenario {
            0 => {}
            1 => assert!(matches!(
                training.fit_or_readback(&AtomicBool::new(true)),
                Err(OwnerError::Training(CellQ24TrainingErrorV1::Cancelled))
            )),
            2 => {
                training.fit_or_readback(&AtomicBool::new(false))?;
            }
            _ => unreachable!(),
        }
        let stage = Stage::from_original_owners(training, f.create_receipts()?).await?;
        let saved = retained(&f)?;
        let error = read(&stage, &f.config.dataset, &completed.receipt)
            .await
            .err()
            .expect("original missing or pending");
        match scenario {
            0 => assert!(matches!(
                error,
                ReadError::Stage(StageError::Receipt(ReceiptError::Training(
                    OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)
                )))
            )),
            1 => assert!(matches!(
                error,
                ReadError::Stage(StageError::Receipt(ReceiptError::Training(
                    OwnerError::Pending
                )))
            )),
            2 => assert!(matches!(
                error,
                ReadError::Stage(StageError::Receipt(ReceiptError::Owner(
                    LearningOriginalOwnerErrorV1::Store(
                        ProductEvaluationExecutionStoreErrorV1::Missing
                    )
                )))
            )),
            _ => unreachable!(),
        }
        assert_eq!(retained(&f)?, saved);
    }
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    training.fit_or_readback(&AtomicBool::new(false))?;
    let mut receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
        opened(f.root.path(), "receipts")?,
        FaultWitness {
            inner: f.receipt_witness()?,
            sequence: 2,
            fault: LostAck::AfterWrite,
        },
        f.config.clone(),
        SigningKey::from_bytes(&[79; 32]),
    )?;
    assert!(matches!(
        receipts.attest_original_completion(&mut training),
        Err(ReceiptError::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    drop(receipts);
    let saved = retained(&f)?;
    assert!(matches!(
        Stage::from_original_owners(training, f.recover_receipts()?).await,
        Err(StageError::Receipt(ReceiptError::Owner(
            LearningOriginalOwnerErrorV1::Pending
        )))
    ));
    assert_eq!(retained(&f)?, saved);
    Ok(())
}

#[tokio::test]
async fn original_training_snapshot_keeps_original_deadline_and_signature_expiry()
-> anyhow::Result<()> {
    let mut f = ReceiptFixture::new(Q)?;
    let deadline = clock()? + 5;
    let mut prefix = f.config.dataset.clone();
    prefix.request.envelope.expiry_unix_seconds = deadline;
    f.config = signing_config(&prefix, &f.data, f.rule)?;
    let stage = Stage::from_original_owners(f.create_training()?, f.create_receipts()?).await?;
    let original = stage
        .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(false)))
        .await?;
    let cuts = histories(&f.config.dataset, &original.receipt)?;
    let saved = retained(&f)?;
    tokio::time::sleep(Duration::from_secs(deadline.saturating_sub(clock()?) + 1)).await;
    assert!(clock()? >= deadline && clock()? < original.attestation.expires_at);
    for cut in cuts {
        let reread = read(&stage, &cut, &original.receipt).await?;
        assert_eq!(
            (&reread.receipt, &reread.attestation),
            (&original.receipt, &original.attestation)
        );
    }
    assert_eq!(retained(&f)?, saved);

    let mut f = ReceiptFixture::new(2 * Q)?;
    f.config.maximum_signature_lifetime_seconds = 2;
    let stage = Stage::from_original_owners(f.create_training()?, f.create_receipts()?).await?;
    let original = stage
        .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(false)))
        .await?;
    let full = histories(&f.config.dataset, &original.receipt)?
        .pop()
        .expect("full structure");
    let saved = retained(&f)?;
    tokio::time::sleep(Duration::from_secs(
        original.attestation.expires_at.saturating_sub(clock()?) + 1,
    ))
    .await;
    assert!(clock()? > original.attestation.expires_at);
    assert!(matches!(
        read(&stage, &full, &original.receipt).await,
        Err(ReadError::Stage(StageError::Receipt(
            ReceiptError::Evidence(SignedEvidenceError::ValidityWindow)
        )))
    ));
    assert_eq!(retained(&f)?, saved);
    Ok(())
}

struct ChangedCurrent {
    inner: FileAnchorWitnessStore,
    changed: Arc<AtomicBool>,
}

impl AnchorWitnessStore for ChangedCurrent {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        let current = self.inner.current()?;
        Ok(current.map(|mut anchor| {
            if self.changed.load(Ordering::SeqCst) {
                anchor.checkpoint_digest = d("changed-independent-current");
            }
            anchor
        }))
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)
    }
}

#[tokio::test]
async fn original_training_snapshot_rechecks_both_original_current_witnesses() -> anyhow::Result<()>
{
    for change_training in [false, true] {
        let f = ReceiptFixture::new(2 * Q)?;
        let training_changed = Arc::new(AtomicBool::new(false));
        let receipt_changed = Arc::new(AtomicBool::new(false));
        let training = CellQ24TrainingOwnerV1::create(
            opened(f.root.path(), "job")?,
            ChangedCurrent {
                inner: witness(f.root.path())?,
                changed: Arc::clone(&training_changed),
            },
            original_plan(Arc::clone(&f.baseline), &f.config.dataset, &f.data, f.rule)?,
            f.data.clone(),
            f.rule,
        )?;
        let receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
            opened(f.root.path(), "receipts")?,
            ChangedCurrent {
                inner: f.receipt_witness()?,
                changed: Arc::clone(&receipt_changed),
            },
            f.config.clone(),
            SigningKey::from_bytes(&[79; 32]),
        )?;
        let stage = Stage::from_original_owners(training, receipts).await?;
        let original = stage
            .execute_training(&f.config.dataset, Arc::new(AtomicBool::new(false)))
            .await?;
        let saved = retained(&f)?;
        if change_training {
            training_changed.store(/*val*/ true, Ordering::SeqCst);
        } else {
            receipt_changed.store(/*val*/ true, Ordering::SeqCst);
        }
        let error = read(&stage, &f.config.dataset, &original.receipt)
            .await
            .err()
            .expect("changed original CURRENT");
        if change_training {
            assert!(matches!(
                error,
                ReadError::Stage(StageError::Training(OwnerError::CommitUncertain))
            ));
        } else {
            assert!(matches!(
                error,
                ReadError::Stage(StageError::Receipt(ReceiptError::Owner(
                    LearningOriginalOwnerErrorV1::CommitUncertain
                )))
            ));
        }
        assert_eq!(retained(&f)?, saved);
    }
    Ok(())
}
