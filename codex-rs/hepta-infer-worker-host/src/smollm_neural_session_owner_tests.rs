use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::process::Stdio;

use super::*;

fn prepare(directory: &std::path::Path) -> SupervisorOwner {
    SupervisorOwner::prepare(
        File::open(directory).unwrap(),
        Instant::now() + Duration::from_secs(2),
        &CancellationToken::new(),
    )
    .unwrap()
}

fn command() -> Command {
    let mut command = Command::new("/bin/sh");
    command
        .args(["-c", "read -r value; test \"$value\" = stop"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command
}

#[test]
fn two_preborn_owners_preserve_parallel_children_and_third_refuses_before_birth() {
    let directory = tempfile::tempdir().unwrap();
    let first = prepare(directory.path());
    let second = prepare(directory.path());
    first.spawn(&mut command()).unwrap();
    second.spawn(&mut command()).unwrap();
    assert_ne!(first.id(), second.id());
    assert!(first.try_wait().unwrap().is_none());
    assert!(second.try_wait().unwrap().is_none());
    assert!(
        SupervisorOwner::prepare(
            File::open(directory.path()).unwrap(),
            Instant::now() + Duration::from_secs(2),
            &CancellationToken::new()
        )
        .err()
        .unwrap()
        .contains("capacity busy")
    );
    for owner in [&first, &second] {
        owner.take_stdin().unwrap().write_all(b"stop\n").unwrap();
        assert!(owner.wait().unwrap().success());
        owner.release_verified_terminal().unwrap();
    }
    let successor = prepare(directory.path());
    assert!(first.spawn(&mut command()).unwrap_err().contains("differs"));
    assert!(first.try_wait().unwrap_err().contains("differs"));
    successor.spawn(&mut command()).unwrap();
    let cutoff = successor.cutoff();
    drop(first);
    drop(second);
    std::thread::sleep(Duration::from_millis(10));
    assert!(!successor.lease.requested.load(Ordering::Acquire));
    assert_eq!(successor.cutoff(), cutoff);
    assert!(successor.try_wait().unwrap().is_none());
    successor
        .take_stdin()
        .unwrap()
        .write_all(b"stop\n")
        .unwrap();
    assert!(successor.wait().unwrap().success());
    successor.release_verified_terminal().unwrap();
}

#[test]
fn denied_or_panicked_prebirth_thread_request_keeps_bounded_roots_without_a_child() {
    let directory = tempfile::tempdir().unwrap();
    let before = std::fs::read_dir("/proc/self/task").unwrap().count();
    for failure in [1, 2] {
        REQUEST_FAILURE.set(failure);
        assert!(
            SupervisorOwner::prepare(
                File::open(directory.path()).unwrap(),
                Instant::now() + Duration::from_secs(2),
                &CancellationToken::new()
            )
            .is_err()
        );
        REQUEST_FAILURE.set(0);
    }
    let roots = OWNERS.lock().unwrap();
    assert_eq!(roots.iter().flatten().count(), CAPACITY);
    for (index, slot) in roots.iter().flatten().enumerate() {
        assert_eq!(slot.failure.load(Ordering::Acquire), (index + 1) as u8);
        let payload = slot.payload.lock().unwrap();
        let payload = payload.as_ref().unwrap();
        assert!(payload.child.is_none());
        assert!(payload.directory.metadata().unwrap().is_dir());
        assert!(!slot.ready.load(Ordering::Acquire));
    }
    assert_eq!(
        roots[0].as_ref().unwrap().os_error.load(Ordering::Acquire),
        libc::EAGAIN
    );
    assert_eq!(
        std::fs::read_dir("/proc/self/task").unwrap().count(),
        before
    );
}

#[test]
fn cleanup_panic_after_drop_retains_exact_child_and_held_directory_in_failed_slot() {
    let directory = tempfile::tempdir().unwrap();
    let owner = prepare(directory.path());
    owner.spawn(&mut command()).unwrap();
    let pid = owner.id();
    let held = owner.directory().unwrap();
    let identity = held.metadata().unwrap();
    let mut input = owner.take_stdin().unwrap();
    let weak = Arc::downgrade(&owner.slot);
    owner.slot.panic_cleanup.store(true, Ordering::SeqCst);
    drop(owner);
    let slot = weak.upgrade().unwrap();
    let deadline = Instant::now() + Duration::from_secs(2);
    while slot.failure.load(Ordering::Acquire) == 0 {
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(
        slot.failure.load(Ordering::Acquire),
        Failure::CleanupPanic as u8
    );
    assert!(
        OWNERS
            .lock()
            .unwrap()
            .iter()
            .flatten()
            .any(|root| Arc::ptr_eq(root, &slot))
    );
    // Test-only inspection of the poisoned original slot, never a production
    // recovery into success. Reap only this exact controlled child naturally.
    let mut guard = slot.payload.lock().err().unwrap().into_inner();
    let payload = guard.as_mut().unwrap();
    let actual = payload.directory.metadata().unwrap();
    assert_eq!(
        (actual.dev(), actual.ino()),
        (identity.dev(), identity.ino())
    );
    let child = payload.child.as_mut().unwrap();
    assert_eq!(child.id(), pid);
    assert!(child.try_wait().unwrap().is_none());
    input.write_all(b"stop\n").unwrap();
    drop(input);
    assert!(child.wait().unwrap().success());
    assert!(payload.child.is_some());
    assert_eq!(
        slot.failure.load(Ordering::Acquire),
        Failure::CleanupPanic as u8
    );
}

#[test]
fn foreground_and_drop_never_wait_for_a_held_cleanup_payload() {
    let directory = tempfile::tempdir().unwrap();
    let owner = prepare(directory.path());
    let slot = Arc::clone(&owner.slot);
    let lease = Arc::clone(&owner.lease);
    let guard = slot.payload.lock().unwrap();
    let started = Instant::now();
    assert!(owner.try_wait().unwrap_err().contains("busy or poisoned"));
    assert!(owner.directory().unwrap_err().contains("busy or poisoned"));
    assert!(
        owner
            .spawn(&mut command())
            .unwrap_err()
            .contains("busy or poisoned")
    );
    assert!(
        owner
            .release_verified_terminal()
            .unwrap_err()
            .contains("busy or poisoned")
    );
    drop(owner);
    assert!(lease.requested.load(Ordering::Acquire));
    assert!(started.elapsed() < Duration::from_millis(250));
    assert!(guard.as_ref().unwrap().child.is_none());
    drop(guard);
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        if let Ok(payload) = slot.payload.try_lock()
            && payload.is_none()
        {
            break;
        }
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(1));
    }
}

#[test]
fn cancellation_or_original_startup_expiry_prevents_child_birth() {
    let directory = tempfile::tempdir().unwrap();
    let cancellation = CancellationToken::new();
    let cancelled = SupervisorOwner::prepare(
        File::open(directory.path()).unwrap(),
        Instant::now() + Duration::from_secs(2),
        &cancellation,
    )
    .unwrap();
    cancellation.cancel();
    assert!(
        cancelled
            .spawn(&mut command())
            .unwrap_err()
            .contains("unavailable")
    );
    assert!(
        cancelled
            .slot
            .payload
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .child
            .is_none()
    );
    let expired = SupervisorOwner::prepare(
        File::open(directory.path()).unwrap(),
        Instant::now() + Duration::from_millis(20),
        &CancellationToken::new(),
    )
    .unwrap();
    std::thread::sleep(Duration::from_millis(25));
    assert!(
        expired
            .spawn(&mut command())
            .unwrap_err()
            .contains("unavailable")
    );
    assert!(
        expired
            .slot
            .payload
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .child
            .is_none()
    );
}

#[test]
fn readiness_expiry_uses_original_budget_and_keeps_unborn_reservation_closed() {
    let directory = tempfile::tempdir().unwrap();
    REQUEST_FAILURE.set(3);
    let deadline = Instant::now() + Duration::from_millis(20);
    let result = SupervisorOwner::prepare(
        File::open(directory.path()).unwrap(),
        deadline,
        &CancellationToken::new(),
    );
    REQUEST_FAILURE.set(0);
    assert!(
        result
            .err()
            .unwrap()
            .contains("readiness exceeded original startup")
    );
    let slot = Arc::clone(OWNERS.lock().unwrap()[0].as_ref().unwrap());
    assert_eq!(
        slot.failure.load(Ordering::Acquire),
        Failure::ReadinessExpired as u8
    );
    assert!(
        slot.payload
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .child
            .is_none()
    );
    let observed = Instant::now() + Duration::from_secs(2);
    while !slot.ready.load(Ordering::Acquire) {
        assert!(Instant::now() < observed);
        std::thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(
        slot.failure.load(Ordering::Acquire),
        Failure::ReadinessExpired as u8
    );
    assert!(
        slot.payload
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .child
            .is_none()
    );
}

#[test]
fn exact_supervisor_exit_without_original_worker_receipt_stays_closed() {
    let directory = tempfile::tempdir().unwrap();
    let owner = prepare(directory.path());
    owner.spawn(&mut Command::new("/bin/true")).unwrap();
    let pid = owner.id();
    let slot = Arc::clone(&owner.slot);
    drop(owner);
    let deadline = Instant::now() + Duration::from_secs(2);
    while slot.failure.load(Ordering::Acquire) == Failure::None as u8 {
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(
        slot.failure.load(Ordering::Acquire),
        Failure::CleanupIo as u8
    );
    assert!(
        OWNERS
            .lock()
            .unwrap()
            .iter()
            .flatten()
            .any(|root| Arc::ptr_eq(root, &slot))
    );
    let mut guard = slot.payload.lock().unwrap();
    let payload = guard.as_mut().unwrap();
    assert!(payload.directory.metadata().unwrap().is_dir());
    let child = payload.child.as_mut().unwrap();
    assert_eq!(child.id(), pid);
    assert!(child.try_wait().unwrap().unwrap().success());
    assert!(payload.lease.requested.load(Ordering::Acquire));
}

#[test]
fn contended_root_reservation_starts_two_original_children_without_retrying_birth() {
    let directory = tempfile::tempdir().unwrap();
    let roots = OWNERS.lock().unwrap();
    let barrier = std::sync::Barrier::new(3);
    let (first, second) = std::thread::scope(|scope| {
        let start = || {
            barrier.wait();
            prepare(directory.path())
        };
        let first = scope.spawn(start);
        let second = scope.spawn(start);
        barrier.wait();
        std::thread::sleep(Duration::from_millis(20));
        drop(roots);
        (first.join().unwrap(), second.join().unwrap())
    });
    first.spawn(&mut command()).unwrap();
    second.spawn(&mut command()).unwrap();
    assert_ne!(first.id(), second.id());
    assert!(first.try_wait().unwrap().is_none());
    assert!(second.try_wait().unwrap().is_none());
    assert!(
        SupervisorOwner::prepare(
            File::open(directory.path()).unwrap(),
            Instant::now() + Duration::from_secs(2),
            &CancellationToken::new(),
        )
        .err()
        .unwrap()
        .contains("capacity busy")
    );
    for owner in [&first, &second] {
        owner.take_stdin().unwrap().write_all(b"stop\n").unwrap();
        assert!(owner.wait().unwrap().success());
        owner.release_verified_terminal().unwrap();
    }
}

#[test]
fn root_contention_preserves_original_deadline_and_cancellation_before_reservation() {
    let directory = tempfile::tempdir().unwrap();
    for cancel in [false, true] {
        let roots = OWNERS.lock().unwrap();
        let cancellation = CancellationToken::new();
        let barrier = std::sync::Barrier::new(2);
        std::thread::scope(|scope| {
            let waiter = scope.spawn(|| {
                barrier.wait();
                SupervisorOwner::prepare(
                    File::open(directory.path()).unwrap(),
                    Instant::now() + Duration::from_millis(40),
                    &cancellation,
                )
            });
            barrier.wait();
            if cancel {
                cancellation.cancel();
            }
            assert!(
                waiter
                    .join()
                    .unwrap()
                    .err()
                    .unwrap()
                    .contains("exceeded original startup")
            );
            assert!(roots.iter().all(Option::is_none));
        });
    }
}

#[test]
fn poisoned_roots_never_wait_or_reserve_an_owner() {
    let directory = tempfile::tempdir().unwrap();
    assert!(
        std::thread::spawn(|| {
            let _roots = OWNERS.lock().unwrap();
            panic!("controlled roots poison before any birth");
        })
        .join()
        .is_err()
    );
    assert!(
        SupervisorOwner::prepare(
            File::open(directory.path()).unwrap(),
            Instant::now() + Duration::from_secs(2),
            &CancellationToken::new(),
        )
        .err()
        .unwrap()
        .contains("busy or poisoned")
    );
    let poisoned = OWNERS.lock().err().unwrap().into_inner();
    assert!(poisoned.iter().all(Option::is_none));
}

#[test]
fn root_contention_attempt_cap_refuses_without_waiting_for_a_longer_startup_window() {
    let directory = tempfile::tempdir().unwrap();
    let roots = OWNERS.lock().unwrap();
    let started = Instant::now();
    let error = SupervisorOwner::prepare(
        File::open(directory.path()).unwrap(),
        started + Duration::from_secs(10),
        &CancellationToken::new(),
    )
    .err()
    .unwrap();
    assert!(error.contains("busy or poisoned"));
    assert!(started.elapsed() < Duration::from_secs(2));
    assert!(roots.iter().all(Option::is_none));
}
