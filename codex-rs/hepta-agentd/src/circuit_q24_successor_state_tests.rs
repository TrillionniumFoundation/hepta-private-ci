//! Finite-state and notification tests use explicit synthetic checkpoint data.
//! The Feature helper installs actual original handles and Source owners in a
//! component slot. It does not construct an original Root aggregate or session.

use super::*;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::config;
use crate::neuron_generation_update_bootstrap::learning_test_baseline;
use crate::neuron_generation_update_bootstrap::learning_test_decision;
use pretty_assertions::assert_eq;

fn checkpoint() -> anyhow::Result<LearningIterationSnapshotV1> {
    let baseline = learning_test_baseline()?;
    let mut original = config()?;
    original.manifest.bundle_digest = baseline.digest()?.into_array();
    original.initial.manifest_digest = original.manifest.digest()?;
    let fixture = Fixture::new(original)?;
    let mut snapshot = learning_test_decision(&fixture, baseline, "none")?
        .snapshot()
        .clone();
    // State-machine data only; this changed request is never authenticated,
    // given to a production owner or used as a publication qualification.
    snapshot.request.envelope.expiry_unix_seconds =
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() + 30;
    Ok(snapshot)
}

#[test]
fn pending_slot_exposes_neither_owner_nor_provider() {
    let slot = SuccessorSlot::new_pending_slot();
    assert!(matches!(
        slot.actual_handle(),
        Err(CircuitTaskErrorV1::Unavailable)
    ));
    assert!(matches!(
        slot.actual_invocation(),
        Err(CircuitTaskErrorV1::Unavailable)
    ));
    assert_eq!(slot.pending_count(), 0);
    assert!(matches!(
        slot.require_installation_open(),
        Err(CircuitTaskErrorV1::Unavailable)
    ));
    assert!(matches!(
        slot.begin_installation(),
        Err(CircuitTaskErrorV1::Unavailable)
    ));
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
        if repeat {
            assert!(slot.begin_installation().is_err());
        } else {
            slot.close();
        }
        assert!(slot.closed.is_cancelled());
        assert!(matches!(
            slot.require_installation_open(),
            Err(CircuitTaskErrorV1::Unavailable)
        ));
        assert_eq!(slot.pending_count(), 1);
        assert!(matches!(
            slot.actual_handle(),
            Err(CircuitTaskErrorV1::Unavailable)
        ));
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
    assert_eq!(
        slot.decision(snapshot.request.envelope.expiry_unix_seconds)
            .await?,
        snapshot
    );
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
    assert!(matches!(
        slot.wait_original_generation(&snapshot).await,
        Err(LearningError::DeadlineExceeded)
    ));
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
            "request" => {
                changed.request.operation_id = codex_hepta_types::StableId::new("other-operation")?
            }
            "prefix" => {
                changed.receipts.pop();
            }
            _ => unreachable!(),
        }
        assert!(
            matches!(
                slot.wait_original_generation(&changed).await,
                Err(LearningError::WrongScope)
            ),
            "{field}"
        );
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
    {
        let mut state = slot.state.lock().unwrap();
        state.decision = Some(snapshot.clone());
        state.generation = true;
    }
    slot.changed.send_replace(());
    slot.wait_original_generation(&snapshot).await?;
    assert!(slot.actual_handle().is_err());
    assert!(!slot.closed.is_cancelled());
    Ok(())
}

impl SuccessorSlot {
    // Only the existing real Feature case calls this with its direct handle
    // and same Source owner. The snapshot supplies component prefix data;
    // neither this helper nor that data claims a registered Root aggregate.
    pub(crate) async fn installed_from_original_feature_for_test(
        snapshot: &LearningIterationSnapshotV1,
        handle: CircuitTaskHandleV1,
        invocation: Arc<DurableCircuitTaskSourceV1<FileAnchorWitnessStore>>,
    ) -> anyhow::Result<Arc<Self>> {
        let slot = Self::new_pending_slot();
        let installing = async {
            let result = async {
                let observed = slot
                    .decision(snapshot.request.envelope.expiry_unix_seconds)
                    .await?;
                assert_eq!(&observed, snapshot);
                let work = slot.begin_installation()?;
                slot.install_original_owner(handle, invocation)?;
                slot.original_generation_installed(snapshot)?;
                drop(work);
                Ok::<(), anyhow::Error>(())
            }
            .await;
            if result.is_err() {
                slot.close();
            }
            result
        };
        // Both futures remain owned here. Failure closes the waiter; dropping
        // this helper drops its original CloseOnDrop, without a detached task.
        let (waited, installed) = tokio::join!(slot.wait_original_generation(snapshot), installing);
        installed?;
        waited?;
        Ok(slot)
    }
}

#[test]
fn ready_guard_rejects_notification_without_an_installed_original_owner() -> anyhow::Result<()> {
    for phase in [Phase::Pending, Phase::Installing, Phase::Ready] {
        let slot = SuccessorSlot::new_pending_slot();
        let snapshot = checkpoint()?;
        // Invalid component state is a refusal control only. It never creates
        // an owner, publication, historical registration or accepted receipt.
        {
            let mut state = slot.state.lock().unwrap();
            state.phase = phase;
            state.decision = Some(snapshot.clone());
            state.generation = true;
        }
        assert!(!slot.original_generation_ready_hint());
        assert!(matches!(
            slot.require_original_generation_ready(&snapshot),
            Err(LearningError::Unavailable)
        ));
        assert!(slot.closed.is_cancelled());
        assert!(slot.actual_handle().is_err());
        assert!(slot.actual_invocation().is_err());
    }
    Ok(())
}

#[test]
fn ready_guard_rejects_expiry_and_poison_without_returning_an_owner() -> anyhow::Result<()> {
    let expired = SuccessorSlot::new_pending_slot();
    let mut snapshot = checkpoint()?;
    snapshot.request.envelope.expiry_unix_seconds = 1;
    assert!(matches!(
        expired.require_original_generation_ready(&snapshot),
        Err(LearningError::DeadlineExceeded)
    ));
    assert!(expired.closed.is_cancelled());
    assert!(!expired.original_generation_ready_hint());

    let poisoned = SuccessorSlot::new_pending_slot();
    let held = Arc::clone(&poisoned);
    assert!(
        std::thread::spawn(move || {
            let _guard = held.state.lock().unwrap();
            panic!("intentional successor state poison control");
        })
        .join()
        .is_err()
    );
    assert!(!poisoned.original_generation_ready_hint());
    assert!(matches!(
        poisoned.require_original_generation_ready(&checkpoint()?),
        Err(LearningError::Unavailable)
    ));
    assert!(poisoned.closed.is_cancelled());
    assert!(poisoned.actual_handle().is_err());
    assert!(poisoned.actual_invocation().is_err());
    Ok(())
}
