use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;

struct StepAfterReadClock {
    now: AtomicU64,
    next: AtomicU64,
}

impl AuthorityClock for StepAfterReadClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let next = self.next.swap(0, Ordering::SeqCst);
        Ok(if next == 0 {
            self.now.load(Ordering::SeqCst)
        } else {
            self.now.swap(next, Ordering::SeqCst)
        })
    }
}

async fn reject_after_clock_step(
    not_before_unix_ms: u64,
    expected_error: BaoFinalUseHostError,
    expected_claims: usize,
) {
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
    let clock = Arc::new(StepAfterReadClock {
        now: AtomicU64::new(10_000),
        next: AtomicU64::new(0),
    });
    let mut fixture = PqFixture::new(
        &client,
        clock.clone(),
        callbacks.clone(),
        /*feed_expires_at*/ 10_500,
    );
    fixture.grant.grant.not_before_unix_ms = not_before_unix_ms;
    fixture.grant.signature = fixture
        .issuer
        .sign_exact_message(&fixture.grant.grant.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    fixture.approval.approval =
        FinalUseApproval::for_grant("operator-approver".into(), &fixture.grant.grant).unwrap();
    fixture.approval.signature = fixture
        .approver
        .sign_exact_message(&fixture.approval.approval.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    fixture.host.apply_revocation_update(&fixture.feed).unwrap();
    // The first host check observes 10,000, then all later owner/host reads see
    // 10,500. Each signature is valid; only the joint time window can deny I/O.
    clock.next.store(10_500, Ordering::SeqCst);
    assert_eq!(
        fixture
            .host
            .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
            .await,
        Err(expected_error)
    );
    assert_eq!(
        fixture.authority.capacity().unwrap().used_nonces,
        expected_claims
    );
    assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    task.abort();
    let _ = task.await;
}

#[tokio::test]
async fn grant_and_feed_without_a_common_time_window_never_dispatch() {
    reject_after_clock_step(
        /*not_before_unix_ms*/ 10_500,
        BaoFinalUseHostError::Client(BaoClientError::Authority(FinalUseError::NotYetValid)),
        /*expected_claims*/ 0,
    )
    .await;
}

#[tokio::test]
async fn feed_expiring_during_claim_is_rechecked_before_any_provider_send() {
    reject_after_clock_step(
        /*not_before_unix_ms*/ 9_000,
        BaoFinalUseHostError::StaleRevocationFeed,
        /*expected_claims*/ 1,
    )
    .await;
}
