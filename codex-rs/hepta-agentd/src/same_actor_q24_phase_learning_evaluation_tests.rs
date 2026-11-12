//! Notification-state components only. The snapshots below are synthetic data.
//! These do not install B, export a Trainer capability or qualify a learning run.

use std::time::Duration;

use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::LearningIterationBudgetV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;
use crate::neuron_generation_update_bootstrap::learning_test_baseline;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;

const WAIT: Duration = Duration::from_secs(60);

fn exchange() -> anyhow::Result<OriginalEvaluationExchange> {
    Ok(OriginalEvaluationExchange::new(
        SameActorPhaseGate::from_original_deadline(
            SameActorPhaseDeadline::at_original_service_start(WAIT)?,
        )?,
    ))
}

fn metadata() -> anyhow::Result<LearningIterationSnapshotV1> {
    let id = |label: &str| StableId::new(label);
    let digest = |label: &str| Digest32::of_bytes(label.as_bytes());
    let expiry = SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_secs()
        .checked_add(3600)
        .ok_or_else(|| anyhow::anyhow!("fixture clock overflow"))?;
    let request = LearningIterationRequestV1 {
        operation_id: id("phase-evaluation-operation")?,
        principal_id: id("phase-evaluation-principal")?,
        agent_id: id("phase-evaluation-agent")?,
        cell_id: id("phase-evaluation-cell")?,
        source_run_id: id("phase-evaluation-source")?,
        completed_task_receipt: digest("completed"),
        selected_artifact_digest: digest("artifact"),
        evaluation_profile: digest("profile"),
        selected_bundle: learning_test_baseline()?,
        envelope: IterationEnvelopeV1 {
            envelope_id: id("phase-evaluation-envelope")?,
            base_commit: digest("commit"),
            base_tree: digest("tree"),
            objective_digest: digest("objective"),
            grammar_digest: digest("grammar"),
            maximum_files: 1,
            maximum_diff_bytes: 1024,
            maximum_candidates: 1,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: expiry,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: 100,
            maximum_dataset_bytes: 1024,
            maximum_training_steps: 100,
            maximum_training_milliseconds: 1000,
            maximum_artifact_bytes: 1024,
        },
    };
    let owners = LearningIterationOwnersV1 {
        evidence_trust_digest: digest("trust"),
        experience: id("experience")?,
        dataset: id("dataset")?,
        trainer: id("trainer")?,
        evaluator: id("evaluator")?,
        proposal: id("proposal")?,
        selector: id("selector")?,
        next_use_observer: id("observer")?,
    };
    Ok(LearningIterationCoordinatorV1::new(request, owners)?
        .snapshot()
        .clone())
}

#[tokio::test]
async fn original_notification_requires_installed_state_before_releasing_wait()
-> anyhow::Result<()> {
    let exchange = exchange()?;
    let snapshot = metadata()?;
    exchange.announce_original_training(&snapshot)?;
    let mut waiting = Box::pin(exchange.wait_installed(&snapshot));
    tokio::select! {
        biased;
        result = &mut waiting => panic!("released before installation: {result:?}"),
        _ = std::future::ready(()) => {}
    }
    let installation = exchange.begin_installation(&snapshot)?;
    tokio::select! {
        biased;
        result = &mut waiting => panic!("released during installation: {result:?}"),
        _ = std::future::ready(()) => {}
    }
    exchange.complete_installation(&snapshot, installation)?;
    tokio::time::timeout(WAIT, waiting).await??;
    exchange.gate.require_open()?;
    Ok(())
}

#[tokio::test]
async fn cancelling_registered_installation_wait_closes_all_later_entries()
-> anyhow::Result<()> {
    let exchange = exchange()?;
    let snapshot = metadata()?;
    exchange.announce_original_training(&snapshot)?;
    let mut waiting = Box::pin(exchange.wait_installed(&snapshot));
    tokio::select! {
        biased;
        result = &mut waiting => panic!("unexpected completion: {result:?}"),
        _ = std::future::ready(()) => {}
    }
    let installation = exchange.begin_installation(&snapshot)?;
    drop(waiting);
    assert!(exchange.gate.require_open().is_err());
    assert!(matches!(
        exchange.begin_installation(&snapshot),
        Err(Error::CommitUncertain)
    ));
    assert!(matches!(
        exchange.complete_installation(&snapshot, installation),
        Err(Error::CommitUncertain)
    ));
    Ok(())
}

#[tokio::test]
async fn cancelled_readonly_progress_preserves_phase_and_announced_state_is_not_lost()
-> anyhow::Result<()> {
    let exchange = exchange()?;
    let mut observing = Box::pin(exchange.training_snapshot());
    tokio::select! {
        biased;
        result = &mut observing => panic!("unexpected snapshot: {result:?}"),
        _ = std::future::ready(()) => {}
    }
    drop(observing);
    exchange.gate.require_open()?;
    let snapshot = metadata()?;
    exchange.announce_original_training(&snapshot)?;
    assert_eq!(
        tokio::time::timeout(WAIT, exchange.training_snapshot()).await??,
        snapshot
    );
    let installation = exchange.begin_installation(&snapshot)?;
    exchange.complete_installation(&snapshot, installation)?;
    tokio::time::timeout(WAIT, exchange.wait_installed(&snapshot)).await??;
    exchange.gate.require_open()?;
    Ok(())
}

#[test]
fn changed_cut_and_repeated_installation_are_terminal() -> anyhow::Result<()> {
    let snapshot = metadata()?;
    let mut changed = snapshot.clone();
    changed.request.operation_id = StableId::new("different-operation")?;
    let first = exchange()?;
    first.announce_original_training(&snapshot)?;
    assert!(matches!(
        first.begin_installation(&changed),
        Err(Error::WrongScope)
    ));
    assert!(first.gate.require_open().is_err());

    let repeated = exchange()?;
    repeated.announce_original_training(&snapshot)?;
    let installation = repeated.begin_installation(&snapshot)?;
    repeated.complete_installation(&snapshot, installation)?;
    assert!(matches!(
        repeated.begin_installation(&snapshot),
        Err(Error::WrongScope)
    ));
    assert!(repeated.gate.require_open().is_err());
    Ok(())
}

#[test]
fn expired_request_is_refused_without_replacing_the_original_phase_end() -> anyhow::Result<()> {
    let exchange = exchange()?;
    let original_instant = exchange.gate.deadline().instant();
    let original_boottime = exchange.gate.deadline().boottime_ns();
    let mut expired = metadata()?;
    expired.request.envelope.expiry_unix_seconds = 0;
    assert!(matches!(
        exchange.announce_original_training(&expired),
        Err(Error::DeadlineExceeded)
    ));
    assert!(exchange.gate.require_open().is_err());
    assert_eq!(exchange.gate.deadline().instant(), original_instant);
    assert_eq!(exchange.gate.deadline().boottime_ns(), original_boottime);
    Ok(())
}

#[test]
fn dropping_the_actual_installation_permit_cannot_rearm_the_cut() -> anyhow::Result<()> {
    let exchange = exchange()?;
    let snapshot = metadata()?;
    exchange.announce_original_training(&snapshot)?;
    let installation = exchange.begin_installation(&snapshot)?;
    exchange.require_installing(&snapshot)?;
    drop(installation);
    assert!(exchange.gate.require_open().is_err());
    assert!(matches!(
        exchange.begin_installation(&snapshot),
        Err(Error::CommitUncertain)
    ));
    assert!(matches!(
        exchange.require_installing(&snapshot),
        Err(Error::CommitUncertain)
    ));
    Ok(())
}
