use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::task::Context;
use std::task::Poll;
use std::task::Wake;
use std::task::Waker;
use std::time::Duration;

use codex_hepta_types::Digest32;

use super::*;
use crate::FEDERATION_MAC_KEY_BYTES;
use crate::FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES;
use crate::FederationOutboundCredentialV1;
use crate::FederationProductProfileV1;
use crate::FederationRecoveryLimitsV1;
use crate::FederationTransportContextIssuerV1;
use crate::FederationWireClientV1;
use crate::InMemoryFederationRecoveryStoreV1;
use crate::MAX_FEDERATION_PRODUCT_PACKET_BYTES;
use crate::PeerCredentialRegistryV1;
use crate::PeerCredentialV1;

const NOW: u64 = 9_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable fixture identity")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

struct TestClock(Arc<AtomicUsize>);

impl FederationProductClockV1 for TestClock {
    fn now_unix_ms(&self) -> Result<u64, FederationProductErrorV1> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok(NOW + 1)
    }
}

struct GatedExchange {
    profile: StableId,
    calls: Arc<AtomicUsize>,
    ready: Arc<AtomicBool>,
    response: Mutex<Option<FederationProductExchangeResponseV1>>,
}

impl FederationProductExchangeV1 for GatedExchange {
    fn transport_profile_id(&self) -> &StableId {
        &self.profile
    }

    fn exchange_once<'a>(
        &'a self,
        _expected_peer_id: &'a StableId,
        _request_packet: Vec<u8>,
        _deadline_unix_ms: u64,
    ) -> FederationProductExchangeFutureV1<'a> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(std::future::poll_fn(move |_context| {
            if !self.ready.load(Ordering::SeqCst) {
                return Poll::Pending;
            }
            Poll::Ready(
                self.response
                    .lock()
                    .expect("fixture response")
                    .take()
                    .ok_or(FederationProductExchangeErrorV1::Unavailable),
            )
        }))
    }
}

type TestAdapter =
    FederationWireTransportV2<InMemoryFederationRecoveryStoreV1, GatedExchange, TestClock>;

fn adapter() -> TestAdapter {
    let mut credentials = PeerCredentialRegistryV1::new();
    credentials
        .enroll(
            PeerCredentialV1::new(
                id("peer-a"),
                id("peer-b"),
                id("key-a-b"),
                1,
                NOW - 100,
                NOW + 100_000,
                [91; FEDERATION_MAC_KEY_BYTES],
            )
            .expect("credential"),
        )
        .expect("enroll");
    let mut wire = FederationWireClientV1::open(
        id("peer-a"),
        credentials,
        32,
        8,
        FederationRecoveryLimitsV1 {
            replay_capacity: 32,
            replay_per_peer_capacity: 8,
            attempt_capacity: 32,
            attempt_per_peer_capacity: 8,
        },
        InMemoryFederationRecoveryStoreV1::default(),
        NOW,
    )
    .expect("wire client");
    wire.bind_outbound_credential(
        id("peer-b"),
        FederationOutboundCredentialV1::new(id("key-a-b"), 1).expect("selector"),
    )
    .expect("bind outbound");
    let issuer = FederationTransportContextIssuerV1::new(
        id("peer-a"),
        id("authenticated-channel-v1"),
        id("context-key"),
        1,
        [93; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES],
    )
    .expect("issuer");
    let profile = FederationProductProfileV1::new(
        id("memory-federation-product-v1"),
        id("authenticated-channel-v1"),
        MAX_FEDERATION_PRODUCT_PACKET_BYTES,
    )
    .expect("profile");
    let client = FederationProductClientV1::new(wire, profile, issuer.verifier()).expect("client");
    let response = FederationProductExchangeResponseV1 {
        // Bytes are intentionally invalid: contention must return before any
        // response parsing or replay/terminal mutation, not fabricate a reply.
        packet: Vec::new(),
        transport: issuer
            .issue_verified_channel(id("peer-b"), digest(b"channel"), NOW, NOW + 100_000)
            .expect("channel context"),
    };
    FederationWireTransportV2::with_clock(
        client,
        GatedExchange {
            profile: id("authenticated-channel-v1"),
            calls: Arc::new(AtomicUsize::new(0)),
            ready: Arc::new(AtomicBool::new(false)),
            response: Mutex::new(Some(response)),
        },
        TestClock(Arc::new(AtomicUsize::new(0))),
    )
}

fn query() -> FederatedQueryV2 {
    FederatedQueryV2 {
        query_id: id("contention-query"),
        peer_id: id("peer-b"),
        principal_id: id("consumer-a"),
        scope_digest: digest(b"scope"),
        purpose_digest: digest(b"purpose"),
        generation_vector_digest: digest(b"generation"),
        query_digest: digest(b"query"),
        maximum_results: 8,
        deadline_unix_ms: NOW + 20_000,
        lease_epoch: 1,
        nonce_digest: digest(b"nonce"),
    }
}

