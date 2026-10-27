use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::future::pending;
use std::path::Path;
use std::time::Duration;

use pretty_assertions::assert_eq;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::task::AbortOnDropHandle;
use tokio_util::task::TaskTracker;

use super::AppServerDrainHandle;
use super::OwnedTransportTasks;

const DEADLINE: Duration = Duration::from_secs(/*secs*/ 5);

#[test]
fn cloned_drain_handle_shares_counters_but_independent_owner_does_not() {
    let original = AppServerDrainHandle::new();
    let cloned = original.clone();
    let independent = AppServerDrainHandle::new();
    assert!(original.shares_counters_with(&cloned));
    assert!(cloned.shares_counters_with(&original));
    assert!(!original.shares_counters_with(&independent));
    assert!(!independent.shares_counters_with(&original));
}

struct HeldLock {
    file: Option<File>,
    released: Option<oneshot::Sender<()>>,
}

impl Drop for HeldLock {
    fn drop(&mut self) {
        // The notification follows physical owner destruction, not an abort request.
        drop(self.file.take());
        if let Some(released) = self.released.take() {
            let _ = released.send(());
        }
    }
}

struct LockedChild {
    task: JoinHandle<()>,
    started: oneshot::Receiver<()>,
    released: oneshot::Receiver<()>,
}

fn spawn_locked_child(path: &Path, tracker: &TaskTracker) -> LockedChild {
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .expect("create the original lock identity");
    file.try_lock().expect("take exclusive owner lock");
    let (started_tx, started) = oneshot::channel();
    let (released_tx, released) = oneshot::channel();
    let task = tracker.spawn(async move {
        let _owner = HeldLock {
            file: Some(file),
            released: Some(released_tx),
        };
        let _ = started_tx.send(());
        pending::<()>().await;
    });
    LockedChild {
        task,
        started,
        released,
    }
}

fn locked_contender(path: &Path) -> File {
    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("open the same existing lock file");
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    contender
}

async fn assert_reclaimed(tracker: &TaskTracker, released: oneshot::Receiver<()>, contender: File) {
    // TaskTracker is an independent observer of actual future destruction.
    // An abort request or a dropped JoinHandle is insufficient to pass this wait.
    timeout(DEADLINE, tracker.wait())
        .await
        .expect("all tracked child futures must actually finish");
    timeout(DEADLINE, released)
        .await
        .expect("owner destruction must be observed")
        .expect("lock owner must release before notifying");
    contender
        .try_lock()
        .expect("the same physical lock can be reacquired after child destruction");
}

#[tokio::test]
async fn drain_request_and_acknowledgement_do_not_acknowledge_completion() {
    let handle = AppServerDrainHandle::new();
    let observer = handle.clone();
    handle.observe_running_turns(/*running_turns*/ 2);
    handle.request_drain();
    timeout(DEADLINE, observer.wait_requested())
        .await
        .expect("the original request reaches the cloned observer");
    assert_eq!(
        (
            observer.running_turns(),
            observer.drained(),
            observer.completed()
        ),
        (2, false, false)
    );
    handle.mark_drained();
    handle.request_drain();
    drop(handle);
    assert_eq!(
        (
            observer.running_turns(),
            observer.drained(),
            observer.completed()
        ),
        (0, true, false)
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn dropping_transport_owner_reclaims_every_lock_without_completion() {
    let directory = tempfile::tempdir().expect("temporary owner directory");
    let tracker = TaskTracker::new();
    let drain = AppServerDrainHandle::new();
    let mut tasks = OwnedTransportTasks::default();
    let mut observations = Vec::new();
    for name in ["first.lock", "second.lock"] {
        let path = directory.path().join(name);
        let LockedChild {
            task,
            started,
            released,
        } = spawn_locked_child(&path, &tracker);
        tasks.0.push(task);
        timeout(DEADLINE, started)
            .await
            .expect("child must be polled")
            .expect("child reports its live owner");
        observations.push((released, locked_contender(&path)));
    }
    tracker.close();
    drain.request_drain();
    drain.mark_drained();
    assert!(!drain.completed());
    drop(tasks);
    for (released, contender) in observations {
        assert_reclaimed(&tracker, released, contender).await;
    }
    assert!(!drain.completed());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn aborted_parent_reclaims_owned_processor_lock_without_completion() {
    let directory = tempfile::tempdir().expect("temporary owner directory");
    let path = directory.path().join("processor.lock");
    let tracker = TaskTracker::new();
    let drain = AppServerDrainHandle::new();
    let LockedChild {
        task,
        started,
        released,
    } = spawn_locked_child(&path, &tracker);
    tracker.close();
    let processor = AbortOnDropHandle::new(task);
    let (parent_ready_tx, parent_ready) = oneshot::channel();
    let parent = AbortOnDropHandle::new(tokio::spawn(async move {
        let _processor = processor;
        let _ = parent_ready_tx.send(());
        pending::<()>().await;
    }));
    timeout(DEADLINE, parent_ready)
        .await
        .expect("parent must own its processor")
        .expect("parent entered its running future");
    timeout(DEADLINE, started)
        .await
        .expect("child must be polled")
        .expect("child reports its live owner");
    let contender = locked_contender(&path);
    drain.mark_drained();
    parent.abort();
    assert!(
        timeout(DEADLINE, parent)
            .await
            .expect("parent abort must be joined")
            .expect_err("parent must retain its cancelled outcome")
            .is_cancelled()
    );
    assert_reclaimed(&tracker, released, contender).await;
    assert!(!drain.completed());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn dropping_unpolled_parent_still_reclaims_immediately_owned_transport() {
    let directory = tempfile::tempdir().expect("temporary owner directory");
    let path = directory.path().join("early-exit.lock");
    let tracker = TaskTracker::new();
    let drain = AppServerDrainHandle::new();
    let LockedChild {
        task,
        started,
        released,
    } = spawn_locked_child(&path, &tracker);
    tracker.close();
    // Ownership precedes creation/polling of the fallible parent future.
    let transport = OwnedTransportTasks(vec![task]);
    let parent = async move {
        let _transport = transport;
        pending::<()>().await;
    };
    timeout(DEADLINE, started)
        .await
        .expect("child must be polled")
        .expect("child reports its live owner");
    let contender = locked_contender(&path);
    drop(parent);
    assert_reclaimed(&tracker, released, contender).await;
    assert!(!drain.completed());
}
