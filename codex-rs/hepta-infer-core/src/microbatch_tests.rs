use super::*;
use std::time::Instant;

fn id(s: &str) -> StableId {
    StableId::new(s).unwrap()
}
fn digest(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}
fn limits() -> MicrobatchLimitsV1 {
    MicrobatchLimitsV1 {
        max_pending: 16_384,
        max_batch_size: 4,
        max_lanes_per_poll: 64,
        max_wait_ms: 10,
    }
}
fn intent(
    request: &str,
    scope: &str,
    generation: u64,
    fence: u64,
    deadline: u64,
) -> InferenceIntentV1 {
    InferenceIntentV1 {
        request_id: id(request),
        key: MicrobatchKeyV1 {
            scope_id: id(scope),
            model_digest: digest("model"),
            generation: Generation::new(generation).unwrap(),
            route_fence: fence,
            authority_epoch: 1,
        },
        feature_digest: digest("feature"),
        shared_features: None,
        deadline_ms: deadline,
    }
}

#[test]
fn never_mix_scope_generation_or_fence() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    q.enqueue(1, intent("a", "scopeA", 1, 1, 100)).unwrap();
    q.enqueue(1, intent("b", "scopeA", 1, 2, 100)).unwrap();
    q.enqueue(1, intent("c", "scopeB", 1, 1, 100)).unwrap();
    q.enqueue(1, intent("d", "scopeA", 2, 1, 100)).unwrap();
    let mut got = BTreeSet::new();
    for _ in 0..4 {
        let batch = q.poll(11).unwrap().batch.unwrap();
        assert_eq!(batch.requests.len(), 1);
        assert_eq!(batch.requests[0].key, batch.key);
        assert_eq!(batch.authority, AuthorityPosture::DENY_ALL);
        got.insert(batch.requests[0].request_id.clone());
    }
    assert_eq!(got.len(), 4);
    assert_eq!(q.pending(), 0);
}

#[test]
fn immutable_payload_is_shared_without_vector_copy() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    let buffer = SharedFeatureBufferV1::from_vec(vec![0, 1 << 24]).unwrap();
    let mut request = intent("payload", "scope", 1, 1, 100);
    request.feature_digest = buffer.digest();
    request.shared_features = Some(buffer.clone());
    q.enqueue(1, request).unwrap();
    let plan = q.poll(11).unwrap().batch.unwrap();
    assert!(
        plan.requests[0]
            .shared_features
            .as_ref()
            .unwrap()
            .shares_allocation_with(&buffer)
    );
}

#[test]
fn rejected_future_admission_never_poisoned_monotonic_clock() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    q.enqueue(10, intent("original", "scope-a", 1, 1, 100))
        .unwrap();

    let mut invalid_digest = intent("invalid", "scope-b", 1, 1, 2_000);
    invalid_digest.feature_digest = Digest32::ZERO;
    assert_eq!(
        q.enqueue(1_000, invalid_digest),
        Err(SchedulerErrorV1::EmptyDigest)
    );

    // The rejected request is not a clock observation: time 11 remains valid.
    q.enqueue(11, intent("accepted", "scope-b", 1, 1, 100))
        .unwrap();

    assert_eq!(
        q.enqueue(999, intent("accepted", "scope-b", 1, 1, 2_000)),
        Err(SchedulerErrorV1::DuplicateRequest)
    );

    // Neither the invalid feature nor the duplicate may advance the clock.
    assert_eq!(q.pending(), 2);
    assert!(q.poll(20).unwrap().batch.is_some());
}

#[test]
fn rejected_expired_request_does_not_fence_later_valid_admission() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    q.enqueue(4, intent("first", "one", 1, 1, 100)).unwrap();
    assert_eq!(
        q.enqueue(200, intent("expired", "two", 1, 1, 100)),
        Err(SchedulerErrorV1::Expired)
    );
    q.enqueue(5, intent("second", "two", 1, 1, 100))
        .unwrap();
    assert_eq!(q.pending(), 2);
    assert_eq!(q.poll(15).unwrap().pending, 1);
}

#[test]
fn capacity_duplicate_and_expired_fail_closed() {
    let mut conf = limits();
    conf.max_pending = 1;
    conf.max_batch_size = 1;
    let mut q = BoundedMicrobatchSchedulerV1::new(conf).unwrap();
    q.enqueue(1, intent("a", "one", 1, 1, 50)).unwrap();
    assert_eq!(
        q.enqueue(1, intent("a", "one", 1, 1, 50)),
        Err(SchedulerErrorV1::DuplicateRequest)
    );
    assert_eq!(
        q.enqueue(1, intent("b", "two", 1, 1, 50)),
        Err(SchedulerErrorV1::Capacity)
    );
    let p = q.poll(51).unwrap();
    assert_eq!(p.expired_request_ids, vec![id("a")]);
    assert!(p.batch.is_none());
    assert_eq!(q.pending(), 0);
    assert_eq!(
        q.enqueue(50, intent("x", "s", 1, 1, 100)),
        Err(SchedulerErrorV1::ClockRegressed)
    );
}

