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
    let adapter = FederationWireTransportV2::with_clock(
        client(),
        exchange,
        SequenceClock::new(NOW + 1),
    );
    let query = query();
    let result = block_on(adapter.send_once(&query)).expect("transport result");
    let FederationTransportResultV2::Terminal(observed) = result else {
        panic!("terminal response");
    };
    assert_eq!(observed, response(&query));
}
