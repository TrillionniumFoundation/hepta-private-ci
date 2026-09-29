use std::future::Future;
use std::pin::Pin;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_memory_federation::FederatedQueryV2;
use codex_hepta_memory_federation::FederationTransportFuture;
use codex_hepta_memory_federation::FederationTransportOutcomeV2;
use codex_hepta_memory_federation::FederationTransportResultV2;
use codex_hepta_memory_federation::FederationTransportV2;
use codex_hepta_memory_federation::FederationV2Error;
use codex_hepta_types::StableId;

use crate::FederationRecoveryStoreV1;

use super::bridge::FederationProductClientV1;
use super::context::FederationAuthenticatedTransportV1;
use super::error::FederationProductErrorV1;

pub struct FederationProductExchangeResponseV1 {
    pub packet: Vec<u8>,
    pub transport: FederationAuthenticatedTransportV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationProductExchangeErrorV1 {
    Unavailable,
    TimedOut,
    NoTerminalObservation,
    Rejected,
}

pub type FederationProductExchangeFutureV1<'a> = Pin<
    Box<
        dyn Future<
                Output = Result<
                    FederationProductExchangeResponseV1,
                    FederationProductExchangeErrorV1,
                >,
            > + Send
            + 'a,
    >,
>;

/// Selected transport owner. Dropping the returned future must stop subsequent
/// network I/O. The response context must describe the channel that delivered
/// the packet.
pub trait FederationProductExchangeV1: Send + Sync {
    fn transport_profile_id(&self) -> &StableId;

    fn exchange_once<'a>(
        &'a self,
        expected_peer_id: &'a StableId,
        request_packet: Vec<u8>,
        deadline_unix_ms: u64,
    ) -> FederationProductExchangeFutureV1<'a>;
}

/// Owner-supplied clock, re-observed at each local admission boundary.
/// Transport timestamps never replace these observations.
pub trait FederationProductClockV1: Send + Sync {
    fn now_unix_ms(&self) -> Result<u64, FederationProductErrorV1>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemFederationProductClockV1;

impl FederationProductClockV1 for SystemFederationProductClockV1 {
    fn now_unix_ms(&self) -> Result<u64, FederationProductErrorV1> {
        let elapsed = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| FederationProductErrorV1::ClockUnavailable)?;
        u64::try_from(elapsed.as_millis()).map_err(|_| FederationProductErrorV1::ClockUnavailable)
    }
}

/// Canonical V2 transport backed by the authenticated packet bridge. This is
/// not a second scheduler, authority owner, or retry loop.
pub struct FederationWireTransportV2<S, T, C = SystemFederationProductClockV1>
where
    S: FederationRecoveryStoreV1,
{
    client: Mutex<FederationProductClientV1<S>>,
    transport: T,
    clock: C,
}

impl<S, T> FederationWireTransportV2<S, T, SystemFederationProductClockV1>
where
    S: FederationRecoveryStoreV1,
{
    pub fn new(client: FederationProductClientV1<S>, transport: T) -> Self {
        Self::with_clock(client, transport, SystemFederationProductClockV1)
    }
}

impl<S, T, C> FederationWireTransportV2<S, T, C>
where
    S: FederationRecoveryStoreV1,
{
    pub fn with_clock(client: FederationProductClientV1<S>, transport: T, clock: C) -> Self {
        Self {
            client: Mutex::new(client),
            transport,
            clock,
        }
    }

    pub fn into_inner(self) -> Result<FederationProductClientV1<S>, FederationProductErrorV1> {
        self.client
            .into_inner()
            .map_err(|_| FederationProductErrorV1::ClientStatePoisoned)
    }
}

impl<S, T, C> FederationWireTransportV2<S, T, C>
where
    S: FederationRecoveryStoreV1,
    C: FederationProductClockV1,
{
    /// Reclaim one bounded expiry batch through the existing durable owner.
    /// The owner schedules this explicitly; it never sends or retries a query.
    pub fn maintain_expired(&self) -> Result<usize, FederationProductErrorV1> {
        let mut client = self
            .client
            .lock()
            .map_err(|_| FederationProductErrorV1::ClientStatePoisoned)?;
        client.maintain_expired(self.clock.now_unix_ms()?)
    }
}

