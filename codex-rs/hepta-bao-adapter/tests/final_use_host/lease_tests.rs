//! Exercise real host entry points while the independent CAS service stalls.
use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::mpsc;
use std::thread;

struct CallSignalClock {
    now: AtomicU64,
    next_read: Mutex<Option<mpsc::Sender<()>>>,
}

impl AuthorityClock for CallSignalClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if let Some(signal) = self.next_read.lock().unwrap().take() {
            let _ = signal.send(());
        }
        Ok(self.now.load(Ordering::SeqCst))
    }
}

pub(super) fn next_feed(
    key: &PqNativeSigningKey,
    previous: &SignedFinalUseRevocationUpdate,
    revision: u64,
    expires_at: u64,
) -> SignedFinalUseRevocationUpdate {
    let mut next = previous.clone();
    next.update.head.revision = revision;
    next.update.expires_at_unix_ms = expires_at;
    next.signature = key
        .sign_exact_message(&next.update.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    next
}

#[tokio::test]
async fn concurrent_feed_api_serializes_owner_commit_with_lease_publication() {
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
    let clock = Arc::new(CallSignalClock {
        now: AtomicU64::new(10_000),
        next_read: Mutex::new(None),
    });
    let PqFixture {
        host,
        authority,
        request,
        grant,
        approval,
        feed,
        distributor,
        frontier,
        _state,
        ..
    } = PqFixture::new(
        &client,
        clock.clone(),
        callbacks.clone(),
        /*feed_expires_at*/ 20_000,
    );
    let later = next_feed(
        &distributor,
        &feed,
        /*revision*/ 3,
        /*expires_at*/ 15_000,
    );
    let host = Arc::new(host);
    let (at_cas, reached_cas) = mpsc::channel();
    let (resume, resumed) = mpsc::channel();
    *frontier.before_return.lock().unwrap() = Some(Box::new(move || {
        at_cas.send(()).unwrap();
        resumed.recv_timeout(Duration::from_secs(5)).unwrap();
    }));
    let first_host = host.clone();
    let first = thread::spawn(move || first_host.apply_revocation_update(&feed));
    reached_cas.recv_timeout(Duration::from_secs(5)).unwrap();

    // A second public API call must not even sample admission time while the
    // first owner's CAS/lease publication transaction is still outstanding.
    let (clock_read, observed_read) = mpsc::channel();
    *clock.next_read.lock().unwrap() = Some(clock_read);
    let (started, observed_start) = mpsc::channel();
    let second_host = host.clone();
    let second = thread::spawn(move || {
        started.send(()).unwrap();
        second_host.apply_revocation_update(&later)
    });
    observed_start.recv_timeout(Duration::from_secs(5)).unwrap();
    let premature_read = observed_read.recv_timeout(Duration::from_millis(200));
    // Always release/join before asserting so a regression cannot strand the
    // independently blocked service thread behind a failed test assertion.
    resume.send(()).unwrap();
    first.join().unwrap().unwrap();
    second.join().unwrap().unwrap();
    assert!(matches!(
        premature_read,
        Err(mpsc::RecvTimeoutError::Timeout)
    ));
    assert_eq!(authority.revocation_head().unwrap().revision, 3);

    clock.now.store(16_000, Ordering::SeqCst);
    assert_eq!(
        host.consume_kv_v2(&client, &grant, &approval, &request)
            .await,
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
    assert_eq!(authority.capacity().unwrap().used_nonces, 0);
    assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    task.abort();
    let _ = task.await;
}

#[tokio::test]
async fn current_owner_head_requires_its_own_lease_and_nonce_changes_do_not_expire_it() {
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
    let fixture = PqFixture::new(
        &client,
        Arc::new(ManualClock::new(/*now_unix_ms*/ 10_000)),
        callbacks.clone(),
        /*feed_expires_at*/ 20_000,
    );
    fixture.host.apply_revocation_update(&fixture.feed).unwrap();
    let current = next_feed(
        &fixture.distributor,
        &fixture.feed,
        /*revision*/ 3,
        /*expires_at*/ 15_000,
    );
    // Another trusted owner entry point advances the same durable authority.
    // Its new head must not inherit the old host lease merely by sharing an epoch.
    fixture
        .authority
        .update_revocations(current.update.head.clone())
        .unwrap();
    assert_eq!(
        fixture
            .host
            .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
            .await,
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
    assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    fixture.host.apply_revocation_update(&current).unwrap();
    let shorter_same_head = next_feed(
        &fixture.distributor,
        &current,
        /*revision*/ 3,
        /*expires_at*/ 12_000,
    );
    fixture
        .host
        .apply_revocation_update(&shorter_same_head)
        .unwrap();
    fixture.clock.set(/*now_unix_ms*/ 14_000);
    fixture
        .host
        .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
        .await
        .unwrap();
    task.await.unwrap().unwrap();
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 1);

    // A different head always replaces the lease, even when its signed window
    // is shorter. The same-head maximum must not extend a successor head.
    let next = next_feed(
        &fixture.distributor,
        &current,
        /*revision*/ 4,
        /*expires_at*/ 14_500,
    );
    fixture.host.apply_revocation_update(&next).unwrap();
    fixture.clock.set(/*now_unix_ms*/ 14_900);
    assert_eq!(
        fixture
            .host
            .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
            .await,
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 1);
}
