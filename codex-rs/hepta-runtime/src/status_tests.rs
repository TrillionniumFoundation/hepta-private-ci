use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

use anyhow::Result;
use codex_hepta_paths::HeptaStateRoot;

use super::HeptaRuntime;
use super::MAX_STATUS_BYTES;
use super::RuntimeStateAdapter;
use super::RuntimeStateStatus;

fn state_status() -> RuntimeStateStatus {
    RuntimeStateStatus {
        adapter: "status-test",
        schema_version: 5,
        outcome_generation: 3,
        preference_generation: 4,
        runtime_snapshot_version: 1,
        runtime_snapshot_generation: 9,
        integrity_binding_present: true,
        integrity_verification: "fixture-only",
        open_mode: "read-only-test",
    }
}

#[derive(Debug)]
struct CountingAdapter(AtomicUsize);

impl RuntimeStateAdapter for CountingAdapter {
    fn status(&self) -> RuntimeStateStatus {
        self.0.fetch_add(1, Ordering::SeqCst);
        state_status()
    }
}

#[test]
fn status_observes_once_without_creating_state_and_preserves_wire() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("not-created");
    let state = Arc::new(CountingAdapter(AtomicUsize::new(0)));
    let runtime = HeptaRuntime::from_adapter(HeptaStateRoot::parse(&path)?, state.clone());
    assert_eq!(state.0.load(Ordering::SeqCst), 0);
    let actual = runtime.status_json()?;
    assert_eq!(state.0.load(Ordering::SeqCst), 1);
    assert_eq!(actual, serde_json::to_vec(&runtime.status())?);
    assert!(!path.exists());
    Ok(())
}

#[test]
fn oversized_status_remains_rejected() -> Result<()> {
    let path = std::env::temp_dir().join("x".repeat(MAX_STATUS_BYTES));
    let runtime = HeptaRuntime::from_adapter(
        HeptaStateRoot::parse(path)?,
        Arc::new(CountingAdapter(AtomicUsize::new(0))),
    );
    assert!(runtime.status_json().is_err());
    Ok(())
}

#[derive(Debug)]
struct ConcurrentAdapter {
    calls: AtomicUsize,
    entered: mpsc::SyncSender<()>,
    release: Mutex<mpsc::Receiver<()>>,
}

impl RuntimeStateAdapter for ConcurrentAdapter {
    fn status(&self) -> RuntimeStateStatus {
        if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
            self.entered.send(()).expect("signal first observation");
            self.release
                .lock()
                .expect("release lock")
                .recv_timeout(Duration::from_secs(5))
                .expect("release first observation");
        }
        state_status()
    }
}

#[test]
fn concurrent_status_does_not_acquire_an_unrelated_dispatch_lock() -> Result<()> {
    let (entered_tx, entered_rx) = mpsc::sync_channel(1);
    let (release_tx, release_rx) = mpsc::sync_channel(1);
    let adapter = Arc::new(ConcurrentAdapter {
        calls: AtomicUsize::new(0),
        entered: entered_tx,
        release: Mutex::new(release_rx),
    });
    let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-concurrent-status"))?;
    let runtime = HeptaRuntime::from_adapter(root, adapter.clone());
    let first_runtime = runtime.clone();
    let first = std::thread::spawn(move || first_runtime.status_json());
    entered_rx.recv_timeout(Duration::from_secs(5))?;
    let second = runtime.status_json();
    // Always release and join before asserting, including a second-call failure.
    release_tx.send(())?;
    let first = first.join().expect("status observer thread");
    assert_eq!(first?, second?);
    assert_eq!(adapter.calls.load(Ordering::SeqCst), 2);
    Ok(())
}
