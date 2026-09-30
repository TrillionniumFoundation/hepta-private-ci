use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::StableId;
use zeroize::Zeroize;

pub const FEDERATION_MAC_KEY_BYTES: usize = 32;
pub const MAX_FEDERATION_CREDENTIAL_KEYS: usize = 4_096;
pub const MAX_FEDERATION_CREDENTIAL_KEYS_PER_PEER_PAIR: usize = 64;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct DirectionalCredentialKey {
    sender_peer_id: StableId,
    receiver_peer_id: StableId,
    key_id: StableId,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct CredentialIdentity {
    key: DirectionalCredentialKey,
    generation: u64,
}

pub struct PeerCredentialV1 {
    identity: CredentialIdentity,
    effective_unix_ms: u64,
    expires_unix_ms: u64,
    secret: [u8; FEDERATION_MAC_KEY_BYTES],
}

impl PeerCredentialV1 {
    pub fn new(
        sender_peer_id: StableId,
        receiver_peer_id: StableId,
        key_id: StableId,
        generation: u64,
        effective_unix_ms: u64,
        expires_unix_ms: u64,
        secret: [u8; FEDERATION_MAC_KEY_BYTES],
    ) -> Result<Self, CredentialError> {
        if sender_peer_id == receiver_peer_id {
            return Err(CredentialError::SamePeer);
        }
        if generation == 0 {
            return Err(CredentialError::ZeroGeneration);
        }
        if effective_unix_ms == 0 || effective_unix_ms >= expires_unix_ms {
            return Err(CredentialError::InvalidLifetime);
        }
        if secret.iter().all(|byte| *byte == 0) {
            return Err(CredentialError::ZeroSecret);
        }
        Ok(Self {
            identity: CredentialIdentity {
                key: DirectionalCredentialKey {
                    sender_peer_id,
                    receiver_peer_id,
                    key_id,
                },
                generation,
            },
            effective_unix_ms,
            expires_unix_ms,
            secret,
        })
    }

    pub fn sender_peer_id(&self) -> &StableId {
        &self.identity.key.sender_peer_id
    }

    pub fn receiver_peer_id(&self) -> &StableId {
        &self.identity.key.receiver_peer_id
    }

    pub fn key_id(&self) -> &StableId {
        &self.identity.key.key_id
    }

    pub const fn generation(&self) -> u64 {
        self.identity.generation
    }

    pub const fn effective_unix_ms(&self) -> u64 {
        self.effective_unix_ms
    }

    pub const fn expires_unix_ms(&self) -> u64 {
        self.expires_unix_ms
    }

    pub(crate) fn secret(&self) -> &[u8; FEDERATION_MAC_KEY_BYTES] {
        &self.secret
    }

    fn directional_key(&self) -> DirectionalCredentialKey {
        self.identity.key.clone()
    }
}

impl fmt::Debug for PeerCredentialV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PeerCredentialV1")
            .field("sender_peer_id", self.sender_peer_id())
            .field("receiver_peer_id", self.receiver_peer_id())
            .field("key_id", self.key_id())
            .field("generation", &self.generation())
            .field("effective_unix_ms", &self.effective_unix_ms())
            .field("expires_unix_ms", &self.expires_unix_ms())
            .field("secret", &"<redacted>")
            .finish()
    }
}

impl Drop for PeerCredentialV1 {
    fn drop(&mut self) {
        self.secret.zeroize();
    }
}

struct CredentialEntry {
    current: Option<PeerCredentialV1>,
    revoked_through_generation: u64,
}

pub struct PeerCredentialRegistryV1 {
    entries: BTreeMap<DirectionalCredentialKey, CredentialEntry>,
    capacity: usize,
    per_peer_pair_capacity: usize,
}

impl Default for PeerCredentialRegistryV1 {
    fn default() -> Self {
        Self::with_limits(
            MAX_FEDERATION_CREDENTIAL_KEYS,
            MAX_FEDERATION_CREDENTIAL_KEYS_PER_PEER_PAIR,
        )
        .expect("architecture credential limits are valid")
    }
}

