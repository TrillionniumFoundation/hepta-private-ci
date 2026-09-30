use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::FederationClientError;
use crate::host::MAX_FEDERATION_HOST_PEERS;
use crate::protocol::AuthenticatedFrontierV1;
use crate::recovery::DurableFederationStateV1;
use crate::recovery::FederationRecoveryLimitsV1;

const CLIENT_SNAPSHOT_SCHEMA: &str = "hepta.memory-federation.client-recovery.v1";
const CLIENT_SNAPSHOT_DOMAIN: &[u8] = b"hepta.memory-federation.client-recovery.v1";

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub(crate) struct ClientAttemptIdentity {
    peer_id: String,
    query_id: String,
    query_binding_digest: [u8; 32],
}

impl ClientAttemptIdentity {
    pub(crate) fn new(
        peer_id: &StableId,
        query_id: &StableId,
        query_binding_digest: Digest32,
    ) -> Self {
        Self {
            peer_id: peer_id.as_str().to_string(),
            query_id: query_id.as_str().to_string(),
            query_binding_digest: *query_binding_digest.as_array(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ClientAttemptMetadata {
    pub(crate) expires_unix_ms: u64,
    pub(crate) cancellation_id: Option<StableId>,
}

pub(crate) fn retain_live_attempts(
    recovery: &DurableFederationStateV1,
    attempts: &mut BTreeMap<ClientAttemptIdentity, ClientAttemptMetadata>,
) {
    let now_unix_ms = recovery.last_observed_unix_ms();
    attempts.retain(|identity, metadata| {
        if metadata.expires_unix_ms <= now_unix_ms {
            return false;
        }
        let Some(cancellation_id) = &metadata.cancellation_id else {
            return true;
        };
        let Ok(peer_id) = StableId::new(identity.peer_id.clone()) else {
            return false;
        };
        let Ok(query_id) = StableId::new(identity.query_id.clone()) else {
            return false;
        };
        !cancellation_id.as_str().is_empty()
            && recovery.is_cancelled(
                &peer_id,
                &query_id,
                Digest32::from_array(identity.query_binding_digest),
            )
    });
}

pub(crate) fn encode_client_snapshot(
    local_peer_id: &StableId,
    limits: FederationRecoveryLimitsV1,
    recovery: Vec<u8>,
    attempts: &BTreeMap<ClientAttemptIdentity, ClientAttemptMetadata>,
    frontiers: &BTreeMap<String, AuthenticatedFrontierV1>,
) -> Result<Vec<u8>, FederationClientError> {
    let payload = ClientSnapshotPayload {
        schema: CLIENT_SNAPSHOT_SCHEMA.to_string(),
        local_peer_id: local_peer_id.as_str().to_string(),
        limits: StoredClientLimits::from(limits),
        recovery,
        attempts: attempts
            .iter()
            .map(|(identity, metadata)| StoredClientAttempt {
                peer_id: identity.peer_id.clone(),
                query_id: identity.query_id.clone(),
                query_binding_digest: identity.query_binding_digest,
                expires_unix_ms: metadata.expires_unix_ms,
                cancellation_id: metadata
                    .cancellation_id
                    .as_ref()
                    .map(|value| value.as_str().to_string()),
            })
            .collect(),
        frontiers: frontiers
            .iter()
            .map(|(peer_id, frontier)| StoredClientFrontier {
                peer_id: peer_id.clone(),
                owner_peer_id: frontier.owner_peer_id.as_str().to_string(),
                generation: frontier.generation,
                frontier: frontier.frontier,
                state_digest: *frontier.state_digest.as_array(),
                parent_witness_digest: *frontier.parent_witness_digest.as_array(),
                observed_unix_ms: frontier.observed_unix_ms,
            })
            .collect(),
    };
    let payload_bytes =
        serde_json::to_vec(&payload).map_err(|_| FederationClientError::SnapshotEncode)?;
    let envelope = ClientSnapshotEnvelope {
        digest: client_snapshot_digest(&payload_bytes),
        payload,
    };
    serde_json::to_vec(&envelope).map_err(|_| FederationClientError::SnapshotEncode)
}

fn client_snapshot_digest(payload: &[u8]) -> [u8; 32] {
    let mut bytes = Vec::with_capacity(CLIENT_SNAPSHOT_DOMAIN.len() + payload.len());
    bytes.extend_from_slice(CLIENT_SNAPSHOT_DOMAIN);
    bytes.extend_from_slice(payload);
    *Digest32::of_bytes(&bytes).as_array()
}

type RestoredClientSnapshot = (
    DurableFederationStateV1,
    BTreeMap<ClientAttemptIdentity, ClientAttemptMetadata>,
    BTreeMap<String, AuthenticatedFrontierV1>,
);

pub(crate) fn restore_client_snapshot(
    local_peer_id: &StableId,
    limits: FederationRecoveryLimitsV1,
    now_unix_ms: u64,
    bytes: &[u8],
) -> Result<RestoredClientSnapshot, FederationClientError> {
    let envelope: ClientSnapshotEnvelope =
        serde_json::from_slice(bytes).map_err(|_| FederationClientError::SnapshotDecode)?;
    if serde_json::to_vec(&envelope).map_err(|_| FederationClientError::SnapshotEncode)? != bytes {
        return Err(FederationClientError::SnapshotNotCanonical);
    }
    let payload_bytes =
        serde_json::to_vec(&envelope.payload).map_err(|_| FederationClientError::SnapshotEncode)?;
    let expected = client_snapshot_digest(&payload_bytes);
    if expected != envelope.digest {
        return Err(FederationClientError::SnapshotDigestMismatch);
    }
    let payload = envelope.payload;
    if payload.schema != CLIENT_SNAPSHOT_SCHEMA
        || payload.local_peer_id != local_peer_id.as_str()
        || payload.limits != StoredClientLimits::from(limits)
    {
        return Err(FederationClientError::SnapshotIdentityMismatch);
    }
    let recovery = DurableFederationStateV1::restore(
        local_peer_id.clone(),
        limits,
        now_unix_ms,
        &payload.recovery,
    )?;
    let mut attempts = BTreeMap::new();
    let mut prior_attempt = None;
    for stored in payload.attempts {
        let peer_id = StableId::new(stored.peer_id.clone())
            .map_err(|_| FederationClientError::SnapshotStateInvalid)?;
        let query_id = StableId::new(stored.query_id.clone())
            .map_err(|_| FederationClientError::SnapshotStateInvalid)?;
        let cancellation_id = stored
            .cancellation_id
            .map(StableId::new)
            .transpose()
            .map_err(|_| FederationClientError::SnapshotStateInvalid)?;
        let binding = Digest32::from_array(stored.query_binding_digest);
        if binding.is_zero() || stored.expires_unix_ms == 0 {
            return Err(FederationClientError::SnapshotStateInvalid);
        }
        let identity = ClientAttemptIdentity::new(&peer_id, &query_id, binding);
        if prior_attempt
            .as_ref()
            .is_some_and(|value| value >= &identity)
        {
            return Err(FederationClientError::SnapshotNotCanonical);
        }
        prior_attempt = Some(identity.clone());
        if stored.expires_unix_ms <= now_unix_ms {
            continue;
        }
        if cancellation_id.is_some() && !recovery.is_cancelled(&peer_id, &query_id, binding) {
            return Err(FederationClientError::SnapshotStateInvalid);
        }
        if attempts
            .insert(
                identity,
                ClientAttemptMetadata {
                    expires_unix_ms: stored.expires_unix_ms,
                    cancellation_id,
                },
            )
            .is_some()
        {
            return Err(FederationClientError::SnapshotStateInvalid);
        }
    }

    if payload.frontiers.len() > MAX_FEDERATION_HOST_PEERS {
        return Err(FederationClientError::SnapshotStateInvalid);
    }
    let mut frontiers = BTreeMap::new();
    let mut prior_peer = None;
    for stored in payload.frontiers {
        let peer_id = StableId::new(stored.peer_id.clone())
            .map_err(|_| FederationClientError::SnapshotStateInvalid)?;
        let owner_peer_id = StableId::new(stored.owner_peer_id)
            .map_err(|_| FederationClientError::SnapshotStateInvalid)?;
        if owner_peer_id != peer_id {
            return Err(FederationClientError::SnapshotStateInvalid);
        }
        if prior_peer
            .as_ref()
            .is_some_and(|value: &String| value >= &stored.peer_id)
        {
            return Err(FederationClientError::SnapshotNotCanonical);
        }
        prior_peer = Some(stored.peer_id.clone());
        let frontier = AuthenticatedFrontierV1 {
            owner_peer_id,
            generation: stored.generation,
            frontier: stored.frontier,
            state_digest: Digest32::from_array(stored.state_digest),
            parent_witness_digest: Digest32::from_array(stored.parent_witness_digest),
            observed_unix_ms: stored.observed_unix_ms,
        };
        frontier
            .validate()
            .map_err(FederationClientError::Protocol)?;
        if frontiers.insert(stored.peer_id, frontier).is_some() {
            return Err(FederationClientError::SnapshotStateInvalid);
        }
    }
    Ok((recovery, attempts, frontiers))
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ClientSnapshotEnvelope {
    digest: [u8; 32],
    payload: ClientSnapshotPayload,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ClientSnapshotPayload {
    schema: String,
    local_peer_id: String,
    limits: StoredClientLimits,
    recovery: Vec<u8>,
    attempts: Vec<StoredClientAttempt>,
    frontiers: Vec<StoredClientFrontier>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredClientLimits {
    replay_capacity: usize,
    replay_per_peer_capacity: usize,
    attempt_capacity: usize,
    attempt_per_peer_capacity: usize,
}

impl From<FederationRecoveryLimitsV1> for StoredClientLimits {
    fn from(value: FederationRecoveryLimitsV1) -> Self {
        Self {
            replay_capacity: value.replay_capacity,
            replay_per_peer_capacity: value.replay_per_peer_capacity,
            attempt_capacity: value.attempt_capacity,
            attempt_per_peer_capacity: value.attempt_per_peer_capacity,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredClientAttempt {
    peer_id: String,
    query_id: String,
    query_binding_digest: [u8; 32],
    expires_unix_ms: u64,
    cancellation_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredClientFrontier {
    peer_id: String,
    owner_peer_id: String,
    generation: u64,
    frontier: u64,
    state_digest: [u8; 32],
    parent_witness_digest: [u8; 32],
    observed_unix_ms: u64,
}
