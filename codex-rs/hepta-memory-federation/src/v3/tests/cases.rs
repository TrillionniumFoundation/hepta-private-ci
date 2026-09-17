#[tokio::test]
async fn partial_empty_remains_partial_and_ttl_is_capability_bounded() {
    let fixture = authority_fixture();
    let peer_key = SigningKey::from_bytes(&[11; 32]);
    let spec = spec("query:partial", 700, 10);
    let permit = permit(&spec, &fixture.issuer, "peer:1", "nonce:1", "grant:1", 1);
    let client = FederationClientV3::new(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry(100, &[("peer:1", "peer-key:1", &peer_key, 900)]),
        FixtureTransport::simple(
            [("peer:1", peer_key, FixtureOutcome::PartialEmpty)],
            800,
        ),
        ScriptedClock::fixed(100),
        32,
    )
    .expect("client");
    let result = client
        .query(FederatedReadPlanV3 {
            spec,
            peers: vec![permit],
            maximum_concurrency: 1,
        })
        .await
        .expect("query");
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.expires_unix_ms, 700);
    assert_eq!(result.coverage.completed_peers, 1);
    assert_eq!(result.coverage.peers[0].completeness, FederatedCompletenessV2::Partial);
    result.validate().expect("aggregate validates");
}

#[tokio::test]
async fn tampered_remote_payload_is_rejected_without_evidence_release() {
    let fixture = authority_fixture();
    let peer_key = SigningKey::from_bytes(&[12; 32]);
    let spec = spec("query:tamper", 700, 10);
    let permit = permit(&spec, &fixture.issuer, "peer:1", "nonce:1", "grant:1", 2);
    let client = FederationClientV3::new(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry(100, &[("peer:1", "peer-key:1", &peer_key, 900)]),
        FixtureTransport::simple([("peer:1", peer_key, FixtureOutcome::Tampered)], 800),
        ScriptedClock::fixed(100),
        32,
    )
    .expect("client");
    let result = client
        .query(FederatedReadPlanV3 {
            spec,
            peers: vec![permit],
            maximum_concurrency: 1,
        })
        .await
        .expect("explicit aggregate");
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Indeterminate);
    assert_eq!(result.coverage.failed_peers, 1);
    assert_eq!(result.coverage.peers[0].failure, Some(FederationPeerFailureV3::InvalidResponse));
}

#[tokio::test]
async fn fresh_clock_after_transport_prevents_deadline_toctou() {
    let fixture = authority_fixture();
    let peer_key = SigningKey::from_bytes(&[13; 32]);
    let spec = spec("query:clock", 600, 10);
    let permit = permit(&spec, &fixture.issuer, "peer:1", "nonce:1", "grant:1", 3);
    let client = FederationClientV3::new(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry(100, &[("peer:1", "peer-key:1", &peer_key, 900)]),
        FixtureTransport::simple([("peer:1", peer_key, FixtureOutcome::Complete)], 800),
        ScriptedClock::new([100, 100, 650]),
        32,
    )
    .expect("client");
    let result = client
        .query(FederatedReadPlanV3 {
            spec,
            peers: vec![permit],
            maximum_concurrency: 1,
        })
        .await
        .expect("explicit aggregate");
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Indeterminate);
    assert_eq!(result.coverage.peers[0].failure, Some(FederationPeerFailureV3::TimedOut));
}

#[tokio::test]
async fn revocation_racing_transport_fails_at_final_authority_fence() {
    let fixture = authority_fixture();
    let peer_key = SigningKey::from_bytes(&[14; 32]);
    let spec = spec("query:revoke", 700, 10);
    let permit = permit(&spec, &fixture.issuer, "peer:1", "nonce:1", "grant:revoke", 4);
    let mut transport = FixtureTransport::simple(
        [("peer:1", peer_key.clone(), FixtureOutcome::Complete)],
        800,
    );
    transport.revoke_during_send = Some((fixture.authority.clone(), "grant:revoke".to_owned()));
    let client = FederationClientV3::new(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry(100, &[("peer:1", "peer-key:1", &peer_key, 900)]),
        transport,
        ScriptedClock::fixed(100),
        32,
    )
    .expect("client");
    let result = client
        .query(FederatedReadPlanV3 {
            spec,
            peers: vec![permit],
            maximum_concurrency: 1,
        })
        .await
        .expect("explicit aggregate");
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::Revoked);
    assert_eq!(result.coverage.peers[0].failure, Some(FederationPeerFailureV3::Revoked));
}

