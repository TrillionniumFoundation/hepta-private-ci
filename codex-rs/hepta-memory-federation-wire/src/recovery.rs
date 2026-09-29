use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::protocol::FEDERATION_NONCE_BYTES;
use crate::protocol::FederationCancelAckMessageV1;
use crate::protocol::FederationCancelMessageV1;
use crate::protocol::FederationCancellationDispositionV1;
use crate::protocol::FederationCancellationReasonV1;
use crate::replay::FederationReplayKeyV1;

pub const MAX_FEDERATION_RECOVERY_BYTES: usize = 32 * 1024 * 1024;
/// One cleanup batch spans replay and attempts together, not the live tables.
pub const FEDERATION_RECOVERY_CLEANUP_BATCH: usize = 64;

#[path = "recovery_index.rs"]
mod index;

const SNAPSHOT_SCHEMA: &str = "hepta.memory-federation.host-recovery.v1";
const SNAPSHOT_DIGEST_DOMAIN: &[u8] = b"hepta.memory-federation.host-recovery.v1";
const REPLAY_DOMAIN: &[u8] = b"hepta.memory-federation.durable-replay.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FederationRecoveryLimitsV1 {
    pub replay_capacity: usize,
    pub replay_per_peer_capacity: usize,
    pub attempt_capacity: usize,
    pub attempt_per_peer_capacity: usize,
}

