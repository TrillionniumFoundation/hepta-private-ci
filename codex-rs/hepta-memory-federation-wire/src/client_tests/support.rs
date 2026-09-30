use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::*;

pub(crate) const NOW: u64 = 4_000_000;

pub(crate) fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

pub(crate) fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

pub(crate) fn credential(
    sender: &str,
    receiver: &str,
    key: &str,
    generation: u64,
    byte: u8,
) -> PeerCredentialV1 {
    PeerCredentialV1::new(
        id(sender),
        id(receiver),
        id(key),
        generation,
        NOW - 100,
        NOW + 100_000,
        [byte; FEDERATION_MAC_KEY_BYTES],
    )
    .expect("credential")
}

pub(crate) fn bidirectional_credentials() -> PeerCredentialRegistryV1 {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 81))
        .expect("A->B credential");
    registry
        .enroll(credential("peer-b", "peer-a", "key-b-a", 1, 82))
        .expect("B->A credential");
    registry
}

pub(crate) fn limits() -> FederationRecoveryLimitsV1 {
    FederationRecoveryLimitsV1 {
        replay_capacity: 32,
        replay_per_peer_capacity: 8,
        attempt_capacity: 32,
        attempt_per_peer_capacity: 8,
    }
}

pub(crate) fn open_client<S>(store: S, now_unix_ms: u64) -> FederationWireClientV1<S>
where
    S: FederationRecoveryStoreV1,
{
    let mut client = FederationWireClientV1::open(
        id("peer-a"),
        bidirectional_credentials(),
        32,
        8,
        limits(),
        store,
        now_unix_ms,
    )
    .expect("open client");
    client
        .bind_outbound_credential(
            id("peer-b"),
            FederationOutboundCredentialV1::new(id("key-a-b"), 1).expect("selector"),
        )
        .expect("bind client credential");
    client
}

pub(crate) fn open_server<S>(store: S, now_unix_ms: u64) -> FederationWireHostV1<S>
where
    S: FederationRecoveryStoreV1,
{
    let mut host = FederationWireHostV1::open(
        id("peer-b"),
        bidirectional_credentials(),
        32,
        8,
        limits(),
        store,
        now_unix_ms,
    )
    .expect("open server");
    host.bind_outbound_credential(
        id("peer-a"),
        FederationOutboundCredentialV1::new(id("key-b-a"), 1).expect("selector"),
    )
    .expect("bind server credential");
    host
}

pub(crate) fn query() -> FederationQueryMessageV1 {
    FederationQueryMessageV1 {
        query_id: id("client-query-1"),
        query_binding_digest: digest(b"client-query-binding"),
        scope_digest: digest(b"client-scope"),
        purpose_digest: digest(b"client-purpose"),
        generation_vector_digest: digest(b"client-generation"),
        maximum_results: 8,
    }
}

pub(crate) fn result(frontier: u64, observed_unix_ms: u64) -> FederationHostQueryResultV1 {
    FederationHostQueryResultV1::new(
        digest(b"client-response"),
        digest(b"client-result"),
        AuthenticatedFrontierV1 {
            owner_peer_id: id("peer-b"),
            generation: 13,
            frontier,
            state_digest: digest(format!("cut-{frontier}").as_bytes()),
            parent_witness_digest: Digest32::ZERO,
            observed_unix_ms,
        },
    )
    .expect("host result")
}

pub(crate) fn encode_from_b(message: FederationWireMessageV1, issued_unix_ms: u64) -> Vec<u8> {
    let registry = bidirectional_credentials();
    let credential = registry
        .require_current(
            &id("peer-b"),
            &id("peer-a"),
            &id("key-b-a"),
            1,
            issued_unix_ms,
        )
        .expect("current B->A credential");
    let frame = AuthenticatedFederationFrameV1::seal(
        credential,
        issued_unix_ms,
        issued_unix_ms + 10_000,
        FederationNonceV1::generate().expect("nonce"),
        message,
    )
    .expect("seal B frame");
    let (schemas, codec) = registered_codec_v1().expect("codec");
    encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode")
}

pub(crate) fn response_for_query(
    query: &FederationQueryMessageV1,
    frontier_owner: &str,
    frontier_observed_unix_ms: u64,
) -> FederationWireMessageV1 {
    FederationWireMessageV1::Response(FederationResponseMessageV1 {
        query_id: query.query_id.clone(),
        query_binding_digest: query.query_binding_digest,
        response_digest: digest(b"manual-response"),
        result_digest: digest(b"manual-result"),
        frontier: AuthenticatedFrontierV1 {
            owner_peer_id: id(frontier_owner),
            generation: 1,
            frontier: 1,
            state_digest: digest(b"manual-cut"),
            parent_witness_digest: Digest32::ZERO,
            observed_unix_ms: frontier_observed_unix_ms,
        },
        terminal_observed: true,
    })
}

#[derive(Default)]
struct ControlledStoreInner {
    snapshot: Option<Vec<u8>>,
    fail_next_store: bool,
}

#[derive(Clone, Default)]
pub(crate) struct ControlledStore {
    inner: Arc<Mutex<ControlledStoreInner>>,
}

impl ControlledStore {
    pub(crate) fn fail_next_store(&self) {
        self.inner
            .lock()
            .expect("controlled store lock")
            .fail_next_store = true;
    }
}

impl FederationRecoveryStoreV1 for ControlledStore {
    fn load(&mut self) -> Result<Option<Vec<u8>>, FederationRecoveryError> {
        self.inner
            .lock()
            .map(|inner| inner.snapshot.clone())
            .map_err(|_| FederationRecoveryError::StoreUnavailable)
    }

    fn store(&mut self, snapshot: &[u8]) -> Result<(), FederationRecoveryError> {
        let mut inner = self
            .inner
            .lock()
            .map_err(|_| FederationRecoveryError::StoreUnavailable)?;
        if inner.fail_next_store {
            inner.fail_next_store = false;
            return Err(FederationRecoveryError::StoreUnavailable);
        }
        inner.snapshot = Some(snapshot.to_vec());
        Ok(())
    }
}
