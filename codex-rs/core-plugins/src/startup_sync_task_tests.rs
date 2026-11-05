use super::StartupSyncTask;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

fn wait_for(mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !condition() {
        assert!(Instant::now() < deadline, "owned startup thread did not reach the expected state");
        std::thread::sleep(Duration::from_millis(1));
    }
}

#[test]
fn explicit_shutdown_joins_the_actual_thread_and_closes_further_admission() {
    let task = StartupSyncTask::default();
    let (started, ready) = mpsc::channel();
    let finished = Arc::new(AtomicBool::new(false));
    let worker_finished = Arc::clone(&finished);
    task.start(move |cancellation| {
        started.send(()).unwrap();
        wait_for(|| cancellation.is_cancelled());
        worker_finished.store(true, Ordering::Release);
    }).unwrap();
    ready.recv_timeout(Duration::from_secs(5)).unwrap();
    task.cancel();
    assert_eq!(task.shutdown(), Ok(()));
    assert!(finished.load(Ordering::Acquire));
    assert_eq!(task.shutdown(), Ok(()));
    assert!(task.start(|_| panic!("closed owner must not start another thread")).is_err());
}

#[test]
fn dropping_the_owner_cancels_and_joins_its_actual_thread() {
    let task = StartupSyncTask::default();
    let (started, ready) = mpsc::channel();
    let finished = Arc::new(AtomicBool::new(false));
    let worker_finished = Arc::clone(&finished);
    task.start(move |cancellation| {
        started.send(()).unwrap();
        wait_for(|| cancellation.is_cancelled());
        worker_finished.store(true, Ordering::Release);
    }).unwrap();
    ready.recv_timeout(Duration::from_secs(5)).unwrap();
    drop(task);
    assert!(finished.load(Ordering::Acquire));
}

#[test]
fn concurrent_shutdowns_wait_for_the_same_retained_thread_to_finish() {
    let task = Arc::new(StartupSyncTask::default());
    let (started, ready) = mpsc::channel();
    let (release, released) = mpsc::channel();
    task.start(move |cancellation| {
        started.send(()).unwrap();
        wait_for(|| cancellation.is_cancelled());
        released.recv_timeout(Duration::from_secs(5)).unwrap();
    }).unwrap();
    ready.recv_timeout(Duration::from_secs(5)).unwrap();
    std::thread::scope(|scope| {
        let (done, completions) = mpsc::channel();
        let first_task = Arc::clone(&task);
        let first_done = done.clone();
        let first = scope.spawn(move || {
            first_done.send(first_task.shutdown()).unwrap();
        });
        wait_for(|| task.state.lock().unwrap().joining.is_some());
        let (entering, entered) = mpsc::channel();
        let second_task = Arc::clone(&task);
        let second = scope.spawn(move || {
            entering.send(()).unwrap();
            done.send(second_task.shutdown()).unwrap();
        });
        entered.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(completions.try_recv(), Err(mpsc::TryRecvError::Empty));
        release.send(()).unwrap();
        assert_eq!(completions.recv_timeout(Duration::from_secs(5)).unwrap(), Ok(()));
        assert_eq!(completions.recv_timeout(Duration::from_secs(5)).unwrap(), Ok(()));
        first.join().unwrap();
        second.join().unwrap();
    });
    assert_eq!(task.shutdown(), Ok(()));
}