impl PeerCredentialRegistryV1 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_limits(
        capacity: usize,
        per_peer_pair_capacity: usize,
    ) -> Result<Self, CredentialError> {
        if capacity == 0
            || capacity > MAX_FEDERATION_CREDENTIAL_KEYS
            || per_peer_pair_capacity == 0
            || per_peer_pair_capacity > MAX_FEDERATION_CREDENTIAL_KEYS_PER_PEER_PAIR
            || per_peer_pair_capacity > capacity
        {
            return Err(CredentialError::InvalidCapacity);
        }
        Ok(Self {
            entries: BTreeMap::new(),
            capacity,
            per_peer_pair_capacity,
        })
    }

    /// Enrolls the first generation for one directional key identity.
    /// Subsequent generations must use `rotate`; direct enrollment may not
    /// recreate a tombstoned key or create two simultaneously-current secrets.
    pub fn enroll(&mut self, credential: PeerCredentialV1) -> Result<(), CredentialError> {
        let key = credential.directional_key();
        if let Some(entry) = self.entries.get(&key) {
            return if credential.generation() <= entry.revoked_through_generation {
                Err(CredentialError::Revoked)
            } else {
                Err(CredentialError::DuplicateCredential)
            };
        }
        self.require_capacity_for_new_key(&key)?;
        self.entries.insert(
            key,
            CredentialEntry {
                current: Some(credential),
                revoked_through_generation: 0,
            },
        );
        Ok(())
    }

    /// Installs a strictly newer directional key generation. Only the current
    /// secret is retained; replacing it drops and zeroizes the prior secret.
    /// A monotone generation tombstone continues to fence old frames.
    pub fn rotate(&mut self, credential: PeerCredentialV1) -> Result<(), CredentialError> {
        let key = credential.directional_key();
        let entry = self
            .entries
            .get_mut(&key)
            .ok_or(CredentialError::MissingCredential)?;
        let prior_generation = entry
            .current
            .as_ref()
            .map(PeerCredentialV1::generation)
            .unwrap_or(entry.revoked_through_generation)
            .max(entry.revoked_through_generation);
        if credential.generation() <= prior_generation {
            return Err(CredentialError::NonIncreasingGeneration);
        }
        entry.revoked_through_generation = prior_generation;
        drop(entry.current.replace(credential));
        Ok(())
    }

    pub fn revoke(
        &mut self,
        sender_peer_id: &StableId,
        receiver_peer_id: &StableId,
        key_id: &StableId,
        generation: u64,
    ) -> Result<(), CredentialError> {
        let key = DirectionalCredentialKey {
            sender_peer_id: sender_peer_id.clone(),
            receiver_peer_id: receiver_peer_id.clone(),
            key_id: key_id.clone(),
        };
        let entry = self
            .entries
            .get_mut(&key)
            .ok_or(CredentialError::MissingCredential)?;
        if generation <= entry.revoked_through_generation {
            return Err(CredentialError::Revoked);
        }
        let current_generation = entry.current.as_ref().map(PeerCredentialV1::generation);
        match current_generation {
            Some(current) if current == generation => {
                entry.revoked_through_generation = generation;
                drop(entry.current.take());
                Ok(())
            }
            Some(current) if generation < current => Err(CredentialError::Revoked),
            Some(_) | None => Err(CredentialError::MissingCredential),
        }
    }

    pub fn require_current(
        &self,
        sender_peer_id: &StableId,
        receiver_peer_id: &StableId,
        key_id: &StableId,
        generation: u64,
        now_unix_ms: u64,
    ) -> Result<&PeerCredentialV1, CredentialError> {
        let key = DirectionalCredentialKey {
            sender_peer_id: sender_peer_id.clone(),
            receiver_peer_id: receiver_peer_id.clone(),
            key_id: key_id.clone(),
        };
        let entry = self
            .entries
            .get(&key)
            .ok_or(CredentialError::MissingCredential)?;
        if generation <= entry.revoked_through_generation {
            return Err(CredentialError::Revoked);
        }
        let credential = entry
            .current
            .as_ref()
            .ok_or(CredentialError::MissingCredential)?;
        if generation != credential.generation() {
            return if generation < credential.generation() {
                Err(CredentialError::Revoked)
            } else {
                Err(CredentialError::MissingCredential)
            };
        }
        if now_unix_ms < credential.effective_unix_ms() {
            return Err(CredentialError::NotYetEffective);
        }
        if now_unix_ms >= credential.expires_unix_ms() {
            return Err(CredentialError::Expired);
        }
        Ok(credential)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn active_len(&self) -> usize {
        self.entries
            .values()
            .filter(|entry| entry.current.is_some())
            .count()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    fn require_capacity_for_new_key(
        &self,
        key: &DirectionalCredentialKey,
    ) -> Result<(), CredentialError> {
        if self.entries.len() >= self.capacity {
            return Err(CredentialError::CapacityExhausted);
        }
        let pair_count = self
            .entries
            .keys()
            .filter(|existing| {
                existing.sender_peer_id == key.sender_peer_id
                    && existing.receiver_peer_id == key.receiver_peer_id
            })
            .count();
        if pair_count >= self.per_peer_pair_capacity {
            return Err(CredentialError::PeerPairCapacityExhausted);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CredentialError {
    SamePeer,
    ZeroGeneration,
    InvalidLifetime,
    ZeroSecret,
    InvalidCapacity,
    CapacityExhausted,
    PeerPairCapacityExhausted,
    DuplicateCredential,
    MissingCredential,
    NonIncreasingGeneration,
    Revoked,
    NotYetEffective,
    Expired,
}

impl fmt::Display for CredentialError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::SamePeer => "directional credential cannot use the same sender and receiver",
            Self::ZeroGeneration => "credential generation must be non-zero",
            Self::InvalidLifetime => "credential lifetime is invalid",
            Self::ZeroSecret => "credential secret cannot be all zero",
            Self::InvalidCapacity => "credential registry capacity is invalid",
            Self::CapacityExhausted => "credential registry key capacity is exhausted",
            Self::PeerPairCapacityExhausted => {
                "credential registry peer-pair capacity is exhausted"
            }
            Self::DuplicateCredential => {
                "directional credential is already enrolled; use explicit rotation"
            }
            Self::MissingCredential => "credential identity is not enrolled",
            Self::NonIncreasingGeneration => "rotated credential generation must strictly increase",
            Self::Revoked => "credential is revoked",
            Self::NotYetEffective => "credential is not yet effective",
            Self::Expired => "credential is expired",
        })
    }
}

impl Error for CredentialError {}
