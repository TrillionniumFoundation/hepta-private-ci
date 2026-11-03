use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn pq_cold_restart_confirms_fresh_current_feed_without_rewriting_nonce_frontier() {
    let provider_calls = Arc::new(AtomicUsize::new(0));
    let calls = provider_calls.clone();
    let body =
        serde_json::json!({"data":{"data":{"value":SECRET},"metadata":{"version":1}}}).to_string();
    let (endpoint, ca, task) = delayed_server(body, move || {
        calls.fetch_add(1, Ordering::SeqCst);
    })
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let callbacks = Arc::new(AtomicUsize::new(0));
    let PqFixture {
        host,
        authority,
        request,
        mut grant,
        mut approval,
        mut feed,
        issuer,
        approver,
        distributor,
        clock,
        frontier,
        _state: state,
    } = PqFixture::new(
        &client,
        Arc::new(ManualClock::new(/*now_unix_ms*/ 10_000)),
        callbacks.clone(),
        /*feed_expires_at*/ 10_500,
    );
    host.apply_revocation_update(&feed).unwrap();
    // An admitted dispatch stays spent even if its process stops before I/O.
    drop(authority.claim(&grant, &grant.grant.binding).unwrap());
    let head = authority.revocation_head().unwrap();
    let expected_frontier = authority.frontier().unwrap();
    let expected_writes = frontier.writes.load(Ordering::SeqCst);
    assert_eq!(authority.capacity().unwrap().used_nonces, 1);
    drop(host);
    drop(authority);
    clock.set(/*now_unix_ms*/ 11_000);

    let (_, issuer_pin) = pq_key(/*seed*/ 71, "issuer-key");
    let (_, approver_pin) = pq_key(/*seed*/ 72, "operator-key");
    let (_, distributor_pin) = pq_key(/*seed*/ 73, "feed-key");
    let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        state.path(),
        "security-owner".into(),
        vec![issuer_pin],
        head,
        clock.clone(),
        frontier.clone(),
    )
    .unwrap();
    let host = BaoFinalUseHost::new(
        authority.clone(),
        FinalUseApprovalVerifier::new_pq_with_keys("operator-approver".into(), vec![approver_pin])
            .unwrap(),
        FinalUseRevocationFeedVerifier::new_pq_with_keys(
            "revocation-distributor".into(),
            vec![distributor_pin],
        )
        .unwrap(),
        clock,
        [registered_consumer(callbacks.clone())],
    )
    .unwrap();
    assert_eq!(
        host.consume_kv_v2(&client, &grant, &approval, &request)
            .await,
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
    assert_eq!(
        host.apply_revocation_update(&feed),
        Err(BaoFinalUseHostError::Control(
            FinalUseControlError::RevocationFeedStale
        ))
    );
    // The independent distributor signs a new validity window for the exact
    // already durable head. No synthetic revision or new nonce namespace.
    feed.update.issued_at_unix_ms = 10_900;
    feed.update.expires_at_unix_ms = 20_000;
    feed.signature = distributor
        .sign_exact_message(&feed.update.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    let mut forged = feed.clone();
    forged.signature[0] ^= 1;
    assert_eq!(
        host.apply_revocation_update(&forged),
        Err(BaoFinalUseHostError::Control(
            FinalUseControlError::InvalidSignature
        ))
    );
    let mut rollback = feed.clone();
    rollback.update.head.revision = 1;
    rollback.signature = distributor
        .sign_exact_message(&rollback.update.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    assert_eq!(
        host.apply_revocation_update(&rollback),
        Err(BaoFinalUseHostError::Control(
            FinalUseControlError::Authority(FinalUseError::StaleRevocationHead)
        ))
    );
    assert_eq!(
        host.consume_kv_v2(&client, &grant, &approval, &request)
            .await,
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
    assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    let receipt = host.apply_revocation_update(&feed).unwrap();
    assert_eq!(receipt.revision(), 2);
    assert_eq!(receipt.valid_until_unix_ms(), 20_000);
    assert_eq!(host.apply_revocation_update(&feed).unwrap(), receipt);
    assert_eq!(frontier.writes.load(Ordering::SeqCst), expected_writes);
    assert_eq!(authority.frontier().unwrap(), expected_frontier);
    assert_eq!(authority.capacity().unwrap().used_nonces, 1);
    assert_eq!(
        host.consume_kv_v2(&client, &grant, &approval, &request)
            .await,
        Err(BaoFinalUseHostError::Client(BaoClientError::Authority(
            FinalUseError::AlreadyClaimed
        )))
    );
    assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);

    grant.grant.grant_id = "pq-host-read-after-restart".into();
    grant.grant.nonce = [32; 32];
    grant.signature = issuer
        .sign_exact_message(&grant.grant.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    approval.approval =
        FinalUseApproval::for_grant("operator-approver".into(), &grant.grant).unwrap();
    approval.signature = approver
        .sign_exact_message(&approval.approval.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    host.consume_kv_v2(&client, &grant, &approval, &request)
        .await
        .unwrap();
    task.await.unwrap().unwrap();
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 1);
    assert_eq!(authority.capacity().unwrap().used_nonces, 2);
    assert_eq!(frontier.writes.load(Ordering::SeqCst), expected_writes + 1);
}
