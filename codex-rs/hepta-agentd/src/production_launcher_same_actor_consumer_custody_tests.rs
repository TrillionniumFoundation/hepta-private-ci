//! Real blocking/FD custody components; no authority, Root grant or business
//! success is constructed. The original task returns an explicit failure.

use super::*;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;
use std::io::Read;
use std::os::unix::net::UnixStream;
use std::sync::mpsc;
use std::time::Duration;

fn gate() -> Arc<SameActorPhaseGate> {
    SameActorPhaseGate::from_original_deadline(
        SameActorPhaseDeadline::at_original_service_start(Duration::from_secs(10)).unwrap(),
    )
    .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unpolled_receive_keeps_real_task_and_fd_until_cleanup_join() {
    let gate = gate();
    let registry = Arc::new(OriginalBootstrapConsumers::new());
    let (owner, mut peer) = UnixStream::pair().unwrap();
    peer.set_nonblocking(true).unwrap();
    let (entered, started) = mpsc::sync_channel(1);
    let (release, released) = mpsc::sync_channel(1);
    let admission = registry
        .reserve(OriginalBootstrapConsumerKind::Device, &gate)
        .unwrap();
    let worker = tokio::task::spawn_blocking(move || {
        let _owner = owner;
        entered.send(()).unwrap();
        let _ = released.recv();
        Err(AgentdError::GenerationFenced(
            "actual component consumer refused".into(),
        ))
    });
    let job = admission.retain_original_bootstrap_consumer_handle(worker);
    started.recv_timeout(Duration::from_secs(2)).unwrap();
    drop(job.receive_original());
    assert!(gate.require_open().is_err());
    let mut byte = [0];
    assert!(
        matches!(peer.read(&mut byte), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock)
    );
    let actual = Arc::clone(&registry);
    let mut cleanup = tokio::spawn(async move { actual.join_and_release().await });
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut cleanup)
            .await
            .is_err()
    );
    release.send(()).unwrap();
    let result = cleanup.await.unwrap();
    assert!(matches!(result, Err(AgentdError::GenerationFenced(message))
        if message == "actual component consumer refused"));
    assert!(matches!(peer.read(&mut byte), Ok(0)));
    let state = job.state.lock().unwrap();
    assert!(state.joined && job.completion.peek().is_some() && state.output.is_none());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn one_actual_consumer_kind_cannot_be_spawned_twice() {
    let gate = gate();
    let registry = OriginalBootstrapConsumers::new();
    let admission = registry
        .reserve(OriginalBootstrapConsumerKind::Device, &gate)
        .unwrap();
    let worker = tokio::task::spawn_blocking(|| {
        Err(AgentdError::GenerationFenced("first actual refusal".into()))
    });
    let job = admission.retain_original_bootstrap_consumer_handle(worker);
    assert!(
        registry
            .reserve(OriginalBootstrapConsumerKind::Device, &gate)
            .is_err()
    );
    assert!(
        registry
            .reserve(OriginalBootstrapConsumerKind::Notes, &gate)
            .is_err()
    );
    assert!(registry.join_and_release().await.is_err());
    let state = job.state.lock().unwrap();
    assert!(state.joined && job.completion.peek().is_some());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn panicked_consumer_does_not_skip_the_other_actual_join() {
    let gate = gate();
    let registry = Arc::new(OriginalBootstrapConsumers::new());
    let first = registry
        .reserve(OriginalBootstrapConsumerKind::Device, &gate)
        .unwrap()
        .retain_original_bootstrap_consumer_handle(tokio::task::spawn_blocking(
            || -> Result<FinalUseAuthority, AgentdError> {
                panic!("actual component consumer panic");
            },
        ));
    let (owner, mut peer) = UnixStream::pair().unwrap();
    peer.set_nonblocking(true).unwrap();
    let (release, released) = mpsc::sync_channel(1);
    let second = registry
        .reserve(OriginalBootstrapConsumerKind::Notes, &gate)
        .unwrap()
        .retain_original_bootstrap_consumer_handle(tokio::task::spawn_blocking(move || {
            let _owner = owner;
            let _ = released.recv();
            Err(AgentdError::GenerationFenced(
                "second actual refusal".into(),
            ))
        }));
    let actual = Arc::clone(&registry);
    let mut cleanup = tokio::spawn(async move { actual.join_and_release().await });
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut cleanup)
            .await
            .is_err()
    );
    let mut byte = [0];
    assert!(
        matches!(peer.read(&mut byte), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock)
    );
    release.send(()).unwrap();
    assert!(matches!(
        cleanup.await.unwrap(),
        Err(AgentdError::Protocol(_))
    ));
    assert!(matches!(peer.read(&mut byte), Ok(0)));
    assert!(first.state.lock().unwrap().joined);
    assert!(first.completion.peek().is_some());
    assert!(second.state.lock().unwrap().joined);
    assert!(second.completion.peek().is_some());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelled_cleanup_retains_one_original_consumer_and_its_error() {
    let gate = gate();
    let registry = Arc::new(OriginalBootstrapConsumers::new());
    let (owner, mut peer) = UnixStream::pair().unwrap();
    peer.set_nonblocking(true).unwrap();
    let (entered, started) = mpsc::sync_channel(1);
    let (release, released) = mpsc::sync_channel(1);
    let executions = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let calls = Arc::clone(&executions);
    let admission = registry
        .reserve(OriginalBootstrapConsumerKind::Device, &gate)
        .unwrap();
    let worker = tokio::task::spawn_blocking(move || {
        let _owner = owner;
        calls.fetch_add(1, std::sync::atomic::Ordering::AcqRel);
        entered.send(()).unwrap();
        let _ = released.recv();
        Err(AgentdError::GenerationFenced(
            "same original consumer error after waiter cancellation".into(),
        ))
    });
    let job = admission.retain_original_bootstrap_consumer_handle(worker);
    drop(job);
    started.recv_timeout(Duration::from_secs(2)).unwrap();

    let first_registry = Arc::clone(&registry);
    let first = tokio::spawn(async move { first_registry.join_and_release().await });
    tokio::time::timeout(Duration::from_secs(2), gate.cancelled())
        .await
        .unwrap();
    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());

    let mut byte = [0];
    assert!(
        matches!(peer.read(&mut byte), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock)
    );
    assert!(executions.load(std::sync::atomic::Ordering::Acquire) == 1);

    let second_registry = Arc::clone(&registry);
    let mut second = tokio::spawn(async move { second_registry.join_and_release().await });
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut second)
            .await
            .is_err()
    );
    release.send(()).unwrap();
    let result = tokio::time::timeout(Duration::from_secs(2), second)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(result, Err(AgentdError::GenerationFenced(message))
        if message == "same original consumer error after waiter cancellation"));
    assert!(executions.load(std::sync::atomic::Ordering::Acquire) == 1);
    assert!(matches!(peer.read(&mut byte), Ok(0)));
}
