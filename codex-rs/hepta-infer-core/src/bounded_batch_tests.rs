use super::*;

fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: impl Into<String>) -> StableId {
    StableId::new(value).expect("valid id")
}

fn lane(generation: u64, fence: &str, scope: &str) -> BatchLaneKeyV1 {
    BatchLaneKeyV1 {
        scope_digest: d(scope),
        model_digest: d("model"),
        generation,
        fence_digest: d(fence),
        authority_epoch: 1,
        revocation_frontier_digest: d("revocation:1"),
    }
}

fn request(n: usize, lane: BatchLaneKeyV1, features: &SharedFeaturesQ24V1) -> BatchRequestV1 {
    BatchRequestV1 {
        operation_id: id(format!("req:{n}")),
        idempotency_digest: d(&format!("nonce:{n}")),
        lane,
        enqueued_at_ms: 1,
        deadline_ms: 100,
        features: features.clone(),
    }
}

fn policy() -> BatchPolicyV1 {
    BatchPolicyV1 {
        max_pending: 8_192,
        max_queued_feature_bytes: 256 * 1024 * 1024,
        max_batch_count: 4,
        max_batch_bytes: 128,
        max_queue_delay_ms: 5,
    }
}

#[test]
fn shared_features_are_immutable_and_arc_backed() {
    let first = SharedFeaturesQ24V1::new(vec![1, 2, 3]).expect("features");
    let second = first.clone();
    assert!(Arc::ptr_eq(&first.values, &second.values));
    assert_eq!(first.digest(), second.digest());
    assert_eq!(first.byte_len(), 24);
    let different = SharedFeaturesQ24V1::new(vec![1, 2, 4]).expect("features");
    assert_ne!(first.digest(), different.digest());
}

#[test]
fn batch_is_fenced_and_not_removed_before_durable_ack() {
    let mut queue = BoundedBatchSchedulerV1::new(policy()).expect("policy");
    let features = SharedFeaturesQ24V1::new(vec![1, 2]).expect("features");
    assert!(queue.admit(request(0, lane(4, "fence:a", "s"), &features)).expect("admit"));
    assert!(queue.admit(request(1, lane(4, "fence:a", "s"), &features)).expect("admit"));
    assert!(queue.admit(request(2, lane(5, "fence:a", "s"), &features)).expect("admit"));
    assert!(queue.admit(request(3, lane(4, "fence:b", "s"), &features)).expect("admit"));
    assert_eq!(queue.pending_count(), 4);
    assert_eq!(queue.queued_feature_bytes(), 64);
    assert!(queue.next_ready(2).expect("peek").is_none());
    let plan = queue.next_ready(7).expect("peek").expect("ready");
    assert_eq!(plan.requests.len(), 2);
    assert!(plan.requests.iter().all(|request| request.lane == lane(4, "fence:a", "s")));
    assert_eq!(queue.next_ready(7).expect("same intent"), Some(plan.clone()));
    assert_eq!(queue.pending_count(), 4);
    queue.confirm_durable(&plan).expect("durable ack");
    assert_eq!(queue.pending_count(), 2);
    assert_eq!(queue.queued_feature_bytes(), 32);
    assert_eq!(queue.confirm_durable(&plan), Err(BatchError::IntentMismatch));
    assert_eq!(queue.pending_count(), 2);
}

#[test]
fn identical_operation_is_idempotent_and_conflict_is_rejected() {
    let mut queue = BoundedBatchSchedulerV1::new(policy()).expect("policy");
    let features = SharedFeaturesQ24V1::new(vec![1]).expect("features");
    let first = request(0, lane(1, "fence:a", "s"), &features);
    assert!(queue.admit(first.clone()).expect("first"));
    assert!(!queue.admit(first.clone()).expect("retry"));
    let mut modified = first;
    modified.deadline_ms = 90;
    assert_eq!(queue.admit(modified), Err(BatchError::Conflict));
    assert_eq!(queue.pending_count(), 1);
}

