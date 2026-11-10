//! Recovery exercises real framed owner reads over synthetic signed evidence.
//! Structural suffix receipts do not qualify production selection or next use.

use codex_hepta_learning_artifacts::CellStatePartitionV1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;

use super::*;

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
            evidence_digest: Digest32::of_bytes(b"synthetic-recovery-suffix"),
            observed_unix_seconds,
            observation,
        },
        observed_unix_seconds,
    )?;
    Ok(())
}

#[tokio::test]
async fn completed_and_intermediate_histories_read_original_evaluation_after_work_expiry()
-> anyhow::Result<()> {
    let current = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let original = current - 400;
    for disposition in [
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        IndependentEvaluationDispositionV1::Ineligible,
    ] {
        let fixture = LearningFixture::new_at(disposition, original);
        assert!(fixture.snapshot.request.envelope.expiry_unix_seconds < current);
        let prepared = prepare_cell_learning_evaluation_v1(
            fixture.runner(),
            &fixture.snapshot,
            &fixture.receipt,
            &fixture.qualification,
            &fixture.request(original),
        )?;
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(fixture.snapshot.clone())?;
        coordinator.record(prepared.clone(), prepared.observed_unix_seconds)?;
        let mut histories = vec![coordinator.snapshot().clone()];
        let updated = coordinator.next_stage() == Some(LearningIterationStageV1::Proposal);
        if updated {
            let candidate_bundle = coordinator
                .candidate()
                .expect("trained candidate")
                .digest()?;
            let proposal_id = fixture.snapshot.request.operation_id.clone();
            append(
                &mut coordinator,
                LearningIterationObservationV1::Proposal {
                    candidate_bundle,
                    proposal_id,
                    composition_digest: Digest32::of_bytes(b"original-proposal"),
                    disposition: LearningProposalDispositionV1::UpdateCandidates,
                },
                original,
            )?;
            histories.push(coordinator.snapshot().clone());
        }
        let bundle = coordinator
            .next_task_bundle()
            .expect("selected bundle")
            .digest()?;
        let selection_digest = Digest32::of_bytes(b"original-selection");
        append(
            &mut coordinator,
            LearningIterationObservationV1::Selection {
                candidate_bundle: bundle,
                selection_digest,
            },
            original,
        )?;
        histories.push(coordinator.snapshot().clone());
        let request = &fixture.snapshot.request;
        let state_partition = CellStatePartitionV1 {
            principal_id: request.principal_id.clone(),
            agent_id: request.agent_id.clone(),
            cell_id: request.cell_id.clone(),
            run_id: StableId::new("distinct-recovery-next-task")?,
        };
        let checkpoint_digest = Digest32::of_bytes(b"original-next-checkpoint");
        let committed_step_receipt = Digest32::of_bytes(b"original-next-step");
        let next_use = if updated {
            LearningIterationObservationV1::NextUse {
                candidate_bundle: bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                state_cutover_receipt: Digest32::of_bytes(b"original-cutover"),
            }
        } else {
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle: bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                task_owner_publication: Digest32::of_bytes(b"original-task-publication"),
            }
        };
        append(&mut coordinator, next_use, original)?;
        assert_eq!(coordinator.next_stage(), None);
        histories.push(coordinator.snapshot().clone());
        for history in histories {
            let (training, evaluation) = original_owners(&fixture, prepared.clone())?;
            let expected = evaluation.signature.clone();
            let (trainer, trainer_server) = training.client()?;
            let (evaluator, evaluator_server) = evaluation.client()?;
            let trainer_peer = serve(
                trainer_server,
                training,
                history.head_digest,
                /*requests*/ 1,
            );
            let evaluator_peer = serve(
                evaluator_server,
                evaluation,
                history.head_digest,
                /*requests*/ 1,
            );
            let mut read = super::request(&fixture);
            read.snapshot = &history;
            let authenticated =
                read_cell_learning_evaluation_v1(read, &trainer, &evaluator).await?;
            assert_eq!(
                (authenticated.receipt(), authenticated.attestation()),
                (&prepared, &expected)
            );
            trainer_peer.join().expect("original trainer")?;
            evaluator_peer.join().expect("original evaluator")?;
        }
    }
    Ok(())
}

#[tokio::test]
async fn corrupted_or_replaced_evaluation_history_is_refused_before_owner_io() -> anyhow::Result<()>
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
    for scenario in 0..6 {
        let mut altered = prepared.clone();
        match scenario {
            0 | 1 | 5 => {}
            2 => altered.evidence_digest = Digest32::of_bytes(b"substituted-evaluation"),
            3 => altered.observed_unix_seconds += 1,
            4 => {
                let LearningIterationObservationV1::Evaluation { disposition, .. } =
                    &mut altered.observation
                else {
                    unreachable!()
                };
                *disposition = LearningEvaluationDispositionV1::Qualified;
            }
            _ => unreachable!(),
        }
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(fixture.snapshot.clone())?;
        coordinator.record(altered.clone(), altered.observed_unix_seconds)?;
        let mut history = coordinator.snapshot().clone();
        match scenario {
            0 => history.head_digest = Digest32::of_bytes(b"wrong-current-head"),
            1 => {
                let bundle = coordinator
                    .next_task_bundle()
                    .expect("retained bundle")
                    .digest()?;
                append(
                    &mut coordinator,
                    LearningIterationObservationV1::Selection {
                        candidate_bundle: bundle,
                        selection_digest: Digest32::of_bytes(b"original-selection"),
                    },
                    now,
                )?;
                history = coordinator.snapshot().clone();
                history.receipts.last_mut().expect("selection").predecessor = Digest32::ZERO;
            }
            5 => {
                let mut prefix = LearningIterationCoordinatorV1::new(
                    history.request.clone(),
                    history.owners.clone(),
                )?;
                for receipt in fixture.snapshot.receipts.iter().take(2) {
                    prefix.record(receipt.clone(), receipt.observed_unix_seconds)?;
                }
                history = prefix.snapshot().clone();
            }
            2..=4 => {
                // A valid recomputed chain alone must not replace the original
                // signed evaluator result, timestamp or disposition.
                LearningIterationCoordinatorV1::from_snapshot(history.clone())?;
            }
            _ => unreachable!(),
        }
        let (training, evaluation) = original_owners(&fixture, prepared.clone())?;
        let (trainer, mut trainer_server) = training.client()?;
        let (evaluator, mut evaluator_server) = evaluation.client()?;
        trainer_server.set_nonblocking(true)?;
        evaluator_server.set_nonblocking(true)?;
        let mut read = request(&fixture);
        read.snapshot = &history;
        assert!(
            read_cell_learning_evaluation_v1(read, &trainer, &evaluator)
                .await
                .is_err()
        );
        for server in [&mut trainer_server, &mut evaluator_server] {
            assert_eq!(
                server.read(&mut [0]).expect_err("no owner request").kind(),
                ErrorKind::WouldBlock
            );
        }
    }
    Ok(())
}
