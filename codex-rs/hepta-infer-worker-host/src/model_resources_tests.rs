use super::*;

#[test]
fn aggregate_reservations_precede_allocation_and_unused_guards_refund() {
    let manager = ResourceManager::new(/*generation*/ 3, /*limit_bytes*/ 4096);
    let first = manager.reserve(/*bytes*/ 3072).unwrap();
    assert!(matches!(
        manager.reserve(/*bytes*/ 2048),
        Err(Error::ModelCapacity)
    ));
    assert_eq!(manager.snapshot().unwrap().reserved_bytes, 3072);
    drop(first);
    assert_eq!(manager.snapshot().unwrap().reserved_bytes, 0);
    assert!(manager.reserve(/*bytes*/ 4096).is_ok());
}

#[test]
fn unknown_physical_outcome_never_refunds_or_reopens_generation() {
    let manager = ResourceManager::new(/*generation*/ 3, /*limit_bytes*/ 4096);
    let mut live = manager.reserve(/*bytes*/ 1024).unwrap();
    live.enter().unwrap();
    drop(live);
    assert_eq!(
        manager.snapshot().unwrap(),
        ResourceSnapshot {
            generation: 3,
            limit_bytes: 4096,
            reserved_bytes: 1024,
            reservations: 1,
            quarantined_reservations: 1,
            fenced: true,
        }
    );
    assert!(matches!(
        manager.reserve(/*bytes*/ 1),
        Err(Error::GenerationFenced)
    ));
}

#[test]
fn observed_cleanup_can_release_a_fenced_generation() {
    let manager = ResourceManager::new(/*generation*/ 3, /*limit_bytes*/ 4096);
    let mut live = manager.reserve(/*bytes*/ 1024).unwrap();
    live.enter().unwrap();
    manager.fence().unwrap();
    live.release_after_terminal().unwrap();
    let snapshot = manager.snapshot().unwrap();
    assert_eq!(snapshot.reserved_bytes, 0);
    assert!(snapshot.fenced);
}

#[test]
fn aggregate_counter_overflow_does_not_mutate_reservation_state() {
    let manager = ResourceManager::new(/*generation*/ 3, u64::MAX);
    let _live = manager.reserve(u64::MAX).unwrap();
    let before = manager.snapshot().unwrap();
    assert!(matches!(
        manager.reserve(/*bytes*/ 1),
        Err(Error::ArithmeticOverflow)
    ));
    assert_eq!(manager.snapshot().unwrap(), before);
}
