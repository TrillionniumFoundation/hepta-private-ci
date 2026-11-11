//! Original signed-task fixture exercises the unchanged Direct path first.
//! Pending views below receive that real record but can never execute it. No
//! original Root/learning capability or ordinary-business C claim is invented.

use super::*;
use crate::circuit_q24_successor::SuccessorSlot;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn pending_and_closed_views_refuse_a_real_authenticated_task_without_queuing()
-> anyhow::Result<()> {
    let mut f = fixture(/*lose_ack*/ false, /*expire*/ false).await?;
    let response = f
        .runtime
        .state
        .response(
            /*request_id*/ 1,
            /*spawn_generation*/ 1,
            AgentdMethod::ObjectiveStart {
                request: f.request.clone(),
            },
        )
        .await?;
    let AgentdPayload::ObjectiveRun(admission) = response.payload else {
        panic!("actual original admission");
    };
    assert_eq!(admission.disposition, "circuit_succeeded");
    let record = f.invocation.records.lock().unwrap()[0].clone();
    let receipt = f.invocation.receipts.lock().unwrap()[0].clone();
    let request = f.invocation.build(&f.runtime.identity, &record)?;
    let slot = SuccessorSlot::new_pending_slot();
    let handle = crate::CircuitTaskHandleV1::original_pending_successor_handle(Arc::clone(&slot));
    let invocation =
        crate::circuit_q24_successor::original_pending_successor_invocation(Arc::clone(&slot));
    for closed in [false, true] {
        if closed {
            slot.close();
        }
        assert!(invocation.build(&f.runtime.identity, &record).is_err());
        assert!(
            invocation
                .publish_result(&f.runtime.identity, &record, &receipt)
                .is_err()
        );
        assert!(matches!(
            invocation.observe_learning(&f.runtime.identity, &record, receipt.trace()),
            crate::CircuitTaskLearningReadinessV1::Pending(
                crate::CircuitTaskLearningPendingV1::OwnerUnavailable
            )
        ));
        assert_eq!(
            timeout(
                Duration::from_millis(100),
                handle.submit(request.clone(), record.clone())
            )
            .await?,
            Err(crate::CircuitTaskErrorV1::Unavailable)
        );
        assert_eq!(
            timeout(
                Duration::from_millis(100),
                handle.readback(request.clone(), record.clone())
            )
            .await?,
            Err(crate::CircuitTaskErrorV1::Unavailable)
        );
        assert_eq!(handle.pending_count(), 0);
        assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    }
    f.stop().await;
    f.store.close().await;
    Ok(())
}

#[tokio::test]
async fn successor_effect_gate_rechecks_actual_draining_and_full_identity() -> anyhow::Result<()> {
    let mut f = fixture(/*lose_ack*/ false, /*expire*/ false).await?;
    let state = &f.runtime.state;
    let identity = &f.runtime.identity;
    crate::cell_q24_publication_driver::require_successor_admission(state, identity)?;
    let mut other = identity.clone();
    other.spawn_generation += 2;
    assert!(
        crate::cell_q24_publication_driver::require_successor_admission(state, &other).is_err()
    );
    other = identity.clone();
    other.resources.turn_queue_capacity += 1;
    assert!(
        crate::cell_q24_publication_driver::require_successor_admission(state, &other).is_err()
    );
    f.runtime.registry.compare_and_transition(
        &identity.agent_id,
        identity.spawn_generation + 1,
        AgentLifecycle::Draining,
    )?;
    state.mark_draining()?;
    assert!(!state.automation_admission_ready()?);
    assert!(
        crate::cell_q24_publication_driver::require_successor_admission(state, identity).is_err()
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 0);
    f.stop().await;
    f.store.close().await;
    Ok(())
}
