use super::tests::spawn_test_process;
use super::tests::spawn_test_process_with_session;
use super::*;
use codex_utils_pty::ProcessDriver;
use pretty_assertions::assert_eq;
use tokio::sync::broadcast;
use tokio::sync::oneshot;
use tokio::time::timeout;

// Hold the real publication lock on a blocking worker. The async test receives
// the original entry only after the lock is held; dropping its release sender
// also unlocks the worker if an assertion unwinds the test.
struct HeldProcessMap {
    custody: Arc<ProcessCustody>,
    accepted_stdin_write_ids: Arc<Mutex<AcceptedStdinWriteIds>>,
    release_tx: std::sync::mpsc::Sender<()>,
    task: tokio::task::JoinHandle<()>,
}

impl HeldProcessMap {
    async fn acquire(backend: &LocalProcess, process_id: &ProcessId) -> Self {
        let inner = Arc::clone(&backend.inner);
        let process_id = process_id.clone();
        let (ready_tx, ready_rx) = oneshot::channel();
        let (release_tx, release_rx) = std::sync::mpsc::channel();
        let task = tokio::task::spawn_blocking(move || {
            let processes = inner.processes.blocking_lock();
            let Some(ProcessEntry::Running(running)) = processes.get(&process_id) else {
                panic!("fixture process must be running");
            };
            if ready_tx
                .send((
                    Arc::clone(&running.custody),
                    Arc::clone(&running.accepted_stdin_write_ids),
                ))
                .is_err()
            {
                return;
            }
            let _ = release_rx.recv();
            drop(processes);
        });
        let (custody, accepted_stdin_write_ids) = ready_rx
            .await
            .expect("blocking fixture holds the original process-map lock");
        Self {
            custody,
            accepted_stdin_write_ids,
            release_tx,
            task,
        }
    }

    async fn release(self) {
        drop(self.release_tx);
        self.task.await.expect("original process-map lock released");
    }
}

#[tokio::test]
async fn blocked_stdin_reservation_wakes_for_retained_outcome() {
    for native_exit in [Some(47), None] {
        let backend = LocalProcess::default();
        let (writer_tx, mut writer_rx) = mpsc::channel(1);
        writer_tx
            .try_send(vec![1])
            .expect("fill the original input capacity");
        let (_stdout_tx, stdout_rx) = broadcast::channel(1);
        let (_stderr_tx, stderr_rx) = broadcast::channel(1);
        let (_driver_exit_tx, driver_exit_rx) = oneshot::channel();
        let session = codex_utils_pty::spawn_from_driver(ProcessDriver {
            writer_tx,
            stdout_rx,
            stderr_rx: Some(stderr_rx),
            exit_rx: driver_exit_rx,
            terminator: None,
            writer_handle: None,
            resizer: None,
            #[cfg(windows)]
            tty: false,
        })
        .session;
        let mut process =
            spawn_test_process_with_session(&backend, "blocked-stdin-observer", session).await;
        {
            let mut processes = backend.inner.processes.lock().await;
            let Some(ProcessEntry::Running(running)) = processes.get_mut(&process.process_id)
            else {
                panic!("fixture process must be running");
            };
            running.pipe_stdin = true;
        }
        let mut write = std::pin::pin!(backend.exec_write(WriteParams {
            process_id: process.process_id.clone(),
            chunk: vec![2].into(),
            write_id: "blocked-write".to_string(),
        }));
        let first_poll = std::future::poll_fn(|cx| {
            std::task::Poll::Ready(std::future::Future::poll(write.as_mut(), cx))
        })
        .await;
        assert!(
            first_poll.is_pending(),
            "the original full input channel must block reserve"
        );
        let held_map = HeldProcessMap::acquire(&backend, &process.process_id).await;
        let custody = Arc::clone(&held_map.custody);
        if let Some(code) = native_exit {
            process.exit(code);
        } else {
            drop(process.exit_tx.take());
        }
        timeout(Duration::from_secs(1), async {
            while custody.observed_exit_code().is_none() && !custody.outcome_is_unknown() {
                tokio::task::yield_now().await;
            }
            process.exit_task.abort();
            assert!(
                (&mut process.exit_task)
                    .await
                    .expect_err("publisher cancelled at map lock")
                    .is_cancelled()
            );
            let response = write.as_mut().await;
            if native_exit.is_some() {
                assert_eq!(
                    response.expect("known exit closes pending input").status,
                    WriteStatus::StdinClosed
                );
            } else {
                assert!(
                    response
                        .expect_err("unknown outcome refuses pending input")
                        .message
                        .contains("unknown")
                );
            }
        })
        .await
        .expect("original retained-outcome observation budget");
        assert_eq!(writer_rx.try_recv().expect("original queued byte"), vec![1]);
        assert!(matches!(
            writer_rx.try_recv(),
            Err(mpsc::error::TryRecvError::Empty)
        ));
        assert!(
            !held_map
                .accepted_stdin_write_ids
                .lock()
                .await
                .contains("blocked-write")
        );
        held_map.release().await;
        backend.shutdown().await;
    }
}

