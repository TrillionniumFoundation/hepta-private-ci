use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const MAX_FEDERATION_REPLAY_ENTRIES: usize = 16_384;

pub struct ReplayCacheV1 {
    capacity: usize,
    entries: BTreeMap<[u8; 32], u64>,
}

impl ReplayCacheV1 {
    pub fn new(capacity: usize) -> Result<Self, ReplayError> {
        if capacity == 0 || capacity > MAX_FEDERATION_REPLAY_ENTRIES {
            return Err(ReplayError::InvalidCapacity(capacity));
        }
        Ok(Self {
            capacity,
            entries: BTreeMap::new(),
        })
    }

    /// Admits a nonce exactly once for its authenticated directional key.
    ///
    /// A full cache fails closed rather than evicting an unexpired nonce, since
    /// eviction would reopen the replay window under load.
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
        if expires_unix_ms <= now_unix_ms {
            return Err(ReplayError::Expired);
        }
        self.entries.retain(|_, expiry| *expiry > now_unix_ms);
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
        self.entries.insert(key, expires_unix_ms);
        Ok(())
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
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
    ZeroGeneration,
    Expired,
    Replay,
    CapacityExhausted,
}

impl fmt::Display for ReplayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidCapacity(value) => write!(formatter, "invalid replay capacity {value}"),
            Self::ZeroGeneration => formatter.write_str("replay key generation must be non-zero"),
            Self::Expired => formatter.write_str("replay entry is already expired"),
            Self::Replay => formatter.write_str("authenticated federation frame was replayed"),
            Self::CapacityExhausted => {
                formatter.write_str("replay cache is full with unexpired entries")
            }
        }
    }
}

impl Error for ReplayError {}