#[tokio::test]
async fn multi_peer_failure_cannot_become_global_empty_or_complete() {
    let fixture = authority_fixture();
    let peer1 = SigningKey::from_bytes(&[21; 32]);
    let peer2 = SigningKey::from_bytes(&[22; 32]);
    let spec = spec("query:multi", 700, 10);
    let permits = vec![
        permit(&spec, &fixture.issuer, "peer:1", "nonce:1", "grant:1", 5),
        permit(&spec, &fixture.issuer, "peer:2", "nonce:2", "grant:2", 6),
    ];
    let client = FederationClientV3::new(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry(
            100,
            &[
                ("peer:1", "peer-key:1", &peer1, 900),
                ("peer:2", "peer-key:2", &peer2, 900),
            ],
        ),
        FixtureTransport::simple(
            [
                ("peer:1", peer1, FixtureOutcome::Empty),
                ("peer:2", peer2, FixtureOutcome::Unavailable),
            ],
            800,
        ),
        ScriptedClock::fixed(100),
        32,
    )
    .expect("client");
    let result = client
        .query(FederatedReadPlanV3 {
            spec,
            peers: permits,
            maximum_concurrency: 2,
        })
        .await
        .expect("query");
    assert!(result.items.is_empty());
    assert_eq!(result.coverage.completed_peers, 1);
    assert_eq!(result.coverage.failed_peers, 1);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
}

#[tokio::test]
async fn fanout_is_concurrency_bounded_and_merge_is_deterministic() {
    let fixture = authority_fixture();
    let mut keys = Vec::new();
    let mut registrations = Vec::new();
    let mut outcomes = Vec::new();
    let spec = spec("query:bounded", 10_000, 10);
    let mut permits = Vec::new();
    for index in 1..=4u8 {
        let peer = format!("peer:{index}");
        let key_id = format!("peer-key:{index}");
        let key = SigningKey::from_bytes(&[30 + index; 32]);
        permits.push(permit(
            &spec,
            &fixture.issuer,
            &peer,
            &format!("nonce:{index}"),
            &format!("grant:{index}"),
            10 + index,
        ));
        keys.push((peer.clone(), key_id.clone(), key.clone()));
        outcomes.push((peer, key, FixtureOutcome::Complete));
    }
    for (peer, key_id, key) in &keys {
        registrations.push((peer.as_str(), key_id.as_str(), key, 20_000));
    }
    let active = Arc::new(AtomicUsize::new(0));
    let maximum = Arc::new(AtomicUsize::new(0));
    let mut transport = FixtureTransport::simple(
        outcomes
            .iter()
            .map(|(peer, key, outcome)| (peer.clone(), key.clone(), *outcome))
            .collect::<Vec<_>>(),
        15_000,
    );
    transport.active = Some(Arc::clone(&active));
    transport.maximum_active = Some(Arc::clone(&maximum));
    transport.delay_ms = 15;
    let client = FederationClientV3::new(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry(100, &registrations),
        transport,
        ScriptedClock::fixed(100),
        32,
    )
    .expect("client");
    let result = client
        .query(FederatedReadPlanV3 {
            spec,
            peers: permits,
            maximum_concurrency: 2,
        })
        .await
        .expect("query");
    assert_eq!(result.coverage.completed_peers, 4);
    assert!(maximum.load(AtomicOrdering::Acquire) <= 2);
    assert_eq!(result.items.len(), 4);
    let mut sorted = result.items.clone();
    sorted.sort_by(|left, right| {
        left.source_owner_id
            .cmp(&right.source_owner_id)
            .then_with(|| left.record_id.cmp(&right.record_id))
            .then_with(|| left.record_revision.cmp(&right.record_revision))
    });
    assert_eq!(result.items, sorted);
    assert_eq!(result.result_digest, result.compute_result_digest());
}

