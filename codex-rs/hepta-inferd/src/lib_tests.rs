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


fn scheduling_reservation() -> SchedulingReservation {
    SchedulingReservation {
        assignment_id: id("assignment:1"),
        request_id: id("request:schedule"),
        request_digest: digest(b"schedule-request"),
        reservation_digest: digest(b"schedule-reservation"),
        model_digest: digest(b"model"),
        tokenizer_digest: digest(b"tokenizer"),
        template_digest: digest(b"template"),
        payload_digest: digest(b"payload"),
        maximum_tokens: 4_096,
        required_memory_bytes: 8 * 1024,
        deadline_ms: 2_000,
    }
}

fn worker(name: &str, in_flight: u32, memory: u64) -> EligibleWorker {
    EligibleWorker {
        worker_id: id(name),
        generation: 7,
        lease_digest: digest(format!("lease:{name}").as_bytes()),
        model_digest: digest(b"model"),
        tokenizer_digest: digest(b"tokenizer"),
        template_digest: digest(b"template"),
        payload_digest: digest(b"payload"),
        maximum_tokens: 8_192,
        available_memory_bytes: memory,
        in_flight,
        maximum_in_flight: 4,
    }
}

#[test]
fn scheduling_is_order_independent_and_grants_no_provider_authority() {
    let first = worker("worker:a", 2, 32 * 1024);
    let second = worker("worker:b", 0, 16 * 1024);
    let forward = EligibleWorkerSnapshot {
        snapshot_id: id("snapshot:1"),
        workers: vec![first.clone(), second.clone()],
    };
    let reverse = EligibleWorkerSnapshot {
        snapshot_id: id("snapshot:1"),
        workers: vec![second, first],
    };
    assert_eq!(
        eligible_worker_snapshot_digest(&forward),
        eligible_worker_snapshot_digest(&reverse)
    );

    let left = schedule(1_000, scheduling_reservation(), forward).unwrap();
    let right = schedule(1_000, scheduling_reservation(), reverse).unwrap();
    assert_eq!(left, right);
    assert_eq!(left.worker_id, id("worker:b"));
    assert!(!left.provider_dispatch_authority);
    assert!(!left.authority.grants_any());
}

#[test]
fn scheduler_rejects_model_payload_or_capacity_mismatch() {
    let mut wrong_payload = worker("worker:a", 0, 32 * 1024);
    wrong_payload.payload_digest = digest(b"other-payload");
    assert_eq!(
        schedule(
            1_000,
            scheduling_reservation(),
            EligibleWorkerSnapshot {
                snapshot_id: id("snapshot:payload"),
                workers: vec![wrong_payload],
            },
        ),
        Err(Error::NoEligibleWorker)
    );

    let too_small = worker("worker:b", 0, 4 * 1024);
    assert_eq!(
        schedule(
            1_000,
            scheduling_reservation(),
            EligibleWorkerSnapshot {
                snapshot_id: id("snapshot:memory"),
                workers: vec![too_small],
            },
        ),
        Err(Error::NoEligibleWorker)
    );
}

#[test]
fn scheduler_uses_spare_memory_then_stable_id_as_deterministic_tiebreakers() {
    let less_memory = worker("worker:a", 0, 16 * 1024);
    let more_memory = worker("worker:z", 0, 64 * 1024);
    let selected = schedule(
        1_000,
        scheduling_reservation(),
        EligibleWorkerSnapshot {
            snapshot_id: id("snapshot:memory-rank"),
            workers: vec![less_memory, more_memory],
        },
    )
    .unwrap();
    assert_eq!(selected.worker_id, id("worker:z"));

    let left = worker("worker:a", 0, 64 * 1024);
    let right = worker("worker:b", 0, 64 * 1024);
    let selected = schedule(
        1_000,
        scheduling_reservation(),
        EligibleWorkerSnapshot {
            snapshot_id: id("snapshot:id-rank"),
            workers: vec![right, left],
        },
    )
    .unwrap();
    assert_eq!(selected.worker_id, id("worker:a"));
}

#[test]
fn duplicate_worker_identity_is_rejected_before_ranking() {
    let first = worker("worker:a", 0, 64 * 1024);
    let mut duplicate = first.clone();
    duplicate.generation = 8;
    assert_eq!(
        schedule(
            1_000,
            scheduling_reservation(),
            EligibleWorkerSnapshot {
                snapshot_id: id("snapshot:duplicate"),
                workers: vec![first, duplicate],
            },
        ),
        Err(Error::DuplicateWorker)
    );
}
