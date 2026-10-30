use super::CoalescingWake;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::mpsc;
use tokio::sync::oneshot;

#[tokio::test]
async fn newer_owner_is_not_lost_after_old_barrier_completes_before_admission() {
    let wake = Arc::new(CoalescingWake::default());
    let (first_done, first_wait) = oneshot::channel();
    let (second_done, second_wait) = oneshot::channel();
    let (before_admission, admission_wait) = oneshot::channel();
    let (allow_admission, admission_gate) = oneshot::channel();
    assert!(wake.register_with(|| async { first_wait.await.unwrap() }));
    let worker_wake = Arc::clone(&wake);
    let worker = tokio::spawn(async move {
        worker_wake.next_barrier().unwrap().await;
        before_admission.send(()).unwrap();
        admission_gate.await.unwrap();
        // The first admission can reject because a newer owner now fences the
        // thread. That owner's callback must still wake this existing worker.
        worker_wake.next_barrier().unwrap().await;
        assert!(worker_wake.next_barrier().is_none());
    });
    first_done.send(()).unwrap();
    admission_wait.await.unwrap();
    assert!(!wake.register_with(|| async { second_wait.await.unwrap() }));
    allow_admission.send(()).unwrap();
    second_done.send(()).unwrap();
    worker.await.unwrap();
    // Empty retirement and a fresh generation cannot lose the new worker.
    assert!(wake.register_with(|| async {}));
    wake.next_barrier().unwrap().await;
    assert!(wake.next_barrier().is_none());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn capture_order_cannot_overwrite_a_newer_pending_owner() {
    let wake = Arc::new(CoalescingWake::default());
    assert!(wake.register_with(|| async {}));
    wake.next_barrier().unwrap().await;
    let captures = Arc::new(Mutex::new(Vec::new()));
    let (capturing_old, old_started) = mpsc::channel();
    let (release_old, old_gate) = mpsc::channel();
    let old_wake = Arc::clone(&wake);
    let old_captures = Arc::clone(&captures);
    let old = std::thread::spawn(move || {
        assert!(!old_wake.register_with(|| {
            old_captures.lock().unwrap().push("old");
            capturing_old.send(()).unwrap();
            old_gate.recv().unwrap();
            async {}
        }));
    });
    old_started.recv().unwrap();
    let (new_attempt, attempted) = mpsc::channel();
    let (new_done, new_wait) = oneshot::channel();
    let new_wake = Arc::clone(&wake);
    let new_captures = Arc::clone(&captures);
    let new = std::thread::spawn(move || {
        new_attempt.send(()).unwrap();
        assert!(!new_wake.register_with(|| {
            new_captures.lock().unwrap().push("new");
            async { new_wait.await.unwrap() }
        }));
    });
    attempted.recv().unwrap();
    release_old.send(()).unwrap();
    old.join().unwrap();
    new.join().unwrap();
    assert_eq!(*captures.lock().unwrap(), vec!["old", "new"]);
    // A pre-captured old future could previously replace this newer owner.
    // Dropping its sender would then fail, making the lost observation visible.
    new_done.send(()).unwrap();
    wake.next_barrier().unwrap().await;
    assert!(wake.next_barrier().is_none());
}