struct NoopWake;

impl Wake for NoopWake {
    fn wake(self: Arc<Self>) {}
}

fn poll_once<F: Future + ?Sized>(future: Pin<&mut F>) -> Poll<F::Output> {
    let waker = Waker::from(Arc::new(NoopWake));
    future.poll(&mut Context::from_waker(&waker))
}

#[test]
fn busy_before_preparation_returns_without_dispatch_or_clock_observation() {
    let adapter = Arc::new(adapter());
    let owner = adapter.client.lock().expect("hold owner");
    let (sender, receiver) = mpsc::channel();
    let worker_adapter = Arc::clone(&adapter);
    let worker = std::thread::spawn(move || {
        let query = query();
        let mut future = worker_adapter.send_once(&query);
        sender.send(poll_once(future.as_mut())).expect("send poll");
    });
    let observed = receiver.recv_timeout(Duration::from_secs(2));
    // Always release before joining so reverting try_lock yields a bounded
    // failing test rather than a deadlocked qualification runner.
    drop(owner);
    worker.join().expect("worker");
    assert!(matches!(
        observed.expect("attempt poll must not block"),
        Poll::Ready(Ok(FederationTransportResultV2::NonTerminal(
            FederationTransportOutcomeV2::Unavailable
        )))
    ));
    assert_eq!(adapter.transport.calls.load(Ordering::SeqCst), 0);
    assert_eq!(adapter.clock.0.load(Ordering::SeqCst), 0);
    adapter
        .client
        .lock()
        .expect("owner")
        .begin_query(&query(), NOW + 1)
        .expect("busy acquisition must not create an attempt");
}

#[test]
fn busy_after_exchange_keeps_pending_intent_and_does_not_blindly_replay() {
    let adapter = Arc::new(adapter());
    let (started_sender, started_receiver) = mpsc::channel();
    let (resume_sender, resume_receiver) = mpsc::channel();
    let (result_sender, result_receiver) = mpsc::channel();
    let worker_adapter = Arc::clone(&adapter);
    let worker = std::thread::spawn(move || {
        let query = query();
        let mut future = worker_adapter.send_once(&query);
        assert!(poll_once(future.as_mut()).is_pending());
        started_sender.send(()).expect("prepared");
        resume_receiver.recv().expect("resume");
        result_sender
            .send(poll_once(future.as_mut()))
            .expect("send completion poll");
    });
    started_receiver
        .recv_timeout(Duration::from_secs(2))
        .expect("prepared before exchange completion");
    let owner = adapter.client.lock().expect("hold terminal owner");
    adapter.transport.ready.store(true, Ordering::SeqCst);
    resume_sender.send(()).expect("resume completion");
    let observed = result_receiver.recv_timeout(Duration::from_secs(2));
    drop(owner);
    worker.join().expect("worker");
    assert!(matches!(
        observed.expect("completion poll must not block"),
        Poll::Ready(Ok(FederationTransportResultV2::NonTerminal(
            FederationTransportOutcomeV2::NoTerminalObservation
        )))
    ));
    assert_eq!(adapter.transport.calls.load(Ordering::SeqCst), 1);
    assert_eq!(adapter.clock.0.load(Ordering::SeqCst), 2);
    assert!(
        adapter
            .client
            .lock()
            .expect("owner")
            .begin_query(&query(), NOW + 2)
            .is_err()
    );
}

#[test]
fn poisoned_owner_is_rejected_not_reported_as_temporary_backpressure() {
    let adapter = Arc::new(adapter());
    let worker_adapter = Arc::clone(&adapter);
    assert!(
        std::thread::spawn(move || {
            let _owner = worker_adapter.client.lock().expect("owner");
            panic!("deliberate owner poisoning");
        })
        .join()
        .is_err()
    );
    let query = query();
    let mut future = adapter.send_once(&query);
    assert!(matches!(
        poll_once(future.as_mut()),
        Poll::Ready(Err(FederationV2Error::TransportRejected))
    ));
    assert_eq!(adapter.transport.calls.load(Ordering::SeqCst), 0);
}

#[test]
fn dropping_pending_exchange_preserves_the_durable_attempt() {
    let adapter = adapter();
    let query = query();
    let mut future = adapter.send_once(&query);
    assert!(poll_once(future.as_mut()).is_pending());
    drop(future);
    assert_eq!(adapter.transport.calls.load(Ordering::SeqCst), 1);
    assert!(
        adapter
            .into_inner()
            .expect("client")
            .begin_query(&query, NOW + 2)
            .is_err()
    );
}