#[tokio::test]
async fn cache_requires_fresh_authority_and_revocation_purge_removes_it() {
    let fixture = authority_fixture();
    let peer_key = SigningKey::from_bytes(&[41; 32]);
    let spec = spec("query:cache", 700, 10);
    let original = permit(&spec, &fixture.issuer, "peer:1", "nonce:1", "grant:cache", 50);
    let target = original.target.clone();
    let key = FederationCacheKeyV3 {
        peer_id: target.peer_id.clone(),
        query_binding_digest: spec.peer_query(&target).binding_digest(),
    };
    let client = FederationClientV3::new(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry(100, &[("peer:1", "peer-key:1", &peer_key, 900)]),
        FixtureTransport::simple([("peer:1", peer_key, FixtureOutcome::Complete)], 800),
        ScriptedClock::fixed(100),
        32,
    )
    .expect("client");
    let initial = client
        .query(FederatedReadPlanV3 {
            spec: spec.clone(),
            peers: vec![original],
            maximum_concurrency: 1,
        })
        .await
        .expect("query");
    assert_eq!(initial.items.len(), 1);
    let fresh = signed_grant(
        &fixture.issuer,
        spec.authority_binding(&target).expect("binding"),
        "grant:cache",
        51,
    );
    let cached = client
        .revalidate_remote(&key, &fresh, spec.generation_vector_digest)
        .expect("fresh authority revalidates cache");
    assert_eq!(cached.items.len(), 1);
    assert_eq!(
        client
            .purge_revocations(&FinalUseRevocations {
                authority_epoch: 9,
                revision: 2,
                revoked_grant_ids: BTreeSet::from(["grant:cache".to_owned()]),
            })
            .expect("purge"),
        1
    );
    let another = signed_grant(
        &fixture.issuer,
        spec.authority_binding(&target).expect("binding"),
        "grant:cache",
        52,
    );
    assert_eq!(
        client.revalidate_remote(&key, &another, spec.generation_vector_digest),
        Err(FederationV3Error::CacheMiss)
    );
}

#[tokio::test]
async fn cancel_query_drops_inflight_transport_and_returns_indeterminate() {
    let fixture = authority_fixture();
    let peer_key = SigningKey::from_bytes(&[42; 32]);
    let spec = spec("query:cancel", 10_000, 10);
    let permit = permit(&spec, &fixture.issuer, "peer:1", "nonce:1", "grant:cancel", 60);
    let query_id = spec.query_id.clone();
    let client = FederationClientV3::new(
        fixture.authority,
        "authority-key:1".to_owned(),
        registry(100, &[("peer:1", "peer-key:1", &peer_key, 20_000)]),
        BlockingTransport,
        ScriptedClock::fixed(100),
        32,
    )
    .expect("client");
    let runner = client.clone();
    let task = tokio::spawn(async move {
        runner
            .query(FederatedReadPlanV3 {
                spec,
                peers: vec![permit],
                maximum_concurrency: 1,
            })
            .await
    });
    let mut cancelled = false;
    for _ in 0..32 {
        if client.cancel_query(&query_id).expect("cancel query") {
            cancelled = true;
            break;
        }
        tokio::task::yield_now().await;
    }
    assert!(cancelled, "query was never registered for cancellation");
    let result = task.await.expect("join").expect("explicit aggregate");
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Indeterminate);
    assert_eq!(result.coverage.peers[0].failure, Some(FederationPeerFailureV3::Cancelled));
    assert!(!client.cancel_query(&query_id).expect("query removed"));
}
