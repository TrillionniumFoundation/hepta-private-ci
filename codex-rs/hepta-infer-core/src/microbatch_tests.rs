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
fn secondary_physical_index_skips_unrelated_scopes_and_reuses_drained_lane_safely() {
    let mut config = limits();
    config.max_batch_size = 3;
    config.max_lanes_per_poll = 3;
    let mut q = BoundedMicrobatchSchedulerV1::new(config).unwrap();
    q.enqueue(1, intent("a", "scopeA", 1, 1, 100)).unwrap();
    for i in 2..=4 {
        q.enqueue(
            1,
            intent(
                &format!("other-{i}"),
                &format!("scope{i}"),
                i,
                1,
                100,
            ),
        )
        .unwrap();
    }
    q.enqueue(1, intent("e", "scopeE", 1, 8, 100)).unwrap();
    q.enqueue(1, intent("f", "scopeF", 1, 9, 100)).unwrap();
    let first = q.poll_physically_compatible(11).unwrap();
    assert_eq!(first.scanned_lanes, 3);
    let batch = first.batch.unwrap();
    assert_eq!(batch.requests.len(), 3);
    assert!(batch.requests.iter().all(|intent| intent.key.generation.get() == 1));
    assert_eq!(first.pending, 3);

    // ScopeE was physically coalesced but its global round-robin key can
    // remain lazy until visited. New work must not create duplicate cursors.
    q.enqueue(12, intent("e2", "scopeE", 1, 8, 100)).unwrap();
    let mut seen = BTreeSet::new();
    for _ in 0..12 {
        let polled = q.poll(22).unwrap();
        if let Some(next) = polled.batch {
            for req in next.requests {
                assert!(seen.insert(req.request_id));
            }
        }
        if q.pending() == 0 {
            break;
        }
    }
    assert_eq!(seen.len(), 4);
    assert!(seen.contains(&id("e2")));
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
