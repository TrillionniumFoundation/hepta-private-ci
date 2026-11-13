//! Actual concurrent scope, poison and failure propagation tests for the
//! production coordination helper. These do not construct a Root authority.

use super::InitialLaneAdmission;
use crate::AgentdError;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Barrier;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

const WATCHDOG: Duration = Duration::from_secs(2);
struct Fixture {
    gate: InitialLaneAdmission,
    data: Mutex<u64>,
    fenced: AtomicBool,
}
fn fixture() -> anyhow::Result<Arc<Fixture>> {
    Ok(Arc::new(Fixture {
        gate: InitialLaneAdmission::for_artifact()?,
        data: Mutex::new(7),
        fenced: AtomicBool::new(false),
    }))
}
fn end() -> Instant {
    Instant::now() + Duration::from_millis(500)
}
fn failure(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

#[test]
fn artifact_admission_serializes_complete_scopes_without_fencing() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let barrier = Arc::new(Barrier::new(/*n*/ 5));
    let active = Arc::new(AtomicUsize::new(0));
    let checks = Arc::new(AtomicUsize::new(0));
    let (entered, observations) = mpsc::channel();
    let mut workers = Vec::new();
    let mut releases = Vec::new();
    for id in 0..4 {
        let fixture = fixture.clone();
        let barrier = barrier.clone();
        let active = active.clone();
        let checks = checks.clone();
        let entered = entered.clone();
        let (release, proceed) = mpsc::channel();
        releases.push(release);
        workers.push(std::thread::spawn(move || {
            let deadline = end();
            barrier.wait();
            fixture.gate.with_original_action(
                &fixture.data,
                &fixture.fenced,
                deadline,
                |data| {
                    assert_eq!(*data, 7);
                    checks.fetch_add(1, Ordering::AcqRel);
                    Ok(())
                },
                |_| {
                    assert_eq!(active.fetch_add(1, Ordering::AcqRel), 0);
                    entered.send(id).map_err(failure)?;
                    proceed.recv_timeout(WATCHDOG).map_err(failure)?;
                    assert_eq!(active.fetch_sub(1, Ordering::AcqRel), 1);
                    Ok(id)
                },
            )
        }));
    }
    barrier.wait();
    for _ in 0..4 {
        let id = observations.recv_timeout(WATCHDOG)?;
        assert!(matches!(
            observations.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));
        releases[id].send(())?;
    }
    let mut results = Vec::new();
    for worker in workers {
        results.push(worker.join().expect("Artifact scope worker")?);
    }
    results.sort();
    assert_eq!(results, [0, 1, 2, 3]);
    assert_eq!(
        (
            active.load(Ordering::Acquire),
            checks.load(Ordering::Acquire)
        ),
        (0, 8)
    );
    assert!(!fixture.fenced.load(Ordering::Acquire));
    assert_eq!(*fixture.data.lock().expect("original reader"), 7);
    assert_eq!(fixture.gate.available.len(), 1);
    Ok(())
}

#[test]
fn artifact_admission_queue_expiry_never_enters_action() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let held = fixture
        .gate
        .acquire(&fixture.data, &fixture.fenced, end())?;
    let entered_at = Instant::now();
    let deadline = entered_at + Duration::from_millis(30);
    let waiter = fixture.clone();
    let calls = Arc::new(AtomicUsize::new(0));
    let worker_calls = calls.clone();
    let (done, result) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let refused = waiter
            .gate
            .with_original_action(
                &waiter.data,
                &waiter.fenced,
                deadline,
                |_| {
                    worker_calls.fetch_add(1, Ordering::AcqRel);
                    Ok(())
                },
                |_| {
                    worker_calls.fetch_add(1, Ordering::AcqRel);
                    Ok(())
                },
            )
            .is_err();
        done.send(refused).expect("expiry result");
    });
    assert!(result.recv_timeout(WATCHDOG)?);
    assert!(Instant::now() >= deadline);
    assert!(
        entered_at.elapsed() < Duration::from_millis(400),
        "test must distinguish the original end from a fresh 500ms wait"
    );
    worker.join().expect("expired Artifact waiter");
    assert_eq!(calls.load(Ordering::Acquire), 0);
    assert!(held.require_open().is_err());
    held.release()?;
    assert!(fixture.fenced.load(Ordering::Acquire));
    assert_eq!(fixture.gate.available.len(), 1);
    Ok(())
}

#[test]
fn artifact_admission_action_panic_keeps_original_mutex_poison() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let worker = fixture.clone();
    assert!(
        std::thread::spawn(move || {
            let _: Result<(), AgentdError> = worker.gate.with_original_action(
                &worker.data,
                &worker.fenced,
                end(),
                |_| Ok(()),
                |_| panic!("actual Artifact action unwind under original mutex"),
            );
        })
        .join()
        .is_err()
    );
    assert!(fixture.data.is_poisoned());
    assert_eq!(fixture.gate.available.len(), 1);
    assert!(
        fixture
            .gate
            .with_original_action(
                &fixture.data,
                &fixture.fenced,
                end(),
                |_| Ok(()),
                |_| Ok(()),
            )
            .is_err()
    );
    assert!(fixture.fenced.load(Ordering::Acquire));
    assert!(fixture.data.is_poisoned());
    Ok(())
}