#[test]
fn cutover_drops_only_stale_scope() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    q.enqueue(1, intent("old", "scope", 1, 1, 100)).unwrap();
    q.enqueue(1, intent("new", "scope", 2, 2, 100)).unwrap();
    q.enqueue(1, intent("other", "another", 1, 1, 100)).unwrap();
    assert_eq!(
        q.retain_scope_binding(&id("scope"), Generation::new(2).unwrap(), 2, 1),
        vec![id("old")]
    );
    assert_eq!(q.pending(), 2);
    assert_eq!(q.active_lanes(), 2);
}

#[test]
fn compatible_scope_lanes_coalesce_without_erasing_original_authority() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    q.enqueue(1, intent("a", "scopeA", 1, 1, 100)).unwrap();
    q.enqueue(1, intent("b", "scopeB", 1, 8, 100)).unwrap();
    q.enqueue(1, intent("c", "scopeC", 1, 19, 100)).unwrap();
    let batch = q.poll_physically_compatible(11).unwrap().batch.unwrap();
    assert_eq!(batch.requests.len(), 3);
    assert_eq!(batch.requests[0].key.scope_id, id("scopeA"));
    assert_eq!(batch.requests[1].key.scope_id, id("scopeB"));
    assert_eq!(batch.requests[2].key.scope_id, id("scopeC"));
    assert_eq!(batch.requests[1].key.route_fence, 8);
    assert_eq!(batch.requests[2].key.route_fence, 19);
    assert_eq!(batch.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(q.pending(), 0);
}

#[test]
fn coalescing_cannot_mix_backend_generation_or_epoch() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    q.enqueue(1, intent("a", "scopeA", 1, 1, 100)).unwrap();
    q.enqueue(1, intent("generation", "scopeB", 2, 1, 100))
        .unwrap();
    let mut changed_epoch = intent("epoch", "scopeC", 1, 1, 100);
    changed_epoch.key.authority_epoch = 2;
    q.enqueue(1, changed_epoch).unwrap();
    let mut changed_model = intent("model", "scopeD", 1, 1, 100);
    changed_model.key.model_digest = digest("different-model");
    q.enqueue(1, changed_model).unwrap();
    let batch = q.poll_physically_compatible(11).unwrap().batch.unwrap();
    assert_eq!(batch.requests.len(), 1);
    assert_eq!(q.pending(), 3);
    for _ in 0..3 {
        let next = q.poll_physically_compatible(11).unwrap().batch.unwrap();
        assert_eq!(next.requests.len(), 1);
    }
    assert_eq!(q.pending(), 0);
}

#[test]
fn compatible_coalescing_respects_global_scan_and_batch_limits() {
    let mut config = limits();
    config.max_lanes_per_poll = 2;
    config.max_batch_size = 2;
    let mut q = BoundedMicrobatchSchedulerV1::new(config).unwrap();
    for number in 0..4 {
        q.enqueue(
            1,
            intent(
                &format!("request-{number}"),
                &format!("scope-{number}"),
                1,
                1,
                100,
            ),
        )
        .unwrap();
    }
    let first = q.poll_physically_compatible(11).unwrap();
    assert_eq!(first.scanned_lanes, 2);
    assert_eq!(first.batch.unwrap().requests.len(), 2);
    assert_eq!(first.pending, 2);
    let second = q.poll_physically_compatible(11).unwrap();
    assert_eq!(second.batch.unwrap().requests.len(), 2);
    assert_eq!(second.pending, 0);
}

#[test]
fn affinity_index_fills_batch_without_scanning_unrelated_scopes() {
    let mut config = limits();
    config.max_lanes_per_poll = 2;
    config.max_batch_size = 2;
    let mut q = BoundedMicrobatchSchedulerV1::new(config).unwrap();
    q.enqueue(1, intent("first", "a-first", 1, 1, 100)).unwrap();
    let mut unrelated = intent("other", "b-unrelated", 1, 1, 100);
    unrelated.key.model_digest = digest("different-model");
    q.enqueue(1, unrelated).unwrap();
    q.enqueue(1, intent("compatible", "z-compatible", 1, 99, 100))
        .unwrap();

    let result = q.poll_physically_compatible(11).unwrap();
    assert_eq!(result.scanned_lanes, 2);
    assert_eq!(result.pending, 1);
    let batch = result.batch.unwrap();
    assert_eq!(batch.requests.len(), 2);
    assert_eq!(batch.requests[0].request_id, id("first"));
    assert_eq!(batch.requests[1].request_id, id("compatible"));
    assert_eq!(batch.requests[1].key.route_fence, 99);
    let other = q.poll_physically_compatible(11).unwrap().batch.unwrap();
    assert_eq!(other.requests[0].request_id, id("other"));
    assert_eq!(q.pending(), 0);
    assert_eq!(q.active_lanes(), 0);
    assert!(q.physical_lanes.is_empty());
}

