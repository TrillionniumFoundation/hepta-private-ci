//! Deadline and worker cleanup only; these fixtures grant no Root authority.
use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[tokio::test]
async fn expired_launch_admission_consumes_carrier_before_receiving() {
    let directory = tempfile::tempdir().unwrap();
    let identity = crate::HostAuthorityRegisteredIdentity {
        agent_id: AgentId::parse("019a2a19-0000-7000-8000-000000000005").unwrap(),
        spawn_generation: 1,
        fleet_root: directory.path().join("fleet"),
        workspace: directory.path().join("workspace"),
        resources: ResourceBudget::local_default(),
    }
    .identity()
    .unwrap();
    let (peer, carrier) = UnixDatagram::pair().unwrap();
    let error = receive_learning_checkpoint_before(carrier, identity, Instant::now())
        .await
        .err()
        .expect("late admission must fail before reading any carrier");
    assert_eq!(error.kind(), io::ErrorKind::TimedOut);
    assert!(peer.send(b"late handoff").is_err());
}

#[tokio::test]
async fn deadline_shutdown_joins_worker_and_drops_late_success() {
    struct Completed(Arc<AtomicBool>);
    impl Drop for Completed {
        fn drop(&mut self) {
            self.0.store(true, Ordering::Release);
        }
    }
    let (mut worker_socket, _peer) = std::os::unix::net::UnixStream::pair().unwrap();
    let cancel = worker_socket.try_clone().unwrap();
    let discarded = Arc::new(AtomicBool::new(false));
    let completed = Completed(discarded.clone());
    let (entered, started) = tokio::sync::oneshot::channel();
    let worker = tokio::task::spawn_blocking(move || {
        entered.send(()).unwrap();
        let mut byte = [0];
        assert_eq!(worker_socket.read(&mut byte)?, 0);
        Ok(completed)
    });
    started.await.unwrap();
    let error = AdmissionBudget::Before(Instant::now())
        .complete(worker, move || cancel.shutdown(Shutdown::Both))
        .await
        .err()
        .expect("the late successful value must not escape admission");
    assert_eq!(error.kind(), io::ErrorKind::TimedOut);
    assert!(discarded.load(Ordering::Acquire));
}
