//! Component scope: real blocking handle, socket lifetime and original error.
//! No business owner, receipt, Root intent or completion capability is created.

use super::*;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;
use pretty_assertions::assert_eq;
use std::future::Future;
use std::io::Read;
use std::os::unix::net::UnixStream;
use std::sync::mpsc;
use std::task::Context;
use std::task::Waker;
use std::time::Duration;

#[tokio::test]
async fn ready_consumer_join_survives_cancelled_recording_waiter_and_counts_once() {
    let gate = SameActorPhaseGate::from_original_deadline(
        SameActorPhaseDeadline::at_original_service_start(Duration::from_secs(10)).unwrap(),
    )
    .unwrap();
    let jobs = OriginalConsumerJobs::new(&gate);
    let (held, mut probe) = UnixStream::pair().unwrap();
    probe.set_nonblocking(true).unwrap();
    let (entered, started) = tokio::sync::oneshot::channel();
    let (release, released) = mpsc::sync_channel(1);
    let admission = jobs.reserve_original_consumer().unwrap();
    let handle = tokio::task::spawn_blocking(move || {
        let _held = held;
        entered.send(()).unwrap();
        released.recv_timeout(Duration::from_secs(5)).unwrap();
        Err(AgentdRootAuthorityError::Refused)
    });
    let job = admission.retain_original_session_consumer_handle(handle);
    tokio::time::timeout(Duration::from_secs(5), started)
        .await
        .unwrap()
        .unwrap();
    assert!(
        matches!(probe.read(&mut [0]), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock)
    );
    let actual_join = {
        let state = job.state.lock().await;
        assert_eq!(state.observed, None);
        state.handle.as_ref().unwrap().clone()
    };
    let mut cancelled = Box::pin(jobs.receive_original_consumer(&job));
    let mut first = Box::pin(jobs.receive_original_consumer(&job));
    let mut second = Box::pin(jobs.receive_original_consumer(&job));
    {
        let mut context = Context::from_waker(Waker::noop());
        assert!(cancelled.as_mut().poll(&mut context).is_pending());
        assert!(first.as_mut().poll(&mut context).is_pending());
        assert!(second.as_mut().poll(&mut context).is_pending());
    }

    release.send(()).unwrap();
    let expected = Err(OriginalConsumerFailure::Owner(
        AgentdRootAuthorityError::Refused,
    ));
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(5), actual_join)
            .await
            .unwrap(),
        expected
    );
    assert_eq!(probe.read(&mut [0]).unwrap(), 0);
    {
        // These waiters already borrowed the real handle before it finished.
        // Its Shared is now Ready; this lock pins their SECOND lock attempt.
        let state = job.state.lock().await;
        assert_eq!(state.observed, None);
        assert_eq!(state.handle.as_ref().unwrap().peek(), Some(&expected));
        let mut context = Context::from_waker(Waker::noop());
        assert!(cancelled.as_mut().poll(&mut context).is_pending());
        assert!(first.as_mut().poll(&mut context).is_pending());
        assert!(second.as_mut().poll(&mut context).is_pending());
        drop(cancelled);
        assert_eq!(state.observed, None);
        assert_eq!(state.handle.as_ref().unwrap().peek(), Some(&expected));
        let registry = jobs.state.lock().unwrap();
        assert_eq!((registry.registered, registry.joined), (1, 0));
        assert_eq!(registry.retained.len(), 1);
        assert!(Arc::ptr_eq(&registry.retained[0], &job));
    }
    // No lock is held across these awaits. Both record the same actual job;
    // the registry must remove that Arc and increment joined exactly once.
    let (first, second) = tokio::time::timeout(Duration::from_secs(5), async {
        tokio::join!(first, second)
    })
    .await
    .unwrap();
    assert_eq!(first, Err(AgentdRootAuthorityError::Refused));
    assert_eq!(second, Err(AgentdRootAuthorityError::Refused));
    {
        let state = job.state.lock().await;
        assert!(state.handle.is_none());
        assert_eq!(state.observed, Some(expected));
    }
    assert_eq!(
        jobs.receive_original_consumer(&job).await,
        Err(AgentdRootAuthorityError::Refused)
    );
    let summary = jobs.join_stopped_consumers().await.unwrap();
    assert_eq!((summary.registered, summary.joined), (1, 1));
    assert_eq!(
        summary.first_observed_failure,
        Some(OriginalConsumerFailure::Owner(
            AgentdRootAuthorityError::Refused
        ))
    );
    assert!(!summary.admission_poisoned);
    assert!(jobs.state.lock().unwrap().retained.is_empty());
}