#[tokio::test]
async fn actual_exit_fact_survives_cancelled_map_publication() {
    let backend = LocalProcess::default();
    let mut process = spawn_test_process(&backend, "cancelled-exit-publication").await;
    let accepted_stdin_write_ids = {
        let mut processes = backend.inner.processes.lock().await;
        let Some(ProcessEntry::Running(running)) = processes.get_mut(&process.process_id) else {
            panic!("fixture process must be running");
        };
        running.pipe_stdin = true;
        Arc::clone(&running.accepted_stdin_write_ids)
    };
    accepted_stdin_write_ids
        .lock()
        .await
        .remember("already-accepted".to_string());
    let held_map = HeldProcessMap::acquire(&backend, &process.process_id).await;
    let custody = Arc::clone(&held_map.custody);
    process.exit(47);
    timeout(Duration::from_secs(1), async {
        while custody.observed_exit_code().is_none() {
            tokio::task::yield_now().await;
        }
        // The native-result receiver has consumed its value, but cannot yet
        // obtain the original process-map lock. Abort at that real await point.
        process.exit_task.abort();
        assert!(
            (&mut process.exit_task)
                .await
                .expect_err("publisher cancelled")
                .is_cancelled()
        );
    })
    .await
    .expect("original exit publication observation budget");
    assert_eq!(custody.observed_exit_code(), Some(47));
    held_map.release().await;
    let read = backend
        .exec_read(ReadParams {
            process_id: process.process_id.clone(),
            after_seq: None,
            max_bytes: None,
            wait_ms: Some(0),
        })
        .await
        .expect("read original retained exit fact");
    assert!(read.exited);
    assert_eq!(read.exit_code, Some(47));
    assert!(!read.closed);
    assert_eq!(read.failure, None);
    let rejected = backend
        .exec_write(WriteParams {
            process_id: process.process_id.clone(),
            chunk: vec![1].into(),
            write_id: "after-observed-exit".to_string(),
        })
        .await
        .expect("the original retained exit closes new input");
    assert_eq!(rejected.status, WriteStatus::StdinClosed);
    let retried = backend
        .exec_write(WriteParams {
            process_id: process.process_id.clone(),
            chunk: vec![2].into(),
            write_id: "already-accepted".to_string(),
        })
        .await
        .expect("an already accepted write remains acknowledged without resending");
    assert_eq!(retried.status, WriteStatus::Accepted);
    let next = backend
        .inner
        .custody
        .reserve(Arc::clone(&backend.inner))
        .expect("the same observed owner has released its reservation");
    drop(next);
    backend.shutdown().await;
}

#[tokio::test]
async fn cancelling_before_effect_releases_only_the_unused_reservation() {
    let backend = LocalProcess::default();
    let launch = backend
        .inner
        .custody
        .reserve(Arc::clone(&backend.inner))
        .expect("reserve before any backend effect");
    let task = tokio::spawn(async move {
        let _launch = launch;
        std::future::pending::<()>().await;
    });
    // A current-thread test can abort before the future's first poll. The
    // guard must already be owned by that future, rather than built inside it.
    task.abort();
    let cancelled = timeout(Duration::from_secs(1), task)
        .await
        .expect("original task cancellation budget")
        .expect_err("task cancelled");
    assert!(cancelled.is_cancelled());
    assert!(backend.inner.processes.lock().await.is_empty());
    let next = backend
        .inner
        .custody
        .reserve(Arc::clone(&backend.inner))
        .expect("no effect occurred; admission remains available");
    drop(next);
}