impl FederationRecoveryLimitsV1 {
    pub fn validate(self) -> Result<Self, FederationRecoveryError> {
        if self.replay_capacity > crate::replay::MAX_FEDERATION_REPLAY_ENTRIES
            || self.attempt_capacity > crate::attempt::MAX_FEDERATION_ATTEMPTS
            || self.replay_capacity == 0
            || self.attempt_capacity == 0
            || self.replay_per_peer_capacity == 0
            || self.attempt_per_peer_capacity == 0
            || self.replay_per_peer_capacity > self.replay_capacity
            || self.attempt_per_peer_capacity > self.attempt_capacity
        {
            return Err(FederationRecoveryError::InvalidLimits);
        }
        Ok(self)
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct AttemptIdentity {
    peer_id: String,
    query_id: String,
    query_binding_digest: [u8; 32],
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum AttemptState {
    Pending,
    Cancelled {
        cancellation_id: String,
        reason: FederationCancellationReasonV1,
        observed_unix_ms: u64,
    },
    Terminal {
        terminal_digest: [u8; 32],
        observed_unix_ms: u64,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct AttemptEntry {
    began_unix_ms: u64,
    expires_unix_ms: u64,
    state: AttemptState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ReplayEntry {
    peer_id: String,
    expires_unix_ms: u64,
}

#[derive(Clone)]
pub struct DurableFederationStateV1 {
    local_peer_id: StableId,
    limits: FederationRecoveryLimitsV1,
    last_observed_unix_ms: u64,
    replay: BTreeMap<[u8; 32], ReplayEntry>,
    attempts: BTreeMap<AttemptIdentity, AttemptEntry>,
    // Derived indexes are never serialized or accepted from a caller. Recovery
    // rebuilds them from validated canonical primary records.
    replay_expiries: BTreeSet<(u64, [u8; 32])>,
    attempt_expiries: BTreeSet<(u64, AttemptIdentity)>,
    replay_counts: BTreeMap<String, usize>,
    attempt_counts: BTreeMap<String, usize>,
}

impl DurableFederationStateV1 {
    pub fn empty(
        local_peer_id: StableId,
        limits: FederationRecoveryLimitsV1,
        now_unix_ms: u64,
    ) -> Result<Self, FederationRecoveryError> {
        limits.validate()?;
        if now_unix_ms == 0 {
            return Err(FederationRecoveryError::ZeroObservationTime);
        }
        Ok(Self {
            local_peer_id,
            limits,
            last_observed_unix_ms: now_unix_ms,
            replay: BTreeMap::new(),
            attempts: BTreeMap::new(),
            replay_expiries: BTreeSet::new(),
            attempt_expiries: BTreeSet::new(),
            replay_counts: BTreeMap::new(),
            attempt_counts: BTreeMap::new(),
        })
    }

    pub fn restore(
        local_peer_id: StableId,
        limits: FederationRecoveryLimitsV1,
        now_unix_ms: u64,
        bytes: &[u8],
    ) -> Result<Self, FederationRecoveryError> {
        limits.validate()?;
        if bytes.len() > MAX_FEDERATION_RECOVERY_BYTES {
            return Err(FederationRecoveryError::SnapshotCapacityExceeded);
        }
        let envelope: RecoveryEnvelope =
            serde_json::from_slice(bytes).map_err(|_| FederationRecoveryError::SnapshotDecode)?;
        let canonical =
            serde_json::to_vec(&envelope).map_err(|_| FederationRecoveryError::SnapshotEncode)?;
        if canonical != bytes {
            return Err(FederationRecoveryError::SnapshotNotCanonical);
        }
        let payload_bytes = serde_json::to_vec(&envelope.payload)
            .map_err(|_| FederationRecoveryError::SnapshotEncode)?;
        let expected_digest = snapshot_digest(&payload_bytes);
        if expected_digest != envelope.digest {
            return Err(FederationRecoveryError::SnapshotDigestMismatch);
        }
        let payload = envelope.payload;
        if payload.schema != SNAPSHOT_SCHEMA
            || payload.local_peer_id != local_peer_id.as_str()
            || payload.limits != StoredLimits::from(limits)
        {
            return Err(FederationRecoveryError::SnapshotIdentityMismatch);
        }
        if payload.last_observed_unix_ms == 0 {
            return Err(FederationRecoveryError::SnapshotStateInvalid);
        }
        if payload.replay.len() > limits.replay_capacity
            || payload.attempts.len() > limits.attempt_capacity
        {
            return Err(FederationRecoveryError::SnapshotCapacityExceeded);
        }
        if now_unix_ms < payload.last_observed_unix_ms {
            return Err(FederationRecoveryError::ClockRegression);
        }

        let mut state = Self::empty(local_peer_id, limits, now_unix_ms)?;
        let mut prior_replay_key = None;
        for record in payload.replay {
            if prior_replay_key
                .as_ref()
                .is_some_and(|key| key >= &record.key)
            {
                return Err(FederationRecoveryError::SnapshotNotCanonical);
            }
            prior_replay_key = Some(record.key);
            validate_peer(&record.peer_id)?;
            if record.expires_unix_ms == 0 || record.key == [0; 32] {
                return Err(FederationRecoveryError::SnapshotStateInvalid);
            }
            if record.expires_unix_ms > now_unix_ms
                && state
                    .replay
                    .insert(
                        record.key,
                        ReplayEntry {
                            peer_id: record.peer_id,
                            expires_unix_ms: record.expires_unix_ms,
                        },
                    )
                    .is_some()
            {
                return Err(FederationRecoveryError::SnapshotDuplicate);
            }
        }

        let mut prior_attempt = None;
        for record in payload.attempts {
            let identity = AttemptIdentity {
                peer_id: record.peer_id.clone(),
                query_id: record.query_id.clone(),
                query_binding_digest: record.query_binding_digest,
            };
            if prior_attempt
                .as_ref()
                .is_some_and(|value| value >= &identity)
            {
                return Err(FederationRecoveryError::SnapshotNotCanonical);
            }
            prior_attempt = Some(identity.clone());
            validate_peer(&record.peer_id)?;
            StableId::new(record.query_id.clone())
                .map_err(|_| FederationRecoveryError::SnapshotIdentityMismatch)?;
            require_digest(Digest32::from_array(record.query_binding_digest))?;
            if record.began_unix_ms == 0
                || record.began_unix_ms > payload.last_observed_unix_ms
                || record.expires_unix_ms <= record.began_unix_ms
            {
                return Err(FederationRecoveryError::SnapshotStateInvalid);
            }
            let restored_state: AttemptState = record.state.try_into()?;
            let observation = match &restored_state {
                AttemptState::Pending => record.began_unix_ms,
                AttemptState::Cancelled {
                    observed_unix_ms, ..
                }
                | AttemptState::Terminal {
                    observed_unix_ms, ..
                } => *observed_unix_ms,
            };
            if observation < record.began_unix_ms
                || observation >= record.expires_unix_ms
                || observation > payload.last_observed_unix_ms
            {
                return Err(FederationRecoveryError::SnapshotStateInvalid);
            }
            // Expiry is garbage collection, not permission to hide malformed
            // identities, impossible timestamps or invalid cancellation state.
            if record.expires_unix_ms <= now_unix_ms {
                continue;
            }
            let entry = AttemptEntry {
                began_unix_ms: record.began_unix_ms,
                expires_unix_ms: record.expires_unix_ms,
                state: restored_state,
            };
            if state.attempts.insert(identity, entry).is_some() {
                return Err(FederationRecoveryError::SnapshotDuplicate);
            }
        }
        state.rebuild_indexes();
        state.require_capacity_isolation()?;
        Ok(state)
    }

    pub fn snapshot_bytes(&self) -> Result<Vec<u8>, FederationRecoveryError> {
        let payload = RecoveryPayload {
            schema: SNAPSHOT_SCHEMA.to_string(),
            local_peer_id: self.local_peer_id.as_str().to_string(),
            limits: StoredLimits::from(self.limits),
            last_observed_unix_ms: self.last_observed_unix_ms,
            replay: self
                .replay
                .iter()
                .map(|(key, entry)| StoredReplayRecord {
                    key: *key,
                    peer_id: entry.peer_id.clone(),
                    expires_unix_ms: entry.expires_unix_ms,
                })
                .collect(),
            attempts: self
                .attempts
                .iter()
                .map(|(identity, entry)| StoredAttemptRecord {
                    peer_id: identity.peer_id.clone(),
                    query_id: identity.query_id.clone(),
                    query_binding_digest: identity.query_binding_digest,
                    began_unix_ms: entry.began_unix_ms,
                    expires_unix_ms: entry.expires_unix_ms,
                    state: StoredAttemptState::from(&entry.state),
                })
                .collect(),
        };
        let payload_bytes =
            serde_json::to_vec(&payload).map_err(|_| FederationRecoveryError::SnapshotEncode)?;
        let envelope = RecoveryEnvelope {
            digest: snapshot_digest(&payload_bytes),
            payload,
        };
        serde_json::to_vec(&envelope).map_err(|_| FederationRecoveryError::SnapshotEncode)
    }

    pub fn preflight_frame(
        &mut self,
        identity: FederationReplayKeyV1<'_>,
        expires_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<[u8; 32], FederationRecoveryError> {
        let FederationReplayKeyV1 {
            sender_peer_id,
            receiver_peer_id,
            key_id,
            generation,
            nonce,
        } = identity;
        self.observe_time(now_unix_ms)?;
        self.purge_expired(now_unix_ms);
        if receiver_peer_id != &self.local_peer_id || generation == 0 {
            return Err(FederationRecoveryError::FrameIdentityMismatch);
        }
        if expires_unix_ms <= now_unix_ms {
            return Err(FederationRecoveryError::Expired);
        }
        let key = replay_key(sender_peer_id, receiver_peer_id, key_id, generation, nonce);
        if self.replay.contains_key(&key) {
            return Err(FederationRecoveryError::Replay);
        }
        if self.replay.len() >= self.limits.replay_capacity {
            return Err(FederationRecoveryError::ReplayCapacityExhausted);
        }
        let peer_count = self
            .replay_counts
            .get(sender_peer_id.as_str())
            .copied()
            .unwrap_or_default();
        if peer_count >= self.limits.replay_per_peer_capacity {
            return Err(FederationRecoveryError::ReplayPeerCapacityExhausted);
        }
        Ok(key)
    }

    pub fn record_verified_frame(
        &mut self,
        key: [u8; 32],
        sender_peer_id: &StableId,
        expires_unix_ms: u64,
    ) -> Result<(), FederationRecoveryError> {
        if self.replay.contains_key(&key) {
            return Err(FederationRecoveryError::Replay);
        }
        if key == [0; 32] {
            return Err(FederationRecoveryError::FrameIdentityMismatch);
        }
        if expires_unix_ms <= self.last_observed_unix_ms {
            return Err(FederationRecoveryError::Expired);
        }
        if self.replay.len() >= self.limits.replay_capacity {
            return Err(FederationRecoveryError::ReplayCapacityExhausted);
        }
        let peer = sender_peer_id.as_str().to_string();
        if self.replay_counts.get(&peer).copied().unwrap_or_default()
            >= self.limits.replay_per_peer_capacity
        {
            return Err(FederationRecoveryError::ReplayPeerCapacityExhausted);
        }
        self.replay.insert(
            key,
            ReplayEntry {
                peer_id: peer.clone(),
                expires_unix_ms,
            },
        );
        self.replay_expiries.insert((expires_unix_ms, key));
        *self.replay_counts.entry(peer).or_default() += 1;
        Ok(())
    }

    pub fn begin_attempt(
        &mut self,
        peer_id: &StableId,
        query_id: &StableId,
        query_binding_digest: Digest32,
        expires_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<(), FederationRecoveryError> {
        self.observe_time(now_unix_ms)?;
        self.purge_expired(now_unix_ms);
        require_digest(query_binding_digest)?;
        if expires_unix_ms <= now_unix_ms {
            return Err(FederationRecoveryError::Expired);
        }
        let identity = attempt_identity(peer_id, query_id, query_binding_digest);
        if self.attempts.contains_key(&identity) {
            return Err(FederationRecoveryError::DuplicateAttempt);
        }
        if self.attempts.len() >= self.limits.attempt_capacity {
            return Err(FederationRecoveryError::AttemptCapacityExhausted);
        }
        let peer_count = self
            .attempt_counts
            .get(peer_id.as_str())
            .copied()
            .unwrap_or_default();
        if peer_count >= self.limits.attempt_per_peer_capacity {
            return Err(FederationRecoveryError::AttemptPeerCapacityExhausted);
        }
        self.attempts.insert(
            identity.clone(),
            AttemptEntry {
                began_unix_ms: now_unix_ms,
                expires_unix_ms,
                state: AttemptState::Pending,
            },
        );
        self.attempt_expiries.insert((expires_unix_ms, identity));
        *self
            .attempt_counts
            .entry(peer_id.as_str().to_string())
            .or_default() += 1;
        Ok(())
    }

    pub fn observe_terminal(
        &mut self,
        peer_id: &StableId,
        query_id: &StableId,
        query_binding_digest: Digest32,
        terminal_digest: Digest32,
        observed_unix_ms: u64,
    ) -> Result<(), FederationRecoveryError> {
        self.observe_time(observed_unix_ms)?;
        require_digest(query_binding_digest)?;
        require_digest(terminal_digest)?;
        let identity = attempt_identity(peer_id, query_id, query_binding_digest);
        let entry = self
            .attempts
            .get_mut(&identity)
            .ok_or(FederationRecoveryError::UnknownAttempt)?;
        if observed_unix_ms < entry.began_unix_ms {
            return Err(FederationRecoveryError::ClockRegression);
        }
        if observed_unix_ms >= entry.expires_unix_ms {
            return Err(FederationRecoveryError::Expired);
        }
        match &entry.state {
            AttemptState::Pending => {
                entry.state = AttemptState::Terminal {
                    terminal_digest: *terminal_digest.as_array(),
                    observed_unix_ms,
                };
                Ok(())
            }
            AttemptState::Cancelled { .. } => Err(FederationRecoveryError::Cancelled),
            AttemptState::Terminal {
                terminal_digest: current,
                observed_unix_ms: current_observed,
            } if current == terminal_digest.as_array() && observed_unix_ms >= *current_observed => {
                Ok(())
            }
            AttemptState::Terminal { .. } => Err(FederationRecoveryError::ConflictingTerminal),
        }
    }

    pub fn observe_cancel(
        &mut self,
        peer_id: &StableId,
        request: &FederationCancelMessageV1,
        observed_unix_ms: u64,
    ) -> Result<FederationCancelAckMessageV1, FederationRecoveryError> {
        self.observe_time(observed_unix_ms)?;
        require_digest(request.query_binding_digest)?;
        let identity = attempt_identity(peer_id, &request.query_id, request.query_binding_digest);
        if self
            .attempts
            .get(&identity)
            .is_some_and(|entry| observed_unix_ms >= entry.expires_unix_ms)
        {
            self.remove_attempt(&identity);
        }
        let (disposition, acknowledged_unix_ms) = match self.attempts.get_mut(&identity) {
            None => (
                FederationCancellationDispositionV1::UnknownAttempt,
                observed_unix_ms,
            ),
            Some(entry) => {
                if observed_unix_ms < entry.began_unix_ms {
                    return Err(FederationRecoveryError::ClockRegression);
                }
                match &entry.state {
                    AttemptState::Pending => {
                        entry.state = AttemptState::Cancelled {
                            cancellation_id: request.cancellation_id.as_str().to_string(),
                            reason: request.reason,
                            observed_unix_ms,
                        };
                        (
                            FederationCancellationDispositionV1::ObservedBeforeTerminal,
                            observed_unix_ms,
                        )
                    }
                    AttemptState::Cancelled {
                        cancellation_id,
                        reason,
                        observed_unix_ms: first_observed,
                    } if cancellation_id == request.cancellation_id.as_str()
                        && reason == &request.reason
                        && observed_unix_ms >= *first_observed =>
                    {
                        (
                            FederationCancellationDispositionV1::ObservedBeforeTerminal,
                            *first_observed,
                        )
                    }
                    AttemptState::Cancelled { .. } => {
                        return Err(FederationRecoveryError::ConflictingCancellation);
                    }
                    AttemptState::Terminal {
                        observed_unix_ms: terminal_observed,
                        ..
                    } if observed_unix_ms >= *terminal_observed => (
                        FederationCancellationDispositionV1::TerminalAlreadyObserved,
                        observed_unix_ms,
                    ),
                    AttemptState::Terminal { .. } => {
                        return Err(FederationRecoveryError::ClockRegression);
                    }
                }
            }
        };
        Ok(FederationCancelAckMessageV1 {
            query_id: request.query_id.clone(),
            query_binding_digest: request.query_binding_digest,
            cancellation_id: request.cancellation_id.clone(),
            disposition,
            observed_unix_ms: acknowledged_unix_ms,
        })
    }

    pub fn is_cancelled(
        &self,
        peer_id: &StableId,
        query_id: &StableId,
        query_binding_digest: Digest32,
    ) -> bool {
        self.attempts
            .get(&attempt_identity(peer_id, query_id, query_binding_digest))
            .is_some_and(|entry| matches!(entry.state, AttemptState::Cancelled { .. }))
    }

    pub const fn last_observed_unix_ms(&self) -> u64 {
        self.last_observed_unix_ms
    }

    pub fn replay_len(&self) -> usize {
        self.replay.len()
    }

    pub fn attempt_len(&self) -> usize {
        self.attempts.len()
    }

    fn observe_time(&mut self, now_unix_ms: u64) -> Result<(), FederationRecoveryError> {
        if now_unix_ms == 0 {
            return Err(FederationRecoveryError::ZeroObservationTime);
        }
        if now_unix_ms < self.last_observed_unix_ms {
            return Err(FederationRecoveryError::ClockRegression);
        }
        self.last_observed_unix_ms = now_unix_ms;
        Ok(())
    }

    fn require_capacity_isolation(&self) -> Result<(), FederationRecoveryError> {
        if self.replay.len() > self.limits.replay_capacity
            || self.attempts.len() > self.limits.attempt_capacity
        {
            return Err(FederationRecoveryError::SnapshotCapacityExceeded);
        }
        let mut replay_counts = BTreeMap::<&str, usize>::new();
        for entry in self.replay.values() {
            *replay_counts.entry(entry.peer_id.as_str()).or_default() += 1;
        }
        let mut attempt_counts = BTreeMap::<&str, usize>::new();
        for identity in self.attempts.keys() {
            *attempt_counts.entry(identity.peer_id.as_str()).or_default() += 1;
        }
        if replay_counts
            .values()
            .any(|count| *count > self.limits.replay_per_peer_capacity)
            || attempt_counts
                .values()
                .any(|count| *count > self.limits.attempt_per_peer_capacity)
        {
            return Err(FederationRecoveryError::SnapshotCapacityExceeded);
        }
        Ok(())
    }
}

/// Atomically persist before acknowledging any externally visible transition.
/// An implementation that cannot determine whether a failed write committed must
/// reject subsequent operations until reopened; it must not permit a stale live
/// host to overwrite potentially committed recovery state.
pub trait FederationRecoveryStoreV1 {
    fn load(&mut self) -> Result<Option<Vec<u8>>, FederationRecoveryError>;
    fn store(&mut self, snapshot: &[u8]) -> Result<(), FederationRecoveryError>;
}

#[derive(Default)]
pub struct InMemoryFederationRecoveryStoreV1 {
    snapshot: Option<Vec<u8>>,
}

impl InMemoryFederationRecoveryStoreV1 {
    pub fn from_snapshot(snapshot: Vec<u8>) -> Self {
        Self {
            snapshot: Some(snapshot),
        }
    }

    pub fn snapshot(&self) -> Option<&[u8]> {
        self.snapshot.as_deref()
    }
}

impl FederationRecoveryStoreV1 for InMemoryFederationRecoveryStoreV1 {
    fn load(&mut self) -> Result<Option<Vec<u8>>, FederationRecoveryError> {
        Ok(self.snapshot.clone())
    }

    fn store(&mut self, snapshot: &[u8]) -> Result<(), FederationRecoveryError> {
        self.snapshot = Some(snapshot.to_vec());
        Ok(())
    }
}

fn attempt_identity(
    peer_id: &StableId,
    query_id: &StableId,
    query_binding_digest: Digest32,
) -> AttemptIdentity {
    AttemptIdentity {
        peer_id: peer_id.as_str().to_string(),
        query_id: query_id.as_str().to_string(),
        query_binding_digest: *query_binding_digest.as_array(),
    }
}

fn replay_key(
    sender_peer_id: &StableId,
    receiver_peer_id: &StableId,
    key_id: &StableId,
    generation: u64,
    nonce: &[u8; FEDERATION_NONCE_BYTES],
) -> [u8; 32] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(REPLAY_DOMAIN);
    push_string(&mut bytes, sender_peer_id.as_str());
    push_string(&mut bytes, receiver_peer_id.as_str());
    push_string(&mut bytes, key_id.as_str());
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(nonce);
    *Digest32::of_bytes(&bytes).as_array()
}

fn snapshot_digest(payload: &[u8]) -> [u8; 32] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(SNAPSHOT_DIGEST_DOMAIN);
    bytes.extend_from_slice(payload);
    *Digest32::of_bytes(&bytes).as_array()
}

fn push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn validate_peer(value: &str) -> Result<(), FederationRecoveryError> {
    StableId::new(value.to_string())
        .map(|_| ())
        .map_err(|_| FederationRecoveryError::SnapshotIdentityMismatch)
}

fn require_digest(value: Digest32) -> Result<(), FederationRecoveryError> {
    if value.is_zero() {
        return Err(FederationRecoveryError::EmptyDigest);
    }
    Ok(())
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RecoveryEnvelope {
    digest: [u8; 32],
    payload: RecoveryPayload,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RecoveryPayload {
    schema: String,
    local_peer_id: String,
    limits: StoredLimits,
    last_observed_unix_ms: u64,
    replay: Vec<StoredReplayRecord>,
    attempts: Vec<StoredAttemptRecord>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredLimits {
    replay_capacity: usize,
    replay_per_peer_capacity: usize,
    attempt_capacity: usize,
    attempt_per_peer_capacity: usize,
}

impl From<FederationRecoveryLimitsV1> for StoredLimits {
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
struct StoredReplayRecord {
    key: [u8; 32],
    peer_id: String,
    expires_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredAttemptRecord {
    peer_id: String,
    query_id: String,
    query_binding_digest: [u8; 32],
    began_unix_ms: u64,
    expires_unix_ms: u64,
    state: StoredAttemptState,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "kind", rename_all = "snake_case")]
enum StoredAttemptState {
    Pending,
    Cancelled {
        cancellation_id: String,
        reason: u8,
        observed_unix_ms: u64,
    },
    Terminal {
        terminal_digest: [u8; 32],
        observed_unix_ms: u64,
    },
}

impl From<&AttemptState> for StoredAttemptState {
    fn from(value: &AttemptState) -> Self {
        match value {
            AttemptState::Pending => Self::Pending,
            AttemptState::Cancelled {
                cancellation_id,
                reason,
                observed_unix_ms,
            } => Self::Cancelled {
                cancellation_id: cancellation_id.clone(),
                reason: encode_reason(*reason),
                observed_unix_ms: *observed_unix_ms,
            },
            AttemptState::Terminal {
                terminal_digest,
                observed_unix_ms,
            } => Self::Terminal {
                terminal_digest: *terminal_digest,
                observed_unix_ms: *observed_unix_ms,
            },
        }
    }
}

impl TryFrom<StoredAttemptState> for AttemptState {
    type Error = FederationRecoveryError;

    fn try_from(value: StoredAttemptState) -> Result<Self, Self::Error> {
        match value {
            StoredAttemptState::Pending => Ok(Self::Pending),
            StoredAttemptState::Cancelled {
                cancellation_id,
                reason,
                observed_unix_ms,
            } => {
                StableId::new(cancellation_id.clone())
                    .map_err(|_| FederationRecoveryError::SnapshotIdentityMismatch)?;
                Ok(Self::Cancelled {
                    cancellation_id,
                    reason: decode_reason(reason)?,
                    observed_unix_ms,
                })
            }
            StoredAttemptState::Terminal {
                terminal_digest,
                observed_unix_ms,
            } => {
                if terminal_digest.iter().all(|byte| *byte == 0) {
                    return Err(FederationRecoveryError::EmptyDigest);
                }
                Ok(Self::Terminal {
                    terminal_digest,
                    observed_unix_ms,
                })
            }
        }
    }
}

const fn encode_reason(value: FederationCancellationReasonV1) -> u8 {
    match value {
        FederationCancellationReasonV1::CallerCancelled => 1,
        FederationCancellationReasonV1::DeadlineExpired => 2,
        FederationCancellationReasonV1::AuthorityRevoked => 3,
    }
}

fn decode_reason(value: u8) -> Result<FederationCancellationReasonV1, FederationRecoveryError> {
    match value {
        1 => Ok(FederationCancellationReasonV1::CallerCancelled),
        2 => Ok(FederationCancellationReasonV1::DeadlineExpired),
        3 => Ok(FederationCancellationReasonV1::AuthorityRevoked),
        _ => Err(FederationRecoveryError::SnapshotStateInvalid),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationRecoveryError {
    InvalidLimits,
    ZeroObservationTime,
    EmptyDigest,
    ClockRegression,
    Expired,
    Replay,
    ReplayCapacityExhausted,
    ReplayPeerCapacityExhausted,
    AttemptCapacityExhausted,
    AttemptPeerCapacityExhausted,
    DuplicateAttempt,
    UnknownAttempt,
    Cancelled,
    ConflictingTerminal,
    ConflictingCancellation,
    FrameIdentityMismatch,
    SnapshotDecode,
    SnapshotEncode,
    SnapshotNotCanonical,
    SnapshotDigestMismatch,
    SnapshotIdentityMismatch,
    SnapshotStateInvalid,
    SnapshotDuplicate,
    SnapshotCapacityExceeded,
    StoreUnavailable,
    StoreLocked,
    StoreInvalidPath,
    StoreCapacityExceeded,
    StoreIndeterminate,
}

impl fmt::Display for FederationRecoveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidLimits => "invalid durable federation recovery limits",
            Self::ZeroObservationTime => "recovery observation time cannot be zero",
            Self::EmptyDigest => "recovery digest cannot be zero",
            Self::ClockRegression => "durable federation recovery clock regressed",
            Self::Expired => "durable federation record is expired",
            Self::Replay => "durable federation replay detected",
            Self::ReplayCapacityExhausted => "durable replay capacity is exhausted",
            Self::ReplayPeerCapacityExhausted => "one peer exhausted its durable replay partition",
            Self::AttemptCapacityExhausted => "durable attempt capacity is exhausted",
            Self::AttemptPeerCapacityExhausted => {
                "one peer exhausted its durable attempt partition"
            }
            Self::DuplicateAttempt => "durable attempt identity already exists",
            Self::UnknownAttempt => "durable attempt identity is unknown",
            Self::Cancelled => "durable attempt was cancelled before terminal completion",
            Self::ConflictingTerminal => "durable attempt has a conflicting terminal result",
            Self::ConflictingCancellation => "durable attempt has a conflicting cancellation",
            Self::FrameIdentityMismatch => "durable frame identity does not target this host",
            Self::SnapshotDecode => "durable recovery snapshot cannot be decoded",
            Self::SnapshotEncode => "durable recovery snapshot cannot be encoded",
            Self::SnapshotNotCanonical => "durable recovery snapshot is not canonical",
            Self::SnapshotDigestMismatch => "durable recovery snapshot digest mismatch",
            Self::SnapshotIdentityMismatch => "durable recovery snapshot identity mismatch",
            Self::SnapshotStateInvalid => "durable recovery snapshot state is invalid",
            Self::SnapshotDuplicate => "durable recovery snapshot contains a duplicate identity",
            Self::SnapshotCapacityExceeded => {
                "durable recovery snapshot exceeds configured isolation limits"
            }
            Self::StoreUnavailable => "durable federation recovery store is unavailable",
            Self::StoreLocked => "durable federation recovery store already has a writer",
            Self::StoreInvalidPath => "durable federation recovery path identity is invalid",
            Self::StoreCapacityExceeded => {
                "durable federation recovery snapshot exceeds its byte limit"
            }
            Self::StoreIndeterminate => {
                "durable recovery commit is indeterminate; close and reopen the store"
            }
        })
    }
}

impl Error for FederationRecoveryError {}

#[cfg(test)]
#[path = "recovery_validation_tests.rs"]
mod validation_tests;

#[cfg(test)]
#[path = "recovery_index_tests.rs"]
mod index_tests;
