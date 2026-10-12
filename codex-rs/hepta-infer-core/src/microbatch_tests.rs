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
fn cutover_of_one_scope_does_not_scan_or_tombstone_other_lanes() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    for index in 0..4096 {
        q.enqueue(
            1,
            intent(
                &format!("request-{index}"),
                &format!("scope-{index}"),
                1,
                1,
                100,
            ),
        )
        .unwrap();
    }
    assert_eq!(q.active_lanes(), 4096);
    assert_eq!(q.round_robin.len(), 4096);
    assert_eq!(q.scope_lanes.len(), 4096);

    // Repeated fence flips for one scope must never leave stale fairness
    // tickets or increase queue metadata with unrelated Cell populations.
    let scope = id("scope-0");
    let mut previous = id("request-0");
    for generation in 2..=80 {
        let removed =
            q.retain_scope_binding(&scope, Generation::new(generation).unwrap(), generation, 1);
        assert_eq!(removed, vec![previous]);
        let name = format!("cutover-{generation}");
        q.enqueue(1, intent(&name, "scope-0", generation, generation, 100))
            .unwrap();
        previous = id(&name);
        assert_eq!(q.pending(), 4096);
        assert_eq!(q.active_lanes(), 4096);
        assert_eq!(q.round_robin.len(), 4096);
        assert_eq!(q.lane_order.len(), 4096);
        assert_eq!(q.scope_lanes.len(), 4096);
    }

    let mut observed = BTreeSet::new();
    while q.pending() != 0 {
        let polled = q.poll(11).unwrap();
        assert!(polled.scanned_lanes <= 64);
        let batch = polled.batch.expect("all surviving lanes are ready");
        observed.insert(batch.requests[0].request_id.clone());
    }
    assert_eq!(observed.len(), 4096);
    assert!(observed.contains(&previous));
    assert_eq!(q.round_robin.len(), 0);
    assert_eq!(q.lane_order.len(), 0);
    assert_eq!(q.scope_lanes.len(), 0);
}

#[test]
fn scheduling_ticket_rollover_preserves_admission_and_fairness() {
    let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
    q.enqueue(1, intent("first", "scope-A", 1, 1, 100)).unwrap();
    q.next_order = u128::MAX;
    q.enqueue(1, intent("second", "scope-B", 1, 1, 100)).unwrap();
    assert_eq!(q.round_robin.len(), 2);
    let first = q.poll(11).unwrap().batch.unwrap();
    assert_eq!(first.requests[0].request_id, id("first"));
    let second = q.poll(11).unwrap().batch.unwrap();
    assert_eq!(second.requests[0].request_id, id("second"));
    assert_eq!(q.pending(), 0);
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
