use super::*;

#[test]
fn one_record_commit_retains_unrelated_allocations_and_rejects_before_append() {
    let path = path("incremental-legacy");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.submit(100, request()).unwrap();
    let mut second = request();
    second.request_id = "request.2".to_string();
    control.submit(100, second).unwrap();
    let original = control.get("request.1").unwrap().clone();
    let allocation = control
        .get("request.1")
        .unwrap()
        .request
        .payload_digest
        .as_ptr();
    control.cancel("request.2", 1).unwrap();
    assert_eq!(control.get("request.1"), Some(&original));
    assert_eq!(
        control
            .get("request.1")
            .unwrap()
            .request
            .payload_digest
            .as_ptr(),
        allocation
    );
    let bytes = std::fs::read(&path).unwrap();
    assert_eq!(
        control.commit(Event::Assign {
            request_id: "request.1".to_string(),
            expected_revision: 1,
            assignment: assignment()
        }),
        Err(Error::InvalidTransition)
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert_eq!(control.get("request.1"), Some(&original));
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.get("request.1"), Some(&original));
    assert_eq!(
        control.get("request.2").unwrap().state,
        RequestState::Cancelled
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn replay_rejects_cross_namespace_collision_in_both_orders() {
    use crate::durable_control::native::NativeRequest;
    let legacy_path = path("collision-legacy");
    let native_path = path("collision-native");
    let mut legacy = DurableInferenceControl::open(&legacy_path, 8).unwrap();
    legacy.submit(100, request()).unwrap();
    drop(legacy);
    let mut native = DurableInferenceControl::open(&native_path, 8).unwrap();
    native
        .reserve_native(
            NativeRequest {
                request_id: "request.1".to_string(),
                principal_id: "principal.1".to_string(),
                worker_generation: 1,
                model: "model".to_string(),
                payload_digest: "2".repeat(64),
            },
            1,
        )
        .unwrap();
    drop(native);
    let left = std::fs::read(&legacy_path).unwrap();
    let right = std::fs::read(&native_path).unwrap();
    for bytes in [
        [left.clone(), right.clone()].concat(),
        [right, left].concat(),
    ] {
        std::fs::write(&legacy_path, bytes).unwrap();
        assert!(matches!(
            DurableInferenceControl::open(&legacy_path, 8),
            Err(Error::CapacityExceeded)
        ));
    }
    std::fs::remove_file(legacy_path).unwrap();
    std::fs::remove_file(native_path).unwrap();
}
