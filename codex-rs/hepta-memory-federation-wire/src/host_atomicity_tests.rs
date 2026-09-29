use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;

const NOW: u64 = 6_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn credential(
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

fn credentials() -> PeerCredentialRegistryV1 {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 91))
        .expect("A->B credential");
    registry
        .enroll(credential("peer-b", "peer-a", "key-b-a", 1, 92))
        .expect("B->A credential");
    registry
}

fn limits() -> FederationRecoveryLimitsV1 {
    FederationRecoveryLimitsV1 {
        replay_capacity: 32,
        replay_per_peer_capacity: 8,
        attempt_capacity: 32,
        attempt_per_peer_capacity: 8,
    }
}

fn query() -> FederationQueryMessageV1 {
    FederationQueryMessageV1 {
        query_id: id("atomic-query"),
        query_binding_digest: digest(b"atomic-query-binding"),
        scope_digest: digest(b"atomic-scope"),
        purpose_digest: digest(b"atomic-purpose"),
        generation_vector_digest: digest(b"atomic-generation"),
        maximum_results: 4,
    }
}

fn encode_from_a(message: FederationWireMessageV1, nonce_byte: u8) -> Vec<u8> {
    let registry = credentials();
    let credential = registry
        .require_current(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 1, NOW)
        .expect("current A->B credential");
    let frame = AuthenticatedFederationFrameV1::seal(
        credential,
        NOW,
        NOW + 20_000,
        FederationNonceV1::from_bytes([nonce_byte; FEDERATION_NONCE_BYTES]),
        message,
    )
    .expect("seal frame");
    let (schemas, codec) = registered_codec_v1().expect("codec");
    encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode")
}

fn result(frontier: u64, observed_unix_ms: u64) -> FederationHostQueryResultV1 {
    FederationHostQueryResultV1::new(
        digest(b"atomic-response"),
        digest(b"atomic-result"),
        AuthenticatedFrontierV1 {
            owner_peer_id: id("peer-b"),
            generation: 1,
            frontier,
            state_digest: digest(format!("atomic-cut-{frontier}").as_bytes()),
            parent_witness_digest: Digest32::ZERO,
            observed_unix_ms,
        },
    )
    .expect("result")
}

#[derive(Default)]
struct StoreState {
    snapshot: Option<Vec<u8>>,
    fail_next_store: bool,
}

#[derive(Clone, Default)]
struct ControlledStore {
    state: Arc<Mutex<StoreState>>,
}

impl ControlledStore {
    fn fail_next_store(&self) {
        self.state.lock().expect("store lock").fail_next_store = true;
    }
}

impl FederationRecoveryStoreV1 for ControlledStore {
    fn load(&mut self) -> Result<Option<Vec<u8>>, FederationRecoveryError> {
        self.state
            .lock()
            .map(|state| state.snapshot.clone())
            .map_err(|_| FederationRecoveryError::StoreUnavailable)
    }

    fn store(&mut self, snapshot: &[u8]) -> Result<(), FederationRecoveryError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| FederationRecoveryError::StoreUnavailable)?;
        if state.fail_next_store {
            state.fail_next_store = false;
            return Err(FederationRecoveryError::StoreUnavailable);
        }
        state.snapshot = Some(snapshot.to_vec());
        Ok(())
    }
}

fn open_host(store: ControlledStore) -> FederationWireHostV1<ControlledStore> {
    let mut host =
        FederationWireHostV1::open(id("peer-b"), credentials(), 32, 8, limits(), store, NOW)
            .expect("open host");
    host.bind_outbound_credential(
        id("peer-a"),
        FederationOutboundCredentialV1::new(id("key-b-a"), 1).expect("selector"),
    )
    .expect("bind outbound credential");
    host
}

#[test]
fn query_store_failure_leaves_recovery_and_replay_retryable() {
    let store = ControlledStore::default();
    let control = store.clone();
    let mut host = open_host(store);
    let payload = encode_from_a(FederationWireMessageV1::Query(query()), 101);
    let before = host.recovery_snapshot().expect("before snapshot");

    control.fail_next_store();
    assert!(matches!(
        host.admit(&id("peer-a"), &payload, NOW + 1),
        Err(FederationHostError::Recovery(
            FederationRecoveryError::StoreUnavailable
        ))
    ));
    assert_eq!(
        host.recovery_snapshot().expect("unchanged snapshot"),
        before
    );
    assert!(matches!(
        host.admit(&id("peer-a"), &payload, NOW + 2)
            .expect("same frame remains retryable"),
        FederationHostAdmissionV1::Query(_)
    ));
}