#[test]
fn tampered_plan_cannot_ack_or_drain_a_queue() {
    let mut queue = BoundedBatchSchedulerV1::new(policy()).expect("policy");
    let features = SharedFeaturesQ24V1::new(vec![1, 2]).expect("features");
    queue.admit(request(0, lane(1, "fence", "s"), &features)).expect("admit");
    let plan = queue.next_ready(7).expect("peek").expect("ready");
    let mut tampered = plan.clone();
    tampered.total_feature_bytes += 1;
    assert_eq!(queue.confirm_durable(&tampered), Err(BatchError::IntentMismatch));
    assert_eq!(queue.pending_count(), 1);
    let mut tampered = plan.clone();
    tampered.requests[0].lane.generation = 2;
    tampered.intent_digest = tampered.calculate_digest();
    assert_eq!(queue.confirm_durable(&tampered), Err(BatchError::IntentMismatch));
    assert_eq!(queue.pending_count(), 1);
    queue.confirm_durable(&plan).expect("exact committed intent");
}

#[test]
fn expired_front_must_be_reconciled_and_not_silently_skipped() {
    let mut queue = BoundedBatchSchedulerV1::new(policy()).expect("policy");
    let features = SharedFeaturesQ24V1::new(vec![1]).expect("features");
    queue.admit(request(0, lane(1, "fence", "s"), &features)).expect("admit");
    assert_eq!(queue.next_ready(100), Err(BatchError::DeadlineExpired));
    assert_eq!(queue.pending_count(), 1);
}

#[test]
fn max_feature_and_queue_caps_are_strict() {
    assert_eq!(
        SharedFeaturesQ24V1::new(vec![]),
        Err(BatchError::InvalidFeatures)
    );
    assert_eq!(
        SharedFeaturesQ24V1::new(vec![1; 4_097]),
        Err(BatchError::InvalidFeatures)
    );
    let mut small = policy();
    small.max_pending = 1;
    let mut queue = BoundedBatchSchedulerV1::new(small).expect("policy");
    let features = SharedFeaturesQ24V1::new(vec![1]).expect("features");
    queue.admit(request(0, lane(1, "fence", "s"), &features)).expect("first");
    assert_eq!(
        queue.admit(request(1, lane(1, "fence", "s"), &features)),
        Err(BatchError::CapacityExceeded)
    );
}

/// Synthetic scheduler-size regression, not target-host throughput evidence.
/// Run explicitly with cargo test -- --ignored --nocapture on the selected host.
#[test]
#[ignore = "explicit 64/256/1024/4096-scope scheduler microbenchmark"]
fn synthetic_scope_matrix() {
    for scope_count in [64, 256, 1_024, 4_096] {
        let mut queue = BoundedBatchSchedulerV1::new(policy()).expect("policy");
        let features = SharedFeaturesQ24V1::new(vec![1; 8]).expect("features");
        let started = std::time::Instant::now();
        for i in 0..scope_count {
            queue
                .admit(request(i, lane(1, "fence", &format!("scope:{i}")), &features))
                .expect("admit");
        }
        assert_eq!(queue.pending_count(), scope_count);
        let admission = started.elapsed();
        let started = std::time::Instant::now();
        for _ in 0..scope_count {
            let plan = queue.next_ready(7).expect("peek").expect("ready");
            assert_eq!(plan.requests.len(), 1);
            queue.confirm_durable(&plan).expect("synthetic acknowledge");
        }
        assert_eq!(queue.pending_count(), 0);
        eprintln!(
            "synthetic scopes={scope_count} admit_us={} drain_us={}",
            admission.as_micros(),
            started.elapsed().as_micros()
        );
    }
}

#[test]
fn global_queued_byte_cap_is_enforced_without_mutation() {
    let mut small = policy();
    small.max_queued_feature_bytes = 16;
    let mut queue = BoundedBatchSchedulerV1::new(small).expect("policy");
    let features = SharedFeaturesQ24V1::new(vec![1, 2]).expect("features");
    assert!(queue.admit(request(0, lane(1, "fence", "s"), &features)).expect("admit"));
    assert_eq!(
        queue.admit(request(1, lane(1, "fence", "s"), &features)),
        Err(BatchError::CapacityExceeded)
    );
    assert_eq!(queue.pending_count(), 1);
    assert_eq!(queue.queued_feature_bytes(), 16);
}