impl<S, T, C> FederationTransportV2 for FederationWireTransportV2<S, T, C>
where
    S: FederationRecoveryStoreV1 + Send,
    T: FederationProductExchangeV1,
    C: FederationProductClockV1,
{
    fn send_once<'a>(&'a self, query: &'a FederatedQueryV2) -> FederationTransportFuture<'a> {
        Box::pin(async move {
            let (started_unix_ms, request_packet) = {
                let mut client = self
                    .client
                    .lock()
                    .map_err(|_| FederationV2Error::TransportRejected)?;
                if self.transport.transport_profile_id() != client.profile().transport_profile_id()
                {
                    return Err(FederationV2Error::TransportRejected);
                }
                // Sample after acquiring the owner, not before waiting for it.
                let started_unix_ms = self
                    .clock
                    .now_unix_ms()
                    .map_err(|_| FederationV2Error::TransportRejected)?;
                if started_unix_ms >= query.deadline_unix_ms {
                    return Ok(FederationTransportResultV2::NonTerminal(
                        FederationTransportOutcomeV2::TimedOut,
                    ));
                }
                let packet = client
                    .begin_query(query, started_unix_ms)
                    .map_err(|_| FederationV2Error::TransportRejected)?;
                (started_unix_ms, packet)
            };
            // Durable preparation can consume the remaining horizon. Never
            // enter the selected network exchange using its earlier timestamp.
            let dispatch_unix_ms = self
                .clock
                .now_unix_ms()
                .map_err(|_| FederationV2Error::TransportRejected)?;
            if dispatch_unix_ms < started_unix_ms {
                return Err(FederationV2Error::TransportRejected);
            }
            if dispatch_unix_ms >= query.deadline_unix_ms {
                return Ok(FederationTransportResultV2::NonTerminal(
                    FederationTransportOutcomeV2::TimedOut,
                ));
            }
            let exchange = self
                .transport
                .exchange_once(&query.peer_id, request_packet, query.deadline_unix_ms)
                .await;
            let exchange = match exchange {
                Ok(exchange) => exchange,
                Err(FederationProductExchangeErrorV1::TimedOut) => {
                    return Ok(FederationTransportResultV2::NonTerminal(
                        FederationTransportOutcomeV2::TimedOut,
                    ));
                }
                Err(FederationProductExchangeErrorV1::Unavailable) => {
                    return Ok(FederationTransportResultV2::NonTerminal(
                        FederationTransportOutcomeV2::Unavailable,
                    ));
                }
                Err(FederationProductExchangeErrorV1::NoTerminalObservation) => {
                    return Ok(FederationTransportResultV2::NonTerminal(
                        FederationTransportOutcomeV2::NoTerminalObservation,
                    ));
                }
                Err(FederationProductExchangeErrorV1::Rejected) => {
                    return Err(FederationV2Error::TransportRejected);
                }
            };
            let (received_unix_ms, response) = {
                let mut client = self
                    .client
                    .lock()
                    .map_err(|_| FederationV2Error::TransportRejected)?;
                // A contended owner lock must not reuse an observation made
                // before waiting. Admission receives a fresh local timestamp.
                let received_unix_ms = self
                    .clock
                    .now_unix_ms()
                    .map_err(|_| FederationV2Error::TransportRejected)?;
                if received_unix_ms < dispatch_unix_ms {
                    return Err(FederationV2Error::TransportRejected);
                }
                if received_unix_ms >= query.deadline_unix_ms {
                    return Ok(FederationTransportResultV2::NonTerminal(
                        FederationTransportOutcomeV2::TimedOut,
                    ));
                }
                let response = client
                    .admit_response_for_query(
                        query,
                        &exchange.transport,
                        &exchange.packet,
                        received_unix_ms,
                    )
                    .map_err(|_| FederationV2Error::TransportRejected)?;
                (received_unix_ms, response)
            };
            // Terminal persistence may also cross a deadline. Keep the durable
            // terminal fence, but never expose stale evidence or replay it.
            let completed_unix_ms = self
                .clock
                .now_unix_ms()
                .map_err(|_| FederationV2Error::TransportRejected)?;
            if completed_unix_ms < received_unix_ms {
                return Err(FederationV2Error::TransportRejected);
            }
            if completed_unix_ms >= query.deadline_unix_ms
                || completed_unix_ms >= response.expires_unix_ms
            {
                return Ok(FederationTransportResultV2::NonTerminal(
                    FederationTransportOutcomeV2::TimedOut,
                ));
            }
            Ok(FederationTransportResultV2::Terminal(response))
        })
    }
}
