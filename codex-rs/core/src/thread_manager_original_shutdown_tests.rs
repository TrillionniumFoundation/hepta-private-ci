//! Actual startup handles and loop ownership, without business capabilities.

use super::*;
use crate::session::original_loop_io_for_test;
use std::time::Duration;

fn enabled() -> Arc<OriginalThreadShutdownCustody> {
    let original = Arc::new(OriginalThreadShutdownCustody::default());
    original.enable(&ThreadRegistryState::default()).unwrap();
    original
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_start_history_prevents_late_strict_activation() {
    let original = OriginalThreadShutdownCustody::default();
    assert!(original.reserve_original_startup().unwrap().is_none());
    assert!(original.enable(&ThreadRegistryState::default()).is_err());
    assert!(original.seal_original_startups().is_err());
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn a_real_startup_panic_does_not_skip_another_owned_handle() {
    use std::io::Read;
    use std::os::unix::net::UnixStream;
    let original = enabled();
    let (owner, mut peer) = UnixStream::pair().unwrap();
    peer.set_nonblocking(true).unwrap();
    let (release, released) = tokio::sync::oneshot::channel();
    {
        let admission = original.reserve_original_startup().unwrap().unwrap();
        let worker = tokio::spawn(async { panic!("actual original startup component panic") });
        admission.retain_original_thread_startup_handle(worker);
    }
    {
        let admission = original.reserve_original_startup().unwrap().unwrap();
        let worker = tokio::spawn(async move {
            let _owner = owner;
            released.await.unwrap();
        });
        admission.retain_original_thread_startup_handle(worker);
    }
    let plan = original.seal_original_startups().unwrap();
    assert!(original.reserve_original_startup().is_err());
    let waiting = Arc::clone(&original);
    let mut cleaner = tokio::spawn(async move { waiting.join_original_sealed(plan).await });
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut cleaner)
            .await
            .is_err()
    );
    let mut byte = [0];
    assert!(matches!(peer.read(&mut byte), Err(error)
        if error.kind() == std::io::ErrorKind::WouldBlock));
    release.send(()).unwrap();
    let errors = cleaner.await.unwrap();
    assert_eq!(errors.len(), 1);
    assert!(
        matches!(errors[0].as_ref(), OriginalCoreTaskFailure::Join(error)
        if error.is_panic())
    );
    assert!(matches!(peer.read(&mut byte), Ok(0)));
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn a_captured_loop_outlives_its_original_io_and_a_cancelled_cleanup_waiter() {
    use codex_protocol::protocol::Op;
    use codex_protocol::protocol::Submission;
    use std::io::Read;
    use std::os::unix::net::UnixStream;
    let original = enabled();
    let (sender, receiver) = async_channel::bounded::<Submission>(1);
    let (owner, mut peer) = UnixStream::pair().unwrap();
    peer.set_nonblocking(true).unwrap();
    let (entered, started) = tokio::sync::oneshot::channel();
    let (release, released) = tokio::sync::oneshot::channel();
    let handle = tokio::spawn(async move {
        let _owner = owner;
        assert!(matches!(receiver.recv().await.unwrap().op, Op::Shutdown));
        entered.send(()).unwrap();
        released.await.unwrap();
    });
    let io = original_loop_io_for_test(sender, handle);
    original.retain_original_session_loop(&io).unwrap();
    drop(io);
    let plan = original.seal_original_startups().unwrap();
    let waiting = Arc::clone(&original);
    let cleaner = tokio::spawn(async move { waiting.join_original_sealed(plan).await });
    tokio::time::timeout(Duration::from_secs(2), started)
        .await
        .unwrap()
        .unwrap();
    cleaner.abort();
    assert!(cleaner.await.unwrap_err().is_cancelled());
    let mut byte = [0];
    assert!(matches!(peer.read(&mut byte), Err(error)
        if error.kind() == std::io::ErrorKind::WouldBlock));
    release.send(()).unwrap();
    let errors = original
        .join_original_sealed(original.seal_original_startups().unwrap())
        .await;
    assert!(errors.is_empty());
    assert!(matches!(peer.read(&mut byte), Ok(0)));
    assert!(
        original
            .join_original_sealed(original.seal_original_startups().unwrap())
            .await
            .is_empty()
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn an_admission_dropped_before_retaining_its_handle_permanently_refuses_start() {
    let original = enabled();
    drop(original.reserve_original_startup().unwrap().unwrap());
    assert!(original.reserve_original_startup().is_err());
    let errors = original
        .join_original_sealed(original.seal_original_startups().unwrap())
        .await;
    assert_eq!(errors.len(), 1);
    assert!(matches!(
        errors[0].as_ref(),
        OriginalCoreTaskFailure::State(_)
    ));
}
