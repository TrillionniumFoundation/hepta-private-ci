//! Same-UID/synthetic-proof component using the actual phase Session fixture.
//! A real Session Drop and worker join are observed; no normal completion is made.

use super::*;
use crate::root_authority_session::lifecycle_support_tests::PhaseConnection;
use crate::root_authority_session::lifecycle_support_tests::join_peer;
use crate::root_authority_session::lifecycle_support_tests::phase_connection;
use pretty_assertions::assert_eq;
use std::future::Future;
use std::task::Context;
use std::task::Waker;
use std::time::Duration;

#[tokio::test]
async fn ready_session_worker_join_survives_cancelled_recording_waiter() {
    let slot = OriginalRootSessionCustodySlot::new();
    let PhaseConnection { session, peer, .. } = phase_connection(&slot).await;
    let session = session.unwrap();
    session.require_original_phase_task_custody(&slot).unwrap();
    let original = slot.state.lock().unwrap().original.as_ref().unwrap().clone();
    let actual_join = {
        let state = original.worker.lock().await;
        assert_eq!(state.observed, None);
        state.handle.as_ref().unwrap().clone()
    };
    assert!(!original.abort.is_finished());
    // On this current-thread runtime no worker can finish its scheduled abort
    // before the synchronous polls below borrow the same original Shared.
    // The actual Session's last field, not this test, marks it retired.
    drop(session);
    assert!(original.session_retired.load(Ordering::Acquire));
    let mut cancelled = Box::pin(slot.stop_and_join_retired_session_tasks());
    let mut first = Box::pin(slot.stop_and_join_retired_session_tasks());
    let mut second = Box::pin(slot.stop_and_join_retired_session_tasks());
    {
        let mut context = Context::from_waker(Waker::noop());
        assert!(cancelled.as_mut().poll(&mut context).is_pending());
        assert!(first.as_mut().poll(&mut context).is_pending());
        assert!(second.as_mut().poll(&mut context).is_pending());
    }

    let expected = tokio::time::timeout(Duration::from_secs(5), actual_join)
        .await
        .unwrap();
    assert_eq!(expected, OriginalRootWorkerTermination::Cancelled);
    assert!(original.abort.is_finished());
    {
        // Shared is already Ready. All three original callers must now wait
        // on this recording lock, with no worker handle removed from custody.
        let state = original.worker.lock().await;
        assert_eq!(state.observed, None);
        assert_eq!(state.handle.as_ref().unwrap().peek(), Some(&expected));
        let mut context = Context::from_waker(Waker::noop());
        assert!(cancelled.as_mut().poll(&mut context).is_pending());
        assert!(first.as_mut().poll(&mut context).is_pending());
        assert!(second.as_mut().poll(&mut context).is_pending());
        drop(cancelled);
        assert_eq!(state.observed, None);
        assert_eq!(state.handle.as_ref().unwrap().peek(), Some(&expected));
    }
    let (first, second) = tokio::time::timeout(Duration::from_secs(5), async {
        tokio::join!(first, second)
    })
    .await
    .unwrap();
    let first = first.unwrap();
    assert_eq!(second.unwrap(), first);
    let OriginalRootSessionJoinObservation::Joined {
        slot_poisoned,
        worker,
        consumers,
        ..
    } = first
    else {
        panic!("actual Session worker was not retained");
    };
    assert!(!slot_poisoned);
    assert_eq!(worker, expected);
    assert_eq!(consumers.joined, consumers.registered);
    {
        let state = original.worker.lock().await;
        assert!(state.handle.is_none());
        assert_eq!(state.observed, Some(expected));
    }
    assert_eq!(
        slot.stop_and_join_retired_session_tasks().await.unwrap(),
        first
    );
    drop(original);
    drop(slot);
    join_peer(peer).await;
}
