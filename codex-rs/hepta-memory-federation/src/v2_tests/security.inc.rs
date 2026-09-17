#[tokio::test]
async fn signed_response_is_canonically_verified_and_ttl_is_capability_bounded() {
    let signing_key = SigningKey::from_bytes(&[7; 32]);
    let peers = peer_directory(&signing_key, &[1]);
    let clock = ManualClock::new(10);
    let authority = FixtureAuthority::new(850);
    let query = query(1);
    let lease = lease(&query);
    let transport = FixtureTransport::new(signing_key, FixtureMode::Complete);

    let result = execute_fixture(&transport, &authority, &peers, &clock, query, &lease)
        .await
        .unwrap_or_else(|error| panic!("valid signed result: {error}"));

    assert_eq!(result.expires_unix_ms, 850);
    assert_eq!(result.completeness, FederatedCompletenessV2::Complete);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
    assert_eq!(result.items.len(), 1);
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
    result
        .validate()
        .unwrap_or_else(|error| panic!("valid result receipt: {error}"));
}

#[tokio::test]
async fn partial_empty_remote_response_remains_partial() {
    let signing_key = SigningKey::from_bytes(&[8; 32]);
    let peers = peer_directory(&signing_key, &[1]);
    let clock = ManualClock::new(10);
    let authority = FixtureAuthority::new(850);
    let query = query(1);
    let lease = lease(&query);
    let transport = FixtureTransport::new(signing_key, FixtureMode::PartialEmpty);

    let result = execute_fixture(&transport, &authority, &peers, &clock, query, &lease)
        .await
        .unwrap_or_else(|error| panic!("partial response remains usable: {error}"));

    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
}

#[tokio::test]
async fn payload_tamper_and_bad_peer_signature_fail_closed() {
    for mode in [FixtureMode::InvalidPayloadDigest, FixtureMode::InvalidSignature] {
        let signing_key = SigningKey::from_bytes(&[9; 32]);
        let peers = peer_directory(&signing_key, &[1]);
        let clock = ManualClock::new(10);
        let authority = FixtureAuthority::new(850);
        let query = query(1);
        let lease = lease(&query);
        let transport = FixtureTransport::new(signing_key, mode);
        let error = execute_fixture(&transport, &authority, &peers, &clock, query, &lease)
            .await
            .expect_err("tampered response must fail");
        assert!(matches!(
            error,
            FederationV2Error::DigestMismatch("response_payload")
                | FederationV2Error::InvalidPeerSignature
        ));
    }
}

#[tokio::test]
async fn fresh_post_io_clock_rejects_deadline_crossing() {
    let signing_key = SigningKey::from_bytes(&[10; 32]);
    let peers = peer_directory(&signing_key, &[1]);
    let clock = ManualClock::new(10);
    let authority = FixtureAuthority::new(2_000);
    let query = query(1);
    let lease = lease(&query);
    let mut transport = FixtureTransport::new(signing_key, FixtureMode::Complete);
    transport.clock_after_send = Some(clock.clone());
    transport.post_send_now = Some(query.deadline_unix_ms);

    let error = execute_fixture(&transport, &authority, &peers, &clock, query, &lease)
        .await
        .expect_err("deadline crossing must fail after I/O");
    assert_eq!(error, FederationV2Error::DeadlineExpired);
}

#[tokio::test]
async fn revocation_during_io_is_revalidated_before_result_admission() {
    let signing_key = SigningKey::from_bytes(&[11; 32]);
    let peers = peer_directory(&signing_key, &[1]);
    let clock = ManualClock::new(10);
    let authority = FixtureAuthority::new(850);
    let query = query(1);
    let lease = lease(&query);
    let mut transport = FixtureTransport::new(signing_key, FixtureMode::Complete);
    transport.revoke_after_send = Some(Arc::clone(&authority.revoked));

    let error = execute_fixture(&transport, &authority, &peers, &clock, query, &lease)
        .await
        .expect_err("mid-flight revocation must fail");
    assert_eq!(error, FederationV2Error::LeaseRevoked);
}

#[tokio::test]
async fn strong_query_binding_rejects_replayed_nonce_or_binding() {
    let signing_key = SigningKey::from_bytes(&[12; 32]);
    let peers = peer_directory(&signing_key, &[1]);
    let authority = FixtureAuthority::new(850);
    let query = query(1);
    let lease = lease(&query);
    let transport = FixtureTransport::new(signing_key, FixtureMode::Complete);
    let capability = authority
        .verify_for_query(10, &query, &lease)
        .await
        .unwrap_or_else(|error| panic!("valid capability: {error}"));
    let mut response = transport.response(&query, &capability);
    response.request_nonce_digest = digest("replayed-request-nonce");
    response.response_digest = response.compute_response_digest();
    response.signature = transport
        .signing_key
        .sign(&response.signing_bytes())
        .to_bytes();

    let error = response
        .verify_for_request(&query, &lease, &capability, &peers.resolve_peer(&query.peer_id).unwrap())
        .expect_err("replayed request nonce must fail");
    assert_eq!(error, FederationV2Error::DigestMismatch("response_request_nonce"));
}

#[tokio::test]
async fn cancellation_token_reaches_and_cancels_real_transport_attempt() {
    let signing_key = SigningKey::from_bytes(&[13; 32]);
    let peers = Arc::new(peer_directory(&signing_key, &[1]));
    let clock = Arc::new(ManualClock::new(10));
    let authority = Arc::new(FixtureAuthority::new(850));
    let query = query(1);
    let lease = lease(&query);
    let transport = Arc::new(FixtureTransport::new(signing_key, FixtureMode::Pending));
    let captured = Arc::clone(&transport.captured_cancellation);
    let cancel = CancellationToken::new();
    let task_cancel = cancel.clone();
    let transport_for_task = Arc::clone(&transport);
    let authority_for_task = Arc::clone(&authority);
    let peers_for_task = Arc::clone(&peers);
    let clock_for_task = Arc::clone(&clock);

    let task = tokio::spawn(async move {
        execute_once(
            transport_for_task.as_ref(),
            authority_for_task.as_ref(),
            peers_for_task.as_ref(),
            clock_for_task.as_ref(),
            &task_cancel,
            query,
            &lease,
        )
        .await
    });
    for _ in 0..100 {
        if captured.lock().expect("captured cancellation mutex").is_some() {
            break;
        }
        tokio::task::yield_now().await;
    }
    cancel.cancel();
    let error = task
        .await
        .expect("join succeeds")
        .expect_err("cancelled attempt must fail");
    assert_eq!(error, FederationV2Error::Cancelled);
    let token = captured
        .lock()
        .expect("captured cancellation mutex")
        .clone()
        .expect("transport received child cancellation token");
    assert!(token.is_cancelled());
}
