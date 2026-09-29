use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Poll;
use std::task::Wake;
use std::task::Waker;

use codex_hepta_memory_federation::FederationTransportResultV2;
use codex_hepta_memory_federation::FederationTransportV2;

use super::*;

struct SequenceClock {
    next: AtomicU64,
}

impl SequenceClock {
    fn new(first: u64) -> Self {
        Self {
            next: AtomicU64::new(first),
        }
    }
}

impl FederationProductClockV1 for SequenceClock {
    fn now_unix_ms(&self) -> Result<u64, FederationProductErrorV1> {
        Ok(self.next.fetch_add(4, Ordering::SeqCst))
    }
}

struct LoopbackExchange {
    profile_id: StableId,
    server: Mutex<FederationProductHostV1<InMemoryFederationRecoveryStoreV1>>,
}

impl FederationProductExchangeV1 for LoopbackExchange {
    fn transport_profile_id(&self) -> &StableId {
        &self.profile_id
    }

    fn exchange_once<'a>(
        &'a self,
        expected_peer_id: &'a StableId,
        request_packet: Vec<u8>,
        _deadline_unix_ms: u64,
    ) -> FederationProductExchangeFutureV1<'a> {
        let result = (|| {
            if expected_peer_id.as_str() != "peer-b" {
                return Err(FederationProductExchangeErrorV1::Rejected);
            }
            let mut server = self
                .server
                .lock()
                .map_err(|_| FederationProductExchangeErrorV1::Unavailable)?;
            let FederationProductHostAdmissionV1::Query(admitted) = server
                .admit(
                    &transport("peer-b", "peer-a", b"loopback-server-channel"),
                    &request_packet,
                    NOW + 2,
                )
                .map_err(|_| FederationProductExchangeErrorV1::Rejected)?
            else {
                return Err(FederationProductExchangeErrorV1::Rejected);
            };
            let product_response = response(admitted.query());
            let packet = server
                .complete_query(admitted, product_response, frontier(), NOW + 4)
                .map_err(|_| FederationProductExchangeErrorV1::Rejected)?;
            Ok(FederationProductExchangeResponseV1 {
                packet,
                transport: transport("peer-a", "peer-b", b"loopback-client-channel"),
            })
        })();
        Box::pin(std::future::ready(result))
    }
}

struct NoopWake;

impl Wake for NoopWake {
    fn wake(self: Arc<Self>) {}
}

fn block_on<F: Future>(future: F) -> F::Output {
    let waker = Waker::from(Arc::new(NoopWake));
    let mut context = Context::from_waker(&waker);
    let mut future = Box::pin(future);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(output) => return output,
            Poll::Pending => std::thread::yield_now(),
        }
    }
}

#[test]
fn canonical_transport_adapter_uses_existing_v2_trait_without_parallel_engine() {
    let exchange = LoopbackExchange {
        profile_id: id("authenticated-channel-v1"),
        server: Mutex::new(server()),
    };
    let adapter =
        FederationWireTransportV2::with_clock(client(), exchange, SequenceClock::new(NOW + 1));
    let query = query();
    let result = block_on(adapter.send_once(&query)).expect("transport result");
    let FederationTransportResultV2::Terminal(observed) = result else {
        panic!("terminal response");
    };
    assert_eq!(observed, response(&query));
}

struct ScriptedClock {
    observations: Vec<u64>,
    next: std::sync::atomic::AtomicUsize,
}

impl ScriptedClock {
    fn new(observations: Vec<u64>) -> Self {
        Self {
            observations,
            next: std::sync::atomic::AtomicUsize::new(0),
        }
    }
}

impl FederationProductClockV1 for ScriptedClock {
    fn now_unix_ms(&self) -> Result<u64, FederationProductErrorV1> {
        self.observations
            .get(self.next.fetch_add(1, Ordering::SeqCst))
            .copied()
            .ok_or(FederationProductErrorV1::ClockUnavailable)
    }
}

struct UnavailableExchange {
    profile_id: StableId,
    calls: Arc<AtomicU64>,
}

impl FederationProductExchangeV1 for UnavailableExchange {
    fn transport_profile_id(&self) -> &StableId {
        &self.profile_id
    }

    fn exchange_once<'a>(
        &'a self,
        _expected_peer_id: &'a StableId,
        _request_packet: Vec<u8>,
        _deadline_unix_ms: u64,
    ) -> FederationProductExchangeFutureV1<'a> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(std::future::ready(Err(
            FederationProductExchangeErrorV1::Unavailable,
        )))
    }
}

