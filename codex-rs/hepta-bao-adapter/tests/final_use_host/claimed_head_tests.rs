use super::leases::next_feed;
use super::*;
use pretty_assertions::assert_eq;
use std::sync::mpsc;
use std::thread;

struct ClaimedHeadClock {
    phase: AtomicUsize,
    claimed: mpsc::Sender<()>,
    updater_sampled: mpsc::Sender<()>,
    sampled: Mutex<mpsc::Receiver<()>>,
}

struct FeedUpdate {
    host: Arc<BaoFinalUseHost>,
    signed: SignedFinalUseRevocationUpdate,
}

struct CallbackHeadClock {
    phase: AtomicUsize,
    updater: Mutex<Option<thread::ThreadId>>,
    begin_update: mpsc::Sender<()>,
    sampled: Mutex<mpsc::Receiver<()>>,
    update_sampled: mpsc::Sender<()>,
}

impl AuthorityClock for CallbackHeadClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let updater = *self.updater.lock().unwrap();
        if updater == Some(thread::current().id()) {
            // This public apply call owns the host lease before trying the
            // authority mutex. Let the older owner's delivery check return.
            self.phase.store(3, Ordering::SeqCst);
            self.update_sampled.send(()).unwrap();
        } else {
            match self.phase.load(Ordering::SeqCst) {
                1 => {
                    // The post-I/O gate still owns the lease and observes A.
                    self.phase.store(2, Ordering::SeqCst);
                    self.begin_update.send(()).unwrap();
                }
                2 => {
                    // Original deliver_final_use is now checking the token.
                    self.sampled
                        .lock()
                        .unwrap()
                        .recv_timeout(Duration::from_secs(5))
                        .unwrap();
                }
                _ => {}
            }
        }
        Ok(10_000)
    }
}

impl AuthorityClock for ClaimedHeadClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        // The independent claim CAS arms phase 1. The subsequent owner read
        // still holds its state lock, so the updater can acquire the host lease
        // but cannot change the head until this original claim returns token A.
        match self.phase.load(Ordering::SeqCst) {
            1 => {
                self.phase.store(2, Ordering::SeqCst);
                self.claimed.send(()).unwrap();
                self.sampled
                    .lock()
                    .unwrap()
                    .recv_timeout(Duration::from_secs(5))
                    .unwrap();
            }
            2 => {
                self.phase.store(3, Ordering::SeqCst);
                self.updater_sampled.send(()).unwrap();
            }
            _ => {}
        }
        Ok(10_000)
    }
}

#[tokio::test]
async fn a_successor_feed_between_claim_and_send_cannot_authorize_the_older_token() {
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
    let (claimed, observed_claim) = mpsc::channel();
    let (updater_sampled, sampled) = mpsc::channel();
    let clock = Arc::new(ClaimedHeadClock {
        phase: AtomicUsize::new(0),
        claimed,
        updater_sampled,
        sampled: Mutex::new(sampled),
    });
    let callbacks = Arc::new(AtomicUsize::new(0));
    let fixture = PqFixture::new(
        &client,
        clock.clone(),
        callbacks.clone(),
        /*feed_expires_at*/ 20_000,
    );
    fixture.host.apply_revocation_update(&fixture.feed).unwrap();
    let next = next_feed(
        &fixture.distributor,
        &fixture.feed,
        /*revision*/ 3,
        /*expires_at*/ 15_000,
    );
    let host = Arc::new(fixture.host);
    *fixture.frontier.before_return.lock().unwrap() = Some(Box::new(move || {
        clock.phase.store(1, Ordering::SeqCst);
    }));
    let updating_host = host.clone();
    let updating = thread::spawn(move || {
        observed_claim.recv_timeout(Duration::from_secs(5)).unwrap();
        updating_host.apply_revocation_update(&next)
    });
    let result = host
        .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
        .await;
    updating.join().unwrap().unwrap();
    assert_eq!(
        result,
        Err(BaoFinalUseHostError::Client(BaoClientError::Authority(
            FinalUseError::StaleRevocationHead
        )))
    );
    assert_eq!(fixture.authority.revocation_head().unwrap().revision, 3);
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 1);
    assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    task.abort();
    let _ = task.await;
}

#[tokio::test]
async fn a_fresh_successor_during_provider_io_does_not_release_an_older_claim() {
    let provider_calls = Arc::new(AtomicUsize::new(0));
    let calls = provider_calls.clone();
    let update = Arc::new(Mutex::new(None::<FeedUpdate>));
    let update_at_provider = update.clone();
    let body =
        serde_json::json!({"data":{"data":{"value":SECRET},"metadata":{"version":1}}}).to_string();
    let (endpoint, ca, task) = delayed_server(body, move || {
        calls.fetch_add(1, Ordering::SeqCst);
        let successor = update_at_provider.lock().unwrap().take().unwrap();
        successor
            .host
            .apply_revocation_update(&successor.signed)
            .unwrap();
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
    let next = next_feed(
        &fixture.distributor,
        &fixture.feed,
        /*revision*/ 3,
        /*expires_at*/ 15_000,
    );
    let host = Arc::new(fixture.host);
    *update.lock().unwrap() = Some(FeedUpdate {
        host: host.clone(),
        signed: next,
    });
    assert_eq!(
        host.consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
            .await,
        Err(BaoFinalUseHostError::Client(BaoClientError::Authority(
            FinalUseError::StaleRevocationHead
        )))
    );
    task.await.unwrap().unwrap();
    assert_eq!(fixture.authority.revocation_head().unwrap().revision, 3);
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 1);
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn successor_after_delivery_precheck_cannot_replace_claim_at_registered_callback() {
    let (begin_update, update_requested) = mpsc::channel();
    let (update_sampled, sampled) = mpsc::channel();
    let clock = Arc::new(CallbackHeadClock {
        phase: AtomicUsize::new(0),
        updater: Mutex::new(None),
        begin_update,
        sampled: Mutex::new(sampled),
        update_sampled,
    });
    let provider_calls = Arc::new(AtomicUsize::new(0));
    let calls = provider_calls.clone();
    let arm_after_io = clock.clone();
    let body =
        serde_json::json!({"data":{"data":{"value":SECRET},"metadata":{"version":1}}}).to_string();
    let (endpoint, ca, task) = delayed_server(body, move || {
        calls.fetch_add(1, Ordering::SeqCst);
        arm_after_io.phase.store(1, Ordering::SeqCst);
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
        clock.clone(),
        callbacks.clone(),
        /*feed_expires_at*/ 20_000,
    );
    fixture.host.apply_revocation_update(&fixture.feed).unwrap();
    let next = next_feed(
        &fixture.distributor,
        &fixture.feed,
        /*revision*/ 3,
        /*expires_at*/ 15_000,
    );
    let host = Arc::new(fixture.host);
    let updating_host = host.clone();
    let updating = thread::spawn(move || {
        update_requested
            .recv_timeout(Duration::from_secs(5))
            .unwrap();
        updating_host.apply_revocation_update(&next)
    });
    *clock.updater.lock().unwrap() = Some(updating.thread().id());
    let result = host
        .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
        .await;
    updating.join().unwrap().unwrap();
    task.await.unwrap().unwrap();
    assert_eq!(
        result,
        Err(BaoFinalUseHostError::Client(BaoClientError::Authority(
            FinalUseError::StaleRevocationHead
        )))
    );
    assert_eq!(fixture.authority.revocation_head().unwrap().revision, 3);
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 1);
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
}
