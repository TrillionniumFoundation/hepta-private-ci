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

fn request(deadline_ms: u64) -> DispatchRequest {
    DispatchRequest {
        dispatch_id: id("dispatch:deadline"),
        request_id: id("request:deadline"),
        worker_id: id("worker:deadline"),
        request_digest: digest(b"request"),
        reservation_digest: digest(b"reservation"),
        lease_digest: digest(b"lease"),
        model_digest: digest(b"model"),
        deadline_ms,
    }
}

fn must_plan(request: DispatchRequest) -> DispatchPlan {
    let result = plan(
        /*now_ms*/ 1_000,
        request,
        digest(b"request"),
        digest(b"reservation"),
        digest(b"lease"),
        digest(b"model"),
    );
    let Ok(plan) = result else {
        panic!("valid dispatch plan must succeed");
    };
    plan
}

#[test]
fn deadline_is_bound_into_the_dispatch_plan_digest() {
    let earlier = must_plan(request(/*deadline_ms*/ 2_000));
    let later = must_plan(request(/*deadline_ms*/ 3_000));

    assert_ne!(earlier.plan_digest, later.plan_digest);
}

#[test]
fn an_exact_retry_keeps_the_complete_dispatch_plan_stable() {
    assert_eq!(
        must_plan(request(/*deadline_ms*/ 2_000)),
        must_plan(request(/*deadline_ms*/ 2_000))
    );
}
