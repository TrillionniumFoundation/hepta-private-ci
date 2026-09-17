use std::future::Future;
use std::pin::Pin;

use tokio_util::sync::CancellationToken;

use super::authority::VerifiedCapabilityReceiptV2;
use super::model::{FederatedQueryV2, FederationV2Error};
use super::response::RemoteFederatedResponseV2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationTransportOutcomeV2 {
    Unavailable,
    TimedOut,
    Cancelled,
    NoTerminalObservation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationTransportResultV2 {
    Terminal(RemoteFederatedResponseV2),
    NonTerminal(FederationTransportOutcomeV2),
}

pub type FederationTransportFutureV2<'a> = Pin<
    Box<dyn Future<Output = Result<FederationTransportResultV2, FederationV2Error>> + Send + 'a>,
>;

/// One authenticated asynchronous I/O attempt. The host must bind the child
/// cancellation token to real I/O; dropping or cancelling the future must stop
/// outstanding work rather than permit an untracked blind retry.
pub trait FederationTransportV2: Send + Sync {
    fn send_once<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        capability: &'a VerifiedCapabilityReceiptV2,
        cancellation: CancellationToken,
    ) -> FederationTransportFutureV2<'a>;
}
