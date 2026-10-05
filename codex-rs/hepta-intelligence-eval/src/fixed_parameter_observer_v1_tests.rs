use super::*;
#[test]
fn ordinary_process_cannot_reach_parameter_observer_signing_from_a_claimed_config() {
    assert!(run_fixed_parameter_observer_v1(Path::new("/missing/claimed-observer.json")).is_err());
}
