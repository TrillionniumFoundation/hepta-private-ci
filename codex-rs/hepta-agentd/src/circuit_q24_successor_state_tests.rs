//! Finite-state and notification components only. Synthetic checkpoint data
//! never constructs an original aggregate, Root session or installed owner.

use pretty_assertions::assert_eq;
use super::*;
use crate::neuron_generation_current::test_support::{Fixture, config};
use crate::neuron_generation_update_bootstrap::{learning_test_baseline, learning_test_decision};

fn checkpoint() -> anyhow::Result<LearningIterationSnapshotV1> {
    let baseline = learning_test_baseline()?;
    let mut original = config()?;
    original.manifest.bundle_digest = baseline.digest()?.into_array();
    original.initial.manifest_digest = original.manifest.digest()?;
    let fixture = Fixture::new(original)?;
    let mut snapshot = learning_test_decision(&fixture, baseline, "none")?.snapshot().clone();
    // State-machine data only; this changed request is never authenticated,
    // given to a production owner or used as a publication qualification.
    snapshot.request.envelope.expiry_unix_seconds = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() + 30;
    Ok(snapshot)
}

#[test]
fn pending_slot_exposes_neither_owner_nor_provider() {
    let slot = SuccessorSlot::new_pending_slot();
    assert!(matches!(slot.actual_handle(), Err(CircuitTaskErrorV1::Unavailable)));
    assert!(matches!(slot.actual_invocation(), Err(CircuitTaskErrorV1::Unavailable)));
    assert_eq!(slot.pending_count(), 0);
    assert!(matches!(slot.require_installation_open(), Err(CircuitTaskErrorV1::Unavailable)));
    assert!(matches!(slot.begin_installation(), Err(CircuitTaskErrorV1::Unavailable)));
    assert!(slot.closed.is_cancelled());
}

#[test]
fn cancelled_or_repeated_installation_keeps_work_counted_until_completion() -> anyhow::Result<()> {
    for repeat in [false, true] {
        let slot = SuccessorSlot::new_pending_slot();
        slot.state.lock().unwrap().decision = Some(checkpoint()?);
        let work = slot.begin_installation()?;
        slot.require_installation_open()?;
        assert_eq!(slot.pending_count(), 1);
        if repeat { assert!(slot.begin_installation().is_err()); } else { slot.close(); }
        assert!(slot.closed.is_cancelled());
        assert!(matches!(slot.require_installation_open(), Err(CircuitTaskErrorV1::Unavailable)));
        assert_eq!(slot.pending_count(), 1);
        assert!(matches!(slot.actual_handle(), Err(CircuitTaskErrorV1::Unavailable)));
        drop(work);
        assert_eq!(slot.pending_count(), 0);
        assert!(slot.begin_installation().is_err());
    }
    Ok(())
}

#[tokio::test]
async fn checkpoint_wait_exposes_exact_data_and_drop_permanently_closes() -> anyhow::Result<()> {
    let slot = SuccessorSlot::new_pending_slot();
    let snapshot = checkpoint()?;
    let waiting = Arc::clone(&slot);
    let expected = snapshot.clone();
    let task = tokio::spawn(async move { waiting.wait_original_generation(&expected).await });
    assert_eq!(slot.decision(snapshot.request.envelope.expiry_unix_seconds).await?, snapshot);
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    assert!(slot.closed.is_cancelled());
    assert!(slot.begin_installation().is_err());
    assert!(slot.actual_invocation().is_err());
    Ok(())
}

#[tokio::test]
async fn expired_checkpoint_closes_without_an_install_or_wakeup() -> anyhow::Result<()> {
    let slot = SuccessorSlot::new_pending_slot();
    let mut snapshot = checkpoint()?;
    snapshot.request.envelope.expiry_unix_seconds = 1;
    assert!(matches!(slot.wait_original_generation(&snapshot).await, Err(LearningError::DeadlineExceeded)));
    assert!(slot.closed.is_cancelled());
    assert_eq!(slot.pending_count(), 0);
    Ok(())
}

#[tokio::test]
async fn mismatched_checkpoint_cannot_wake_a_registered_wait() -> anyhow::Result<()> {
    for field in ["owner", "request", "prefix"] {
        let slot = SuccessorSlot::new_pending_slot();
        let original = checkpoint()?;
        slot.state.lock().unwrap().decision = Some(original.clone());
        let mut changed = original;
        match field {
            "owner" => changed.owners.trainer = codex_hepta_types::StableId::new("other-trainer")?,
            "request" => changed.request.operation_id = codex_hepta_types::StableId::new("other-operation")?,
            "prefix" => { changed.receipts.pop(); },
            _ => unreachable!(),
        }
        assert!(matches!(slot.wait_original_generation(&changed).await, Err(LearningError::WrongScope)), "{field}");
        assert!(slot.closed.is_cancelled());
        assert!(!slot.state.lock().unwrap().generation);
    }
    Ok(())
}

#[tokio::test]
async fn an_existing_notification_is_seen_without_a_lost_wakeup() -> anyhow::Result<()> {
    let slot = SuccessorSlot::new_pending_slot();
    let snapshot = checkpoint()?;
    // Notification machinery only: no Ready state, provider or actual owner is
    // constructed. A real notification is emitted solely by install_generation.
    { let mut state = slot.state.lock().unwrap(); state.decision = Some(snapshot.clone()); state.generation = true; }
    slot.changed.send_replace(());
    slot.wait_original_generation(&snapshot).await?;
    assert!(slot.actual_handle().is_err());
    assert!(!slot.closed.is_cancelled());
    Ok(())
}
