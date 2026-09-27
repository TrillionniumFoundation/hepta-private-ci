use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const MAX_FEDERATION_REPLAY_ENTRIES: usize = 16_384;
pub const MAX_FEDERATION_REPLAY_ENTRIES_PER_CREDENTIAL: usize = 1_024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct ReplayEntry {
    credential_scope: [u8; 32],
    expires_unix_ms: u64,
}

#[derive(Clone)]
pub struct ReplayCacheV1 {
    capacity: usize,
    per_credential_capacity: usize,
    last_observed_unix_ms: u64,
    entries: BTreeMap<[u8; 32], ReplayEntry>,
    credential_counts: BTreeMap<[u8; 32], usize>,
}

impl ReplayCacheV1 {
    pub fn new(capacity: usize) -> Result<Self, ReplayError> {
        Self::with_limits(
            capacity,
            capacity.min(MAX_FEDERATION_REPLAY_ENTRIES_PER_CREDENTIAL),
        )
    }

    pub fn with_limits(
        capacity: usize,
        per_credential_capacity: usize,
    ) -> Result<Self, ReplayError> {
        if capacity == 0 || capacity > MAX_FEDERATION_REPLAY_ENTRIES {
            return Err(ReplayError::InvalidCapacity(capacity));
        }
        if per_credential_capacity == 0 || per_credential_capacity > capacity {
            return Err(ReplayError::InvalidCredentialCapacity(
                per_credential_capacity,
            ));
        }
        Ok(Self {
            capacity,
            per_credential_capacity,
            last_observed_unix_ms: 0,
            entries: BTreeMap::new(),
            credential_counts: BTreeMap::new(),
        })
    }

    /// Admits a nonce exactly once for its authenticated directional key.
    ///
    /// A full cache fails closed rather than evicting an unexpired nonce, since
    /// eviction would reopen the replay window under load. The cache also
    /// remembers the greatest admitted observation time and rejects a later
    /// call whose clock regresses, even after the original nonce has expired
    /// and been purged. Per-credential capacity prevents one directional peer
    /// credential from consuming the entire host-wide replay budget.
    pub fn admit(
        &mut self,
        sender_peer_id: &StableId,
        receiver_peer_id: &StableId,
        key_id: &StableId,
        generation: u64,
        nonce: &[u8; 32],
        expires_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<(), ReplayError> {
        if generation == 0 {
            return Err(ReplayError::ZeroGeneration);
        }
        self.observe_time(now_unix_ms)?;
        if expires_unix_ms <= now_unix_ms {
            return Err(ReplayError::Expired);
        }
        self.purge_expired_unchecked(now_unix_ms);
        let credential_scope = credential_scope_key(
            sender_peer_id,
            receiver_peer_id,
            key_id,
            generation,
        );
        let key = replay_key(
            sender_peer_id,
            receiver_peer_id,
            key_id,
            generation,
            nonce,
        );
        if self.entries.contains_key(&key) {
            return Err(ReplayError::Replay);
        }
        if self.entries.len() >= self.capacity {
            return Err(ReplayError::CapacityExhausted);
        }
        if self
            .credential_counts
            .get(&credential_scope)
            .copied()
            .unwrap_or_default()
            >= self.per_credential_capacity
        {
            return Err(ReplayError::CredentialCapacityExhausted);
        }
        self.entries.insert(
            key,
            ReplayEntry {
                credential_scope,
                expires_unix_ms,
            },
        );
        *self
            .credential_counts
            .entry(credential_scope)
            .or_insert(0) += 1;
        Ok(())
    }

    pub fn purge_expired(&mut self, now_unix_ms: u64) -> Result<usize, ReplayError> {
        self.observe_time(now_unix_ms)?;
        Ok(self.purge_expired_unchecked(now_unix_ms))
    }

    pub const fn capacity(&self) -> usize {
        self.capacity
    }

    pub const fn per_credential_capacity(&self) -> usize {
        self.per_credential_capacity
    }

    pub const fn last_observed_unix_ms(&self) -> u64 {
        self.last_observed_unix_ms
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    fn observe_time(&mut self, now_unix_ms: u64) -> Result<(), ReplayError> {
        if now_unix_ms < self.last_observed_unix_ms {
            return Err(ReplayError::ClockRegression);
        }
        self.last_observed_unix_ms = now_unix_ms;
        Ok(())
    }

    fn purge_expired_unchecked(&mut self, now_unix_ms: u64) -> usize {
        let before = self.entries.len();
        let mut removed_scopes = Vec::new();
        self.entries.retain(|_, entry| {
            let keep = entry.expires_unix_ms > now_unix_ms;
            if !keep {
                removed_scopes.push(entry.credential_scope);
            }
            keep
        });
        for scope in removed_scopes {
            let remove_scope = match self.credential_counts.get_mut(&scope) {
                Some(count) => {
                    *count = count.saturating_sub(1);
                    *count == 0
                }
                None => false,
            };
            if remove_scope {
                self.credential_counts.remove(&scope);
            }
        }
        before.saturating_sub(self.entries.len())
    }
}

fn credential_scope_key(
    sender_peer_id: &StableId,
    receiver_peer_id: &StableId,
    key_id: &StableId,
    generation: u64,
) -> [u8; 32] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.memory-federation.replay-credential.v1");
    push_id(&mut bytes, sender_peer_id);
    push_id(&mut bytes, receiver_peer_id);
    push_id(&mut bytes, key_id);
    bytes.extend_from_slice(&generation.to_be_bytes());
    *Digest32::of_bytes(&bytes).as_array()
}

fn replay_key(
    sender_peer_id: &StableId,
    receiver_peer_id: &StableId,
    key_id: &StableId,
    generation: u64,
    nonce: &[u8; 32],
) -> [u8; 32] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.memory-federation.replay.v1");
    push_id(&mut bytes, sender_peer_id);
    push_id(&mut bytes, receiver_peer_id);
    push_id(&mut bytes, key_id);
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(nonce);
    *Digest32::of_bytes(&bytes).as_array()
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReplayError {
    InvalidCapacity(usize),
    InvalidCredentialCapacity(usize),
    ZeroGeneration,
    ClockRegression,
    Expired,
    Replay,
    CapacityExhausted,
    CredentialCapacityExhausted,
}

impl fmt::Display for ReplayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidCapacity(value) => write!(formatter, "invalid replay capacity {value}"),
            Self::InvalidCredentialCapacity(value) => {
                write!(formatter, "invalid replay per-credential capacity {value}")
            }
            Self::ZeroGeneration => formatter.write_str("replay key generation must be non-zero"),
            Self::ClockRegression => {
                formatter.write_str("replay cache observation time regressed")
            }
            Self::Expired => formatter.write_str("replay entry is already expired"),
            Self::Replay => formatter.write_str("authenticated federation frame was replayed"),
            Self::CapacityExhausted => {
                formatter.write_str("replay cache is full with unexpired entries")
            }
            Self::CredentialCapacityExhausted => formatter.write_str(
                "directional federation credential exhausted its replay-cache partition",
            ),
        }
    }
}

impl Error for ReplayError {}
