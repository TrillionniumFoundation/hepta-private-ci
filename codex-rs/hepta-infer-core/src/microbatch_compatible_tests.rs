use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn request(
    id_value: &str,
    scope: &str,
    encoder: &str,
    generation: u64,
    route_fence: u64,
    deadline: u64,
) -> InferenceIntentV1 {
    InferenceIntentV1 {
        request_id: id(id_value),
        key: MicrobatchKeyV1 {
            scope_id: id(scope),
            model_digest: digest("common-model"),
            generation: Generation::new(generation).unwrap(),
            route_fence,
            authority_epoch: 7,
        },
        feature_digest: digest("shared-features"),
        encoder_digest: Some(digest(encoder)),
        shared_features: None,
        deadline_ms: deadline,
    }
}

fn scheduler() -> BoundedMicrobatchSchedulerV1 {
    BoundedMicrobatchSchedulerV1::new(MicrobatchLimitsV1 {
        max_pending: 128,
        max_batch_size: 4,
        max_lanes_per_poll: 8,
        max_wait_ms: 5,
    })
    .unwrap()
}

#[test]
fn compatible_requests_from_three_scopes_share_one_plan_but_keep_fences() {
    let mut q = scheduler();
    q.enqueue(1, request("a", "scope-a", "encoder-1", 3, 5, 100))
        .unwrap();
    q.enqueue(1, request("b", "scope-b", "encoder-1", 3, 7, 100))
        .unwrap();
    q.enqueue(1, request("c", "scope-c", "encoder-1", 3, 9, 100))
        .unwrap();
    let batch = q.poll_physical_compatible(7).unwrap().batch.unwrap();
    assert_eq!(batch.requests.len(), 3);
    assert_eq!(batch.compatibility.encoder_digest, digest("encoder-1"));
    assert_eq!(batch.authority, AuthorityPosture::DENY_ALL);
    let scopes: BTreeSet<_> = batch
        .requests
        .iter()
        .map(|item| item.key.scope_id.clone())
        .collect();
    let fences: BTreeSet<_> = batch
        .requests
        .iter()
        .map(|item| item.key.route_fence)
        .collect();
    assert_eq!(scopes.len(), 3);
    assert_eq!(fences, BTreeSet::from([5, 7, 9]));
    assert_eq!(q.pending(), 0);
}

#[test]
fn never_coalesce_different_encoder_or_generation() {
    let mut q = scheduler();
    q.enqueue(1, request("a", "scope-a", "encoder-1", 3, 5, 100))
        .unwrap();
    q.enqueue(1, request("b", "scope-b", "encoder-2", 3, 7, 100))
        .unwrap();
    q.enqueue(1, request("c", "scope-c", "encoder-1", 4, 5, 100))
        .unwrap();
    let first = q.poll_physical_compatible(7).unwrap().batch.unwrap();
    assert_eq!(first.requests.len(), 1);
    let second = q.poll_physical_compatible(7).unwrap().batch.unwrap();
    assert_eq!(second.requests.len(), 1);
    let third = q.poll_physical_compatible(7).unwrap().batch.unwrap();
    assert_eq!(third.requests.len(), 1);
    let encoders: BTreeSet<_> = [first, second, third]
        .iter()
        .map(|plan| {
            (
                plan.compatibility.encoder_digest,
                plan.compatibility.generation,
            )
        })
        .collect();
    assert_eq!(encoders.len(), 3);
    assert_eq!(q.pending(), 0);
}

#[test]
fn expiry_and_cutover_do_not_transfer_stale_scope_authority() {
    let mut q = scheduler();
    q.enqueue(1, request("expired", "s-1", "encoder", 3, 1, 2))
        .unwrap();
    q.enqueue(1, request("stale", "s-1", "encoder", 3, 2, 100))
        .unwrap();
    q.enqueue(1, request("valid", "s-2", "encoder", 3, 5, 100))
        .unwrap();
    let removed = q.retain_scope_binding(&id("s-1"), Generation::new(3).unwrap(), 1, 7);
    assert_eq!(removed, vec![id("stale")]);
    let poll = q.poll_physical_compatible(7).unwrap();
    assert_eq!(poll.expired_request_ids, vec![id("expired")]);
    assert_eq!(poll.batch.unwrap().requests[0].request_id, id("valid"));
    assert_eq!(q.pending(), 0);
}

#[test]
fn capacity_keeps_physical_plan_under_limit_across_many_scopes() {
    let mut q = scheduler();
    for index in 0..12 {
        q.enqueue(
            1,
            request(
                &format!("request-{index}"),
                &format!("scope-{index}"),
                "encoder",
                3,
                5,
                100,
            ),
        )
        .unwrap();
    }
    let mut counts = Vec::new();
    while q.pending() != 0 {
        let result = q.poll_physical_compatible(7).unwrap();
        assert!(result.scanned_lanes <= 8);
        let batch = result.batch.unwrap();
        assert!(batch.requests.len() <= 4);
        counts.push(batch.requests.len());
    }
    assert_eq!(counts, vec![4, 4, 4]);
}
