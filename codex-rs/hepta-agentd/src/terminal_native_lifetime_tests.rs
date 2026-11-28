//! Real blocking workers over the existing authorized synthetic owner fixture.
//! Both workers stop before the actual fit; no model fit or new science runs.

use super::*;
use crate::terminal_learning::TerminalNativeLifetimeV1;
use pretty_assertions::assert_eq;
use std::sync::TryLockError;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::oneshot;

fn pause_before_fit(
    lifetime: &TerminalNativeLifetimeV1,
) -> (oneshot::Receiver<()>, std::sync::mpsc::Sender<()>) {
    let (entered, waiting) = oneshot::channel();
    let (release, held) = std::sync::mpsc::channel();
    *lifetime.before_fit.lock().unwrap() = Some(Box::new(move || {
        let _ = entered.send(());
        held.recv_timeout(Duration::from_secs(/*secs*/ 10))
            .expect("bounded native test barrier");
    }));
    (waiting, release)
}

async fn wait_for_worker_exit(lifetime: &TerminalNativeLifetimeV1) {
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), async {
        while lifetime.blockers() != 0 {
            tokio::time::sleep(Duration::from_millis(/*millis*/ 1)).await;
        }
    })
    .await
    .expect("real native permit was not released");
    assert_eq!(lifetime.fit_calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn cancellation_before_fit_keeps_real_worker_tracked_until_exit() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    let lifetime = owner.native_lifetime();
    let (entered, release) = pause_before_fit(&lifetime);
    let state = fixture.daemon.state();
    let (handle, bootstrap) = terminal_learning_channel_v1(
        fixture.daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        owner,
        /*capacity*/ 1,
    )
    .unwrap();
    bootstrap.attach_native_lifetime(&state).unwrap();
    // Same-owner startup registration is idempotent; a different original
    // owner sharing Ledger/Memory still cannot replace the registered lane.
    bootstrap.attach_native_lifetime(&state).unwrap();
    assert!(
        state
            .attach_terminal_native_lifetime(fixture.native_owner().native_lifetime())
            .is_err()
    );
    let cancellation = CancellationToken::new();
    let running =
        tokio::spawn(bootstrap.run_with_clock(Arc::clone(&state), cancellation.clone(), || Ok(50)));
    let request = fixture.request.clone();
    let submitted = tokio::spawn(async move { handle.submit(request).await });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), entered)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(state.terminal_native_drain_blockers(), 1);
    assert!(matches!(
        fixture.ledger.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    cancellation.cancel();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), running)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(
        submitted.await.unwrap(),
        Err(TerminalLearningErrorV1::CommitUncertain)
    );
    // The supervised future has actually exited. Its abandoned JoinHandle must
    // not release the blocking worker's permit or advertise a completed drain.
    assert_eq!(state.terminal_native_drain_blockers(), 1);
    assert!(lifetime.require_fit_open().is_err());
    assert_eq!(lifetime.fit_calls.load(Ordering::SeqCst), 0);
    assert!(matches!(
        fixture.ledger.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    release.send(()).unwrap();
    wait_for_worker_exit(&lifetime).await;
    assert_eq!(state.terminal_native_drain_blockers(), 0);
    assert!(fixture.ledger.try_lock().is_ok());
}

#[tokio::test]
async fn draining_closes_native_admission_and_cannot_finish_with_live_worker() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    let lifetime = owner.native_lifetime();
    let (entered, release) = pause_before_fit(&lifetime);
    let state = fixture.daemon.state();
    let stale_running_state = fixture.daemon.state();
    let (handle, bootstrap) = terminal_learning_channel_v1(
        fixture.daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        owner,
        /*capacity*/ 1,
    )
    .unwrap();
    bootstrap.attach_native_lifetime(&state).unwrap();
    let cancellation = CancellationToken::new();
    let running =
        tokio::spawn(bootstrap.run_with_clock(Arc::clone(&state), cancellation.clone(), || Ok(50)));
    let request = fixture.request.clone();
    let submitted = tokio::spawn(async move { handle.submit(request).await });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), entered)
        .await
        .unwrap()
        .unwrap();
    fixture
        .daemon
        .registry
        .compare_and_transition(
            &fixture.daemon.identity.agent_id,
            /*expected_generation*/ 2,
            codex_hepta_fleet::AgentLifecycle::Draining,
        )
        .unwrap();
    let mut draining = Box::pin(crate::runtime::drain_runtime(Arc::clone(&state)));
    poll_fn(|context| {
        // No turns or Circuit/generation workers exist in this fixture. The
        // real blocked terminal worker alone keeps this drain future pending.
        assert!(draining.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    assert_eq!(state.terminal_native_drain_blockers(), 1);
    assert!(lifetime.require_fit_open().is_err());
    let snapshot = state.drain_snapshot(/*automation_blockers*/ 0).unwrap();
    assert!(snapshot.admission_closed && !snapshot.drained);
    // A runtime which already observed Draining with no registered lane cannot
    // acquire one afterward. The worker stays owned by its original state.
    let late_state = fixture.daemon.state();
    assert!(
        late_state
            .attach_terminal_native_lifetime(Arc::clone(&lifetime))
            .is_err()
    );
    assert_eq!(late_state.terminal_native_drain_blockers(), 0);
    assert_eq!(state.terminal_native_drain_blockers(), 1);
    release.send(()).unwrap();
    wait_for_worker_exit(&lifetime).await;
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), draining)
        .await
        .unwrap()
        .unwrap();
    assert!(submitted.await.unwrap().is_err());
    assert_eq!(state.terminal_native_drain_blockers(), 0);
    assert!(lifetime.require_fit_open().is_err());
    cancellation.cancel();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), running)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(fixture.ledger.try_lock().is_ok());
    // A generation rejection must leave a sticky terminal fence even when the
    // rejected state still caches Running and had no registered worker lane.
    fixture
        .daemon
        .registry
        .compare_and_transition(
            &fixture.daemon.identity.agent_id,
            /*expected_generation*/ 3,
            codex_hepta_fleet::AgentLifecycle::Stopped,
        )
        .unwrap();
    assert!(stale_running_state.refresh_generation().is_err());
    let rejected_lifetime = fixture.native_owner().native_lifetime();
    assert!(
        stale_running_state
            .attach_terminal_native_lifetime(Arc::clone(&rejected_lifetime))
            .is_err()
    );
    assert!(rejected_lifetime.require_fit_open().is_err());
    assert_eq!(stale_running_state.terminal_native_drain_blockers(), 0);
}
