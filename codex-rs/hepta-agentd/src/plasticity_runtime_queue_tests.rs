use super::*;

#[test]
fn runtime_queue_capacity_is_bounded() {
    assert!(validate_plasticity_runtime_capacity(1).is_ok());
    assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE).is_ok());
    assert!(validate_plasticity_runtime_capacity(0).is_err());
    assert!(validate_plasticity_runtime_capacity(MAX_PLASTICITY_RUNTIME_QUEUE + 1).is_err());
}
