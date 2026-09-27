mod admission;
mod error;
mod lifecycle;
mod persistence;
mod snapshot;

pub use error::FederationClientError;

use std::collections::BTreeMap;

use codex_hepta_types::StableId;

use self::snapshot::ClientAttemptIdentity;
use self::snapshot::ClientAttemptMetadata;
use crate::credential::PeerCredentialRegistryV1;
use crate::host::FederationOutboundCredentialV1;
use crate::protocol::AuthenticatedFrontierV1;
use crate::recovery::DurableFederationStateV1;
use crate::recovery::FederationRecoveryLimitsV1;
use crate::recovery::FederationRecoveryStoreV1;
use crate::replay::ReplayCacheV1;

struct SealedClientFrameV1 {
    payload: Vec<u8>,
    expires_unix_ms: u64,
}

/// Durable client-side half of the authenticated federation host boundary.
///
/// The server-side `FederationWireHostV1` owns inbound query/cancel admission.
/// This client owns outbound query/cancel intent and correlates authenticated
/// response/cancel-ack frames with the exact durable attempt before exposing
/// them to a product adapter. The supplied recovery store must atomically
/// replace its prior snapshot before returning `Ok(())` from `store`.
pub struct FederationWireClientV1<S>
where
    S: FederationRecoveryStoreV1,
{
    local_peer_id: StableId,
    limits: FederationRecoveryLimitsV1,
    credentials: PeerCredentialRegistryV1,
    outbound_credentials: BTreeMap<String, FederationOutboundCredentialV1>,
    replay: ReplayCacheV1,
    recovery: DurableFederationStateV1,
    attempts: BTreeMap<ClientAttemptIdentity, ClientAttemptMetadata>,
    frontiers: BTreeMap<String, AuthenticatedFrontierV1>,
    recovery_store: S,
}