#[test]
fn cancel_store_failure_does_not_install_a_cancellation_fence() {
    let store = ControlledStore::default();
    let control = store.clone();
    let mut host = open_host(store);
    let query = query();
    let query_payload = encode_from_a(FederationWireMessageV1::Query(query.clone()), 102);
    let FederationHostAdmissionV1::Query(_) = host
        .admit(&id("peer-a"), &query_payload, NOW + 1)
        .expect("query admission")
    else {
        panic!("query admission")
    };
    let cancel = FederationCancelMessageV1 {
        query_id: query.query_id,
        query_binding_digest: query.query_binding_digest,
        cancellation_id: id("atomic-cancel"),
        reason: FederationCancellationReasonV1::CallerCancelled,
    };
    let cancel_payload = encode_from_a(FederationWireMessageV1::Cancel(cancel), 103);
    let before = host.recovery_snapshot().expect("before cancellation");

    control.fail_next_store();
    assert!(matches!(
        host.admit(&id("peer-a"), &cancel_payload, NOW + 2),
        Err(FederationHostError::Recovery(
            FederationRecoveryError::StoreUnavailable
        ))
    ));
    assert_eq!(
        host.recovery_snapshot().expect("unchanged snapshot"),
        before
    );
    assert!(matches!(
        host.admit(&id("peer-a"), &cancel_payload, NOW + 3)
            .expect("same cancellation remains retryable"),
        FederationHostAdmissionV1::Reply(_)
    ));
}

#[test]
fn terminal_store_failure_leaves_pending_attempt_retryable() {
    let store = ControlledStore::default();
    let control = store.clone();
    let mut host = open_host(store);
    let payload = encode_from_a(FederationWireMessageV1::Query(query()), 104);
    let FederationHostAdmissionV1::Query(admitted) = host
        .admit(&id("peer-a"), &payload, NOW + 1)
        .expect("query admission")
    else {
        panic!("query admission")
    };
    let before = host.recovery_snapshot().expect("pending snapshot");
    let terminal = result(501, NOW + 2);

    control.fail_next_store();
    assert!(matches!(
        host.complete_query(admitted.clone(), terminal.clone(), NOW + 2),
        Err(FederationHostError::Recovery(
            FederationRecoveryError::StoreUnavailable
        ))
    ));
    assert_eq!(
        host.recovery_snapshot().expect("unchanged snapshot"),
        before
    );
    assert!(
        !host
            .complete_query(admitted, terminal, NOW + 3)
            .expect("terminal retry")
            .is_empty()
    );
}

#[test]
fn invalid_mac_precedes_recovery_staging_and_preserves_original_packet() {
    let mut host = open_host(ControlledStore::default());
    let advanced = FederationQueryMessageV1 {
        query_id: id("advance-clock"),
        query_binding_digest: digest(b"advance-clock"),
        ..query()
    };
    host.admit(
        &id("peer-a"),
        &encode_from_a(FederationWireMessageV1::Query(advanced), 110),
        NOW + 20,
    )
    .expect("advance durable clock");
    let original = encode_from_a(FederationWireMessageV1::Query(query()), 111);
    let (schemas, codec) = registered_codec_v1().expect("codec");
    let mut frame = decode_registered_frame_v1(&schemas, &codec, &original).expect("decode");
    frame.mac[0] ^= 1;
    let forged = encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode");
    let before = host.recovery_snapshot().expect("before");
    assert!(matches!(
        host.admit(&id("peer-a"), &forged, NOW + 1),
        Err(FederationHostError::Protocol(
            FederationProtocolError::MacMismatch
        ))
    ));
    assert_eq!(host.recovery_snapshot().expect("unchanged"), before);
    assert!(matches!(
        host.admit(&id("peer-a"), &original, NOW + 21)
            .expect("original packet"),
        FederationHostAdmissionV1::Query(_)
    ));
}
