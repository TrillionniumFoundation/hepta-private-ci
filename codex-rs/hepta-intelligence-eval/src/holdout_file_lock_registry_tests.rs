use super::*;
use pretty_assertions::assert_eq;
use std::cell::Cell;

#[test]
fn origin_gate_is_local_and_rejects_inherited_process_before_registry() {
    // A local gate only: never mutate the process-wide ORIGIN in parallel tests.
    let origin = AtomicU32::new(0);
    assert!(check_origin(&origin, 101).is_ok());
    assert!(check_origin(&origin, 101).is_ok());
    assert_eq!(
        check_origin(&origin, 202).unwrap_err().kind(),
        io::ErrorKind::Unsupported
    );
    assert_eq!(origin.load(Ordering::Relaxed), 101);
}

#[test]
fn old_nonce_cannot_release_replacement_and_unlock_failure_quarantines() {
    let mut registry = Registry::new();
    let key = Identity(1, 2);
    let old = registry.reserve(key, 101).unwrap();
    assert!(matches!(
        registry.reserve(key, 101),
        Err(TryLockError::WouldBlock)
    ));
    registry.release(old, || Ok(()));
    let new = registry.reserve(key, 101).unwrap();
    assert_ne!(old.nonce, new.nonce);
    let called = Cell::new(false);
    registry.release(old, || {
        called.set(true);
        Ok(())
    });
    assert!(!called.get());
    assert_eq!(registry.leases.get(&key), Some(&new.nonce));
    registry.release(new, || Err(io::Error::other("injected unlock failure")));
    assert!(matches!(
        registry.reserve(key, 101),
        Err(TryLockError::WouldBlock)
    ));
    assert_eq!(registry.leases.get(&key), Some(&new.nonce));
}

#[test]
fn exhausted_nonce_fails_without_reservation() {
    let mut registry = Registry::new();
    registry.next_nonce = u64::MAX;
    assert!(matches!(
        registry.reserve(Identity(3, 4), 101),
        Err(TryLockError::Error(_))
    ));
    assert!(registry.leases.is_empty());
}

#[test]
fn child_cleanup_and_poisoned_registry_do_not_unlock_live_lock() {
    // All registry/PID simulation is local; neither global static is mutated.
    let fixture = super::super::tests::Fixture::new();
    let file = fixture.open();
    file.try_lock().unwrap();
    let metadata = file.metadata().unwrap();
    let identity = Identity(metadata.dev(), metadata.ino());
    let registry = Mutex::new(Registry::new());
    let lease = registry
        .lock()
        .unwrap()
        .reserve(identity, std::process::id())
        .unwrap();
    let child_copy = Lease {
        pid: lease.pid ^ u32::MAX,
        ..lease
    };
    release_registered(&registry, &file, child_copy);
    fixture.assert_busy();
    assert_eq!(
        registry.lock().unwrap().leases.get(&identity),
        Some(&lease.nonce)
    );
    let poisoned = std::panic::catch_unwind(|| {
        let _guard = registry.lock().unwrap();
        panic!("poison local test registry");
    });
    assert!(poisoned.is_err());
    release_registered(&registry, &file, lease);
    fixture.assert_busy();
    file.unlock().unwrap();
}
