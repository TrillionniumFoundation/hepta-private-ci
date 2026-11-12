//! Real join/cancellation components. These are ordinary Tokio task handles,
//! not Root, business, role, or Session::spawn qualification fixtures.

use super::*;
use std::error::Error as _;
use std::time::Duration;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_loop_panic_is_preserved_as_the_original_error_source() {
    let (sender, _receiver) = async_channel::bounded(1);
    let handle = tokio::spawn(async { panic!("actual original loop component panic") });
    let io = original_loop_io_for_test(sender, handle);
    let original = io.retain_original_loop_shutdown();
    drop(io);
    let error = original.join_original_loop().await.unwrap_err();
    let source = error.source().unwrap().downcast_ref::<JoinError>().unwrap();
    assert!(source.is_panic());
    assert!(!source.is_cancelled());
    let again = original.join_original_loop().await.unwrap_err();
    assert!(Arc::ptr_eq(&error, &again));
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelled_loop_wait_retains_the_same_owner_until_actual_join() {
    use std::io::Read;
    use std::os::unix::net::UnixStream;
    let (sender, receiver) = async_channel::bounded::<Submission>(2);
    let (owner, mut peer) = UnixStream::pair().unwrap();
    peer.set_nonblocking(true).unwrap();
    let (entered, started) = tokio::sync::oneshot::channel();
    let (release, released) = tokio::sync::oneshot::channel();
    let handle = tokio::spawn(async move {
        let _owner = owner;
        assert!(matches!(receiver.recv().await.unwrap().op, Op::Shutdown));
        entered.send(()).unwrap();
        released.await.unwrap();
        assert!(receiver.try_recv().is_err());
    });
    let io = original_loop_io_for_test(sender, handle);
    let original = io.retain_original_loop_shutdown();
    drop(io);
    let waiting = Arc::clone(&original);
    let waiter = tokio::spawn(async move { waiting.join_original_loop().await });
    tokio::time::timeout(Duration::from_secs(2), started).await.unwrap().unwrap();
    waiter.abort();
    assert!(waiter.await.unwrap_err().is_cancelled());
    let mut byte = [0];
    assert!(matches!(peer.read(&mut byte), Err(error)
        if error.kind() == std::io::ErrorKind::WouldBlock));
    release.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(2), original.join_original_loop())
        .await.unwrap().unwrap();
    assert!(matches!(peer.read(&mut byte), Ok(0)));
    original.join_original_loop().await.unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn missing_side_record_is_refused_even_after_the_real_unit_future_completes() {
    let (sender, receiver) = async_channel::bounded::<Submission>(1);
    let handle = tokio::spawn(async move {
        assert!(matches!(receiver.recv().await.unwrap().op, Op::Shutdown));
    });
    let termination = super::super::session_loop_termination_from_handle(handle);
    let original = OriginalSessionLoopShutdown::new(sender, termination, None);
    let error = original.join_original_loop().await.unwrap_err();
    assert!(matches!(error.as_ref(), OriginalCoreTaskFailure::State(_)));
}