#[test]
fn preparation_crossing_deadline_never_enters_exchange() {
    let query = query();
    let calls = Arc::new(AtomicU64::new(0));
    let exchange = UnavailableExchange {
        profile_id: id("authenticated-channel-v1"),
        calls: Arc::clone(&calls),
    };
    let adapter = FederationWireTransportV2::with_clock(
        client(),
        exchange,
        ScriptedClock::new(vec![NOW + 1, query.deadline_unix_ms]),
    );
    assert_eq!(
        block_on(adapter.send_once(&query)).expect("timeout observation"),
        FederationTransportResultV2::NonTerminal(
            codex_hepta_memory_federation::FederationTransportOutcomeV2::TimedOut,
        )
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    // Preparation was durable. Failure to dispatch must not silently delete
    // the original attempt and allow the same identity to be sent again.
    assert!(
        adapter
            .into_inner()
            .expect("client")
            .begin_query(&query, NOW + 2)
            .is_err()
    );
}

#[test]
fn preparation_clock_regression_never_enters_exchange() {
    let calls = Arc::new(AtomicU64::new(0));
    let exchange = UnavailableExchange {
        profile_id: id("authenticated-channel-v1"),
        calls: Arc::clone(&calls),
    };
    let adapter = FederationWireTransportV2::with_clock(
        client(),
        exchange,
        ScriptedClock::new(vec![NOW + 2, NOW + 1]),
    );
    assert!(matches!(
        block_on(adapter.send_once(&query())),
        Err(codex_hepta_memory_federation::FederationV2Error::TransportRejected)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[test]
fn response_clock_must_not_regress_below_dispatch_observation() {
    let exchange = LoopbackExchange {
        profile_id: id("authenticated-channel-v1"),
        server: Mutex::new(server()),
    };
    let adapter = FederationWireTransportV2::with_clock(
        client(),
        exchange,
        ScriptedClock::new(vec![NOW + 1, NOW + 8, NOW + 6]),
    );
    assert!(matches!(
        block_on(adapter.send_once(&query())),
        Err(codex_hepta_memory_federation::FederationV2Error::TransportRejected)
    ));
}

#[test]
fn terminal_persistence_crossing_deadline_does_not_expose_evidence() {
    let query = query();
    let exchange = LoopbackExchange {
        profile_id: id("authenticated-channel-v1"),
        server: Mutex::new(server()),
    };
    let adapter = FederationWireTransportV2::with_clock(
        client(),
        exchange,
        ScriptedClock::new(vec![NOW + 1, NOW + 2, NOW + 5, query.deadline_unix_ms]),
    );
    assert_eq!(
        block_on(adapter.send_once(&query)).expect("timeout observation"),
        FederationTransportResultV2::NonTerminal(
            codex_hepta_memory_federation::FederationTransportOutcomeV2::TimedOut,
        )
    );
    assert!(
        adapter
            .into_inner()
            .expect("client")
            .begin_query(&query, NOW + 6)
            .is_err()
    );
}

#[test]
fn terminal_persistence_crossing_response_expiry_does_not_expose_evidence() {
    let query = query();
    let exchange = LoopbackExchange {
        profile_id: id("authenticated-channel-v1"),
        server: Mutex::new(server()),
    };
    let adapter = FederationWireTransportV2::with_clock(
        client(),
        exchange,
        ScriptedClock::new(vec![NOW + 1, NOW + 2, NOW + 5, response(&query).expires_unix_ms]),
    );
    assert_eq!(
        block_on(adapter.send_once(&query)).expect("timeout observation"),
        FederationTransportResultV2::NonTerminal(
            codex_hepta_memory_federation::FederationTransportOutcomeV2::TimedOut,
        )
    );
}

struct FixedResponseExchange {
    profile_id: StableId,
    packet: Vec<u8>,
}

impl FederationProductExchangeV1 for FixedResponseExchange {
    fn transport_profile_id(&self) -> &StableId {
        &self.profile_id
    }

    fn exchange_once<'a>(
        &'a self,
        _expected_peer_id: &'a StableId,
        _request_packet: Vec<u8>,
        _deadline_unix_ms: u64,
    ) -> FederationProductExchangeFutureV1<'a> {
        Box::pin(std::future::ready(Ok(
            FederationProductExchangeResponseV1 {
                packet: self.packet.clone(),
                transport: transport("peer-a", "peer-b", b"client-channel"),
            },
        )))
    }
}

#[test]
fn wrong_attempt_response_is_rejected_before_its_terminal_state_is_consumed() {
    let mut client = client();
    let mut server = server();
    let (packet, expected) = complete_round_trip(&mut client, &mut server);
    let mut other_query = query();
    other_query.query_id = id("product-query-2");
    other_query.nonce_digest = digest(b"product-nonce-2");
    let exchange = FixedResponseExchange {
        profile_id: id("authenticated-channel-v1"),
        packet: packet.clone(),
    };
    let adapter =
        FederationWireTransportV2::with_clock(client, exchange, SequenceClock::new(NOW + 5));
    assert!(matches!(
        block_on(adapter.send_once(&other_query)),
        Err(codex_hepta_memory_federation::FederationV2Error::TransportRejected)
    ));
    let observed = adapter
        .into_inner()
        .expect("client")
        .admit_response_for_query(
            &query(),
            &transport("peer-a", "peer-b", b"client-channel"),
            &packet,
            NOW + 20,
        )
        .expect("original response still admissible for the correct attempt");
    assert_eq!(observed, expected);
}

#[test]
fn expired_response_body_is_rejected_while_its_frame_is_still_current() {
    let mut client = client();
    let mut server = server();
    let (packet, expected) = complete_round_trip(&mut client, &mut server);
    assert!(matches!(
        client.admit_response_for_query(
            &query(),
            &transport("peer-a", "peer-b", b"client-channel"),
            &packet,
            expected.expires_unix_ms,
        ),
        Err(FederationProductErrorV1::V2(
            codex_hepta_memory_federation::FederationV2Error::ResponseExpired,
        ))
    ));
}

#[test]
fn wrapped_client_can_reclaim_expired_attempts_without_any_exchange() {
    let mut client = client();
    let query = query();
    client.begin_query(&query, NOW + 1).expect("pending query");
    let calls = Arc::new(AtomicU64::new(0));
    let exchange = UnavailableExchange {
        profile_id: id("authenticated-channel-v1"),
        calls: Arc::clone(&calls),
    };
    let adapter = FederationWireTransportV2::with_clock(
        client,
        exchange,
        ScriptedClock::new(vec![query.deadline_unix_ms]),
    );
    assert_eq!(adapter.maintain_expired().expect("owner maintenance"), 1);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}