#[test]
fn physical_affinity_index_cleans_up_after_expiry_and_cutover() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    q.enqueue(1, intent("expired", "scope-a", 1, 1, 5)).unwrap();
    q.enqueue(1, intent("fenced", "scope-b", 1, 1, 100))
        .unwrap();
    q.enqueue(1, intent("live", "scope-c", 1, 1, 100)).unwrap();
    assert_eq!(
        q.retain_scope_binding(&id("scope-b"), Generation::new(2).unwrap(), 1, 1),
        vec![id("fenced")]
    );
    let result = q.poll_physically_compatible(11).unwrap();
    assert_eq!(result.expired_request_ids, vec![id("expired")]);
    assert_eq!(result.batch.unwrap().requests[0].request_id, id("live"));
    assert_eq!(q.pending(), 0);
    assert!(q.physical_lanes.is_empty());
}

#[test]
fn coalesced_scope_reuses_its_stale_round_robin_slot_on_readmission() {
    let mut config = limits();
    config.max_batch_size = 2;
    config.max_lanes_per_poll = 2;
    let mut q = BoundedMicrobatchSchedulerV1::new(config).unwrap();

    q.enqueue(1, intent("first", "scope-a", 1, 1, 100))
        .unwrap();
    q.enqueue(1, intent("coalesced", "scope-b", 1, 2, 100))
        .unwrap();
    let first = q.poll_physically_compatible(11).unwrap().batch.unwrap();
    assert_eq!(first.requests.len(), 2);
    assert_eq!(q.pending(), 0);
    // scope-b was consumed by the affinity index, so it still has exactly
    // one unvisited round-robin slot until the next ordinary poll.
    assert_eq!(q.round_robin.len(), 1);
    assert_eq!(q.round_robin_members.len(), 1);

    q.enqueue(12, intent("readmitted", "scope-b", 1, 2, 100))
        .unwrap();
    assert_eq!(q.active_lanes(), 1);
    assert_eq!(q.round_robin.len(), 1);
    assert_eq!(q.round_robin_members.len(), 1);
    let second = q.poll_physically_compatible(22).unwrap().batch.unwrap();
    assert_eq!(second.requests.len(), 1);
    assert_eq!(second.requests[0].request_id, id("readmitted"));
    assert_eq!(q.pending(), 0);
    assert!(q.round_robin_members.is_empty());
}

#[test]
fn repeated_cross_scope_coalescing_never_accumulates_duplicate_queue_slots() {
    let mut config = limits();
    config.max_batch_size = 2;
    config.max_lanes_per_poll = 2;
    let mut q = BoundedMicrobatchSchedulerV1::new(config).unwrap();

    for round in 0..128_u64 {
        let now = 1 + round * 20;
        q.enqueue(
            now,
            intent(&format!("a-{round}"), "scope-a", 1, 1, now + 100),
        )
        .unwrap();
        q.enqueue(
            now,
            intent(&format!("b-{round}"), "scope-b", 1, 2, now + 100),
        )
        .unwrap();
        let result = q.poll_physically_compatible(now + 10).unwrap();
        assert_eq!(result.batch.unwrap().requests.len(), 2);
        assert_eq!(q.pending(), 0);
        assert!(q.round_robin.len() <= 1);
        assert_eq!(q.round_robin_members.len(), q.round_robin.len());
    }
}

// Opt-in source benchmark: not hardware acceptance, report raw durations.
#[test]
#[ignore = "run with --ignored --nocapture on deployment hardware"]
fn benchmark_64_256_1024_4096_scopes() {
    for scopes in [64, 256, 1024, 4096] {
        let conf = MicrobatchLimitsV1 {
            max_pending: 16_384,
            max_batch_size: 4,
            max_lanes_per_poll: 64,
            max_wait_ms: 10,
        };
        let mut q = BoundedMicrobatchSchedulerV1::new(conf).unwrap();
        let start = Instant::now();
        for i in 0..scopes {
            let name = format!("scope{i}");
            q.enqueue(1, intent(&format!("req{i}"), &name, 1, 1, 1000))
                .unwrap();
        }
        let admission = start.elapsed();
        let start = Instant::now();
        let mut count = 0;
        while q.pending() != 0 {
            if let Some(batch) = q.poll(20).unwrap().batch {
                count += batch.requests.len();
            }
        }
        assert_eq!(count, scopes);
        eprintln!(
            "scopes={scopes} admission_us={} drain_us={}",
            admission.as_micros(),
            start.elapsed().as_micros()
        );
    }
}
