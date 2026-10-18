#![allow(clippy::unwrap_used)]
use super::*;
#[test]
fn observed_floor_survives_a_failed_read_and_never_rolls_back() {
    let floor = AtomicU64::new(100);
    observe_clock(&floor, 101).unwrap();
    // A caller-visible source validation failure does not move the floor back.
    assert!(observe_clock(&floor, 99).is_err());
    assert_eq!(floor.load(Ordering::Acquire), 101);
    observe_clock(&floor, 10000).unwrap();
    assert!(observe_clock(&floor, 500).is_err());
    assert_eq!(floor.load(Ordering::Acquire), 10000);
}