#[tokio::test]
async fn cancelled_exit_watcher_retains_unknown_and_wakes_observers() {
    let backend = LocalProcess::default();
    let mut process = spawn_test_process(&backend, "cancelled-exit-watch").await;
    let (owner, mut wake, mut events) = {
        let processes = backend.inner.processes.lock().await;
        let Some(ProcessEntry::Running(running)) = processes.get(&process.process_id) else {
            panic!("fixture process must be running");
        };
        (
            Arc::downgrade(&running.session),
            running.wake_tx.subscribe(),
            running.events.subscribe(),
        )
    };
    process.exit_task.abort();
    timeout(Duration::from_secs(1), async {
        assert!( (&mut process.exit_task).await.expect_err("watcher cancelled").is_cancelled());
        wake.changed().await.expect("unknown outcome wakes the original reader");
        assert!(matches!(events.recv().await, Ok(ExecProcessEvent::Failed(message)) if message == custody::UNKNOWN_OUTCOME));
        let read = backend.exec_read(ReadParams {
            process_id: process.process_id.clone(), after_seq: None,
            max_bytes: None, wait_ms: Some(0),
        }).await.expect("read retained unknown process");
        assert_eq!(read.failure.as_deref(), Some(custody::UNKNOWN_OUTCOME));
        assert!(!read.exited);
        assert_eq!(read.exit_code, None);
        assert!(!read.closed);
    }).await.expect("original cancellation observation budget");
    assert!(owner.upgrade().is_some());
    assert!(
        backend
            .inner
            .custody
            .reserve(Arc::clone(&backend.inner))
            .is_err()
    );
    backend.shutdown().await;
    assert!(owner.upgrade().is_some());
}

#[tokio::test]
async fn lost_exit_observation_retains_owner_and_fences_other_sessions() {
    let backend = LocalProcess::default();
    let mut process = spawn_test_process(&backend, "lost-exit-observation").await;
    let owner = {
        let processes = backend.inner.processes.lock().await;
        let Some(ProcessEntry::Running(running)) = processes.get(&process.process_id) else {
            panic!("fixture process must be running");
        };
        Arc::downgrade(&running.session)
    };
    drop(process.exit_tx.take());
    let read = tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            let response = backend
                .exec_read(ReadParams {
                    process_id: process.process_id.clone(),
                    after_seq: None,
                    max_bytes: None,
                    wait_ms: Some(10),
                })
                .await
                .expect("retained read");
            if response.failure.is_some() {
                break response;
            }
        }
    })
    .await
    .expect("failure observation budget");
    assert_eq!(
        read.failure.as_deref(),
        Some("process exit observation lost")
    );
    assert!(!read.exited);
    assert_eq!(read.exit_code, None);
    assert!(!read.closed);
    let (tx, _rx) = mpsc::channel(16);
    let second = LocalProcess::with_runtime_paths_and_custody(
        RpcNotificationSender::new(tx),
        ExecServerTelemetry::default(),
        None,
        Arc::clone(&backend.inner.custody),
    );
    assert!(
        second
            .inner
            .custody
            .reserve(Arc::clone(&second.inner))
            .is_err()
    );
    backend.shutdown().await;
    assert!(owner.upgrade().is_some());
    assert!(
        backend
            .inner
            .processes
            .lock()
            .await
            .contains_key(&process.process_id)
    );
    assert!(
        second
            .inner
            .custody
            .reserve(Arc::clone(&second.inner))
            .is_err()
    );
}

#[tokio::test]
async fn actual_exit_releases_only_its_original_registry_reservation() {
    let backend = LocalProcess::default();
    let mut first = spawn_test_process(&backend, "confirmed-exit").await;
    let mut second = spawn_test_process(&backend, "unknown-exit").await;
    drop(second.exit_tx.take());
    first.exit(23);
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            let first_read = backend
                .exec_read(ReadParams {
                    process_id: first.process_id.clone(),
                    after_seq: None,
                    max_bytes: None,
                    wait_ms: Some(10),
                })
                .await
                .expect("first read");
            let second_read = backend
                .exec_read(ReadParams {
                    process_id: second.process_id.clone(),
                    after_seq: None,
                    max_bytes: None,
                    wait_ms: Some(10),
                })
                .await
                .expect("second read");
            if first_read.exited && second_read.failure.is_some() {
                assert_eq!(first_read.exit_code, Some(23));
                assert!(!second_read.exited);
                assert!(!second_read.closed);
                break;
            }
        }
    })
    .await
    .expect("exit observation fixture budget");
    assert!(
        backend
            .inner
            .custody
            .reserve(Arc::clone(&backend.inner))
            .is_err()
    );
    backend.shutdown().await;
}