#[test]
fn artifact_admission_failed_action_still_checks_and_releases() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let mut checks = 0;
    let result: Result<(), AgentdError> = fixture.gate.with_original_action(
        &fixture.data,
        &fixture.fenced,
        end(),
        |_| {
            checks += 1;
            Ok(())
        },
        |_| Err(failure("original action failure")),
    );
    assert!(
        matches!(result, Err(AgentdError::Invalid(message)) if message == "original action failure")
    );
    assert_eq!(checks, 2);
    assert!(!fixture.fenced.load(Ordering::Acquire));
    assert!(fixture.data.try_lock().is_ok());
    assert_eq!(fixture.gate.available.len(), 1);
    assert_eq!(
        fixture.gate.with_original_action(
            &fixture.data,
            &fixture.fenced,
            end(),
            |_| Ok(()),
            |data| Ok(*data),
        )?,
        7
    );
    Ok(())
}

#[test]
fn artifact_admission_postcheck_failure_refuses_success() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let mut checks = 0;
    let mut actions = 0;
    let result = fixture.gate.with_original_action(
        &fixture.data,
        &fixture.fenced,
        end(),
        |_| {
            checks += 1;
            if checks == 2 {
                return Err(AgentdError::GenerationFenced(
                    "original session changed".into(),
                ));
            }
            Ok(())
        },
        |_| {
            actions += 1;
            Ok(7)
        },
    );
    assert!(matches!(result, Err(AgentdError::GenerationFenced(_))));
    assert_eq!((checks, actions), (2, 1));
    assert!(fixture.fenced.load(Ordering::Acquire));
    assert!(fixture.data.try_lock().is_ok());
    assert_eq!(fixture.gate.available.len(), 1);
    assert!(
        fixture
            .gate
            .with_original_action(
                &fixture.data,
                &fixture.fenced,
                end(),
                |_| Ok(()),
                |_| Ok(()),
            )
            .is_err()
    );
    Ok(())
}

#[test]
fn artifact_admission_token_return_failure_refuses_success() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let mut checks = 0;
    let result = fixture.gate.with_original_action(
        &fixture.data,
        &fixture.fenced,
        end(),
        |_| {
            checks += 1;
            Ok(())
        },
        |_| {
            fixture.gate.returned.try_send(()).map_err(failure)?;
            Ok(7)
        },
    );
    assert!(result.is_err());
    assert_eq!(checks, 2);
    assert!(fixture.fenced.load(Ordering::Acquire));
    assert!(fixture.data.try_lock().is_ok());
    assert_eq!(fixture.gate.available.len(), 1);
    assert!(
        fixture
            .gate
            .with_original_action(
                &fixture.data,
                &fixture.fenced,
                end(),
                |_| Ok(()),
                |_| Ok(()),
            )
            .is_err()
    );
    Ok(())
}

#[test]
fn artifact_admission_late_action_cannot_report_success() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let worker_fixture = fixture.clone();
    let entered_at = Instant::now();
    let deadline = entered_at + Duration::from_millis(30);
    let checks = Arc::new(AtomicUsize::new(0));
    let worker_checks = checks.clone();
    let (entered, observed) = mpsc::channel();
    let (release, proceed) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        worker_fixture.gate.with_original_action(
            &worker_fixture.data,
            &worker_fixture.fenced,
            deadline,
            |_| {
                worker_checks.fetch_add(1, Ordering::AcqRel);
                Ok(())
            },
            |_| {
                entered.send(()).map_err(failure)?;
                proceed.recv_timeout(WATCHDOG).map_err(failure)?;
                Ok(7)
            },
        )
    });
    observed.recv_timeout(WATCHDOG)?;
    let (_kept_sender, timer) = mpsc::channel::<()>();
    assert!(matches!(
        timer.recv_timeout(deadline.saturating_duration_since(Instant::now())),
        Err(mpsc::RecvTimeoutError::Timeout)
    ));
    assert!(Instant::now() >= deadline);
    release.send(())?;
    assert!(worker.join().expect("late Artifact action").is_err());
    assert!(
        entered_at.elapsed() < Duration::from_millis(400),
        "test must distinguish the original end from a fresh 500ms scope"
    );
    assert_eq!(checks.load(Ordering::Acquire), 2);
    assert!(fixture.fenced.load(Ordering::Acquire));
    assert!(fixture.data.try_lock().is_ok());
    assert_eq!(fixture.gate.available.len(), 1);
    Ok(())
}
