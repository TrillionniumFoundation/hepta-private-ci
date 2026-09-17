#[tokio::test]
async fn multi_peer_orchestrator_preserves_partial_coverage_deterministically() {
    let signing_key = SigningKey::from_bytes(&[14; 32]);
    let peers = Arc::new(peer_directory(&signing_key, &[1, 2]));
    let clock = Arc::new(ManualClock::new(10));
    let authority = Arc::new(FixtureAuthority::new(850));
    let transport = Arc::new(FixtureTransport::new(signing_key, FixtureMode::PartialPeerTwo));
    let attempts = [1, 2]
        .into_iter()
        .map(|peer| {
            let query = query(peer);
            let lease = lease(&query);
            FederationAttemptV2 { query, lease }
        })
        .collect();

    let batch = execute_federated(
        transport,
        authority,
        peers,
        clock,
        CancellationToken::new(),
        attempts,
        2,
    )
    .await
    .unwrap_or_else(|error| panic!("valid federation batch: {error}"));

    assert_eq!(batch.coverage.requested_peers, 2);
    assert_eq!(batch.coverage.completed_peers, 2);
    assert_eq!(batch.coverage.failed_peers, 0);
    assert_eq!(batch.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(batch.items.len(), 1);
    assert_eq!(batch.results[0].peer_id, id("peer:1"));
    assert_eq!(batch.results[1].peer_id, id("peer:2"));
    batch
        .validate()
        .unwrap_or_else(|error| panic!("valid batch receipt: {error}"));
}

#[tokio::test]
async fn nonterminal_peer_never_fabricates_empty_data() {
    let signing_key = SigningKey::from_bytes(&[15; 32]);
    let peers = peer_directory(&signing_key, &[1]);
    let clock = ManualClock::new(10);
    let authority = FixtureAuthority::new(850);
    let query = query(1);
    let lease = lease(&query);
    let transport = FixtureTransport::new(signing_key, FixtureMode::NonTerminal);

    let result = execute_fixture(&transport, &authority, &peers, &clock, query, &lease)
        .await
        .unwrap_or_else(|error| panic!("nonterminal attempt returns receipt: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Indeterminate);
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert_eq!(result.coverage.failed_peers, 1);
}

#[tokio::test]
async fn cache_is_capability_bounded_and_revocation_purges_grant_index() {
    let signing_key = SigningKey::from_bytes(&[16; 32]);
    let peers = peer_directory(&signing_key, &[1]);
    let clock = ManualClock::new(10);
    let authority = FixtureAuthority::new(850);
    let query = query(1);
    let lease = lease(&query);
    let transport = FixtureTransport::new(signing_key, FixtureMode::Complete);
    let result = execute_fixture(
        &transport,
        &authority,
        &peers,
        &clock,
        query.clone(),
        &lease,
    )
    .await
    .unwrap_or_else(|error| panic!("valid result: {error}"));
    let capability = authority
        .verify_for_query(10, &query, &lease)
        .await
        .unwrap_or_else(|error| panic!("valid capability: {error}"));
    let cache = FederationCacheV2::default();
    cache
        .insert(10, query.clone(), lease.clone(), capability.clone(), result.clone())
        .unwrap_or_else(|error| panic!("cache insert: {error}"));
    assert_eq!(
        cache
            .get(10, query.binding_digest())
            .unwrap_or_else(|error| panic!("cache read: {error}")),
        Some(result)
    );

    authority.revoked.store(true, Ordering::SeqCst);
    let validity = cache
        .revalidate_remote(&authority, &clock, query.binding_digest())
        .await
        .unwrap_or_else(|error| panic!("revocation revalidation: {error}"));
    assert_eq!(validity, FederatedValidityV2::Revoked);
    assert!(
        cache
            .get(10, query.binding_digest())
            .unwrap_or_else(|error| panic!("cache read after purge: {error}"))
            .is_none()
    );
    assert_eq!(cache.purge_grant(&capability.grant_id).unwrap(), 0);
}

#[test]
fn cancellation_receipt_carries_no_success_assumption() {
    let receipt = observe_cancellation(
        FederationCancellationRequestV2 {
            cancellation_id: id("cancel:1"),
            query_id: id("query:1"),
            peer_id: id("peer:1"),
            query_binding_digest: digest("query-binding"),
            lease_epoch: 11,
            cancellation_nonce_digest: digest("cancel-nonce"),
        },
        false,
    )
    .unwrap_or_else(|error| panic!("valid cancellation receipt: {error}"));
    assert!(!receipt.terminal_observed);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert!(!receipt.receipt_digest.is_zero());
}
