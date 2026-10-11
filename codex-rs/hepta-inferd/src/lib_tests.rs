use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn request() -> DispatchRequest {
    DispatchRequest {
        dispatch_id: id("dispatch:1"),
        request_id: id("request:1"),
        worker_id: id("worker:1"),
        request_digest: digest(b"request"),
        reservation_digest: digest(b"reservation"),
        lease_digest: digest(b"lease"),
        model_digest: digest(b"model"),
        deadline_ms: 2_000,
    }
}

#[test]
fn exact_plan_grants_no_provider_authority() {
    let value = request();
    let Ok(plan) = plan(
        1_000,
        value,
        digest(b"request"),
        digest(b"reservation"),
        digest(b"lease"),
        digest(b"model"),
    ) else {
        panic!("exact plan must succeed");
    };
    assert!(!plan.provider_dispatch_authority);
    assert!(!plan.authority.grants_any());
}

#[test]
fn lease_drift_is_rejected() {
    assert_eq!(
        plan(
            1_000,
            request(),
            digest(b"request"),
            digest(b"reservation"),
            digest(b"other-lease"),
            digest(b"model"),
        ),
        Err(Error::BindingMismatch("lease"))
    );
}

#[test]
fn expired_dispatch_is_rejected() {
    assert_eq!(
        plan(
            2_000,
            request(),
            digest(b"request"),
            digest(b"reservation"),
            digest(b"lease"),
            digest(b"model"),
        ),
        Err(Error::DeadlineExpired)
    );
}
