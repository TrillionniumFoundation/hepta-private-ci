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

fn worker(
    worker_id: &str,
    preference_rank: u32,
    available_tokens: u64,
    available_concurrency: u32,
) -> EligibleWorker {
    EligibleWorker {
        worker_id: id(worker_id),
        worker_generation: 7,
        lease_digest: digest(format!("lease:{worker_id}").as_bytes()),
        model_digest: digest(b"model"),
        available_concurrency,
        available_tokens,
        preference_rank,
    }
}

fn schedule_request(workers: Vec<EligibleWorker>) -> ScheduleRequest {
    ScheduleRequest {
        dispatch_id: id("dispatch:schedule"),
        request_id: id("request:schedule"),
        request_digest: digest(b"request"),
        reservation_digest: digest(b"reservation"),
        model_digest: digest(b"model"),
        deadline_ms: 2_000,
        required_tokens: 512,
        eligible_workers: workers,
    }
}

#[test]
fn deterministic_feasible_ranking_is_input_order_independent_and_authority_free() {
    let worker_a = worker("worker:a", 1, 1_024, 1);
    let worker_b = worker("worker:b", 1, 2_048, 1);
    let worker_c = worker("worker:c", 0, 256, 1);

    let first = schedule(
        1_000,
        schedule_request(vec![worker_a.clone(), worker_b.clone(), worker_c.clone()]),
    )
    .expect("feasible assignment");
    let reordered = schedule(
        1_000,
        schedule_request(vec![worker_c, worker_b, worker_a]),
    )
    .expect("same feasible assignment");

    assert_eq!(first, reordered);
    assert_eq!(first.plan.worker_id, id("worker:b"));
    assert!(!first.plan.provider_dispatch_authority);
    assert!(!first.plan.authority.grants_any());
}

#[test]
fn scheduler_rejects_exhausted_or_model_mismatched_workers() {
    let exhausted = worker("worker:exhausted", 0, 511, 1);
    let mut wrong_model = worker("worker:wrong-model", 0, 4_096, 1);
    wrong_model.model_digest = digest(b"other-model");

    assert_eq!(
        schedule(1_000, schedule_request(vec![exhausted, wrong_model])),
        Err(Error::NoFeasibleWorker)
    );
}

#[test]
fn scheduler_rejects_duplicate_worker_identity() {
    let worker = worker("worker:duplicate", 0, 4_096, 1);
    assert_eq!(
        schedule(1_000, schedule_request(vec![worker.clone(), worker])),
        Err(Error::DuplicateWorker)
    );
}

#[test]
fn eligible_snapshot_and_selection_digest_bind_capacity_and_lease() {
    let base = worker("worker:stable", 0, 1_024, 1);
    let first =
        schedule(1_000, schedule_request(vec![base.clone()])).expect("first assignment");

    let mut changed_capacity = base.clone();
    changed_capacity.available_tokens = 2_048;
    let capacity =
        schedule(1_000, schedule_request(vec![changed_capacity])).expect("capacity assignment");
    assert_ne!(
        first.eligible_snapshot_digest,
        capacity.eligible_snapshot_digest
    );
    assert_ne!(first.selection_digest, capacity.selection_digest);

    let mut changed_lease = base;
    changed_lease.lease_digest = digest(b"lease:changed");
    let lease =
        schedule(1_000, schedule_request(vec![changed_lease])).expect("lease assignment");
    assert_ne!(first.eligible_snapshot_digest, lease.eligible_snapshot_digest);
    assert_ne!(first.selection_digest, lease.selection_digest);
}
