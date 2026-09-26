use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::StableId;

pub const FEDERATION_MAC_KEY_BYTES: usize = 32;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct CredentialIdentity {
    sender_peer_id: StableId,
    receiver_peer_id: StableId,
    key_id: StableId,
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
                sender_peer_id,
                receiver_peer_id,
                key_id,
                generation,
            },
            effective_unix_ms,
            expires_unix_ms,
            secret,
        })
    }

    pub fn sender_peer_id(&self) -> &StableId {
        &self.identity.sender_peer_id
    }

    pub fn receiver_peer_id(&self) -> &StableId {
        &self.identity.receiver_peer_id
    }

    pub fn key_id(&self) -> &StableId {
        &self.identity.key_id
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
        self.secret.fill(0);
    }
}

#[derive(Default)]
pub struct PeerCredentialRegistryV1 {
    credentials: BTreeMap<CredentialIdentity, PeerCredentialV1>,
    revoked: BTreeSet<CredentialIdentity>,
}

impl PeerCredentialRegistryV1 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn enroll(&mut self, credential: PeerCredentialV1) -> Result<(), CredentialError> {
        let identity = credential.identity.clone();
        if self.credentials.contains_key(&identity) {
            return Err(CredentialError::DuplicateCredential);
        }
        if self.revoked.contains(&identity) {
            return Err(CredentialError::Revoked);
        }
        self.credentials.insert(identity, credential);
        Ok(())
    }

    /// Installs a strictly newer directional key generation and revokes all
    /// older generations for the same sender, receiver and key identity.
    pub fn rotate(&mut self, credential: PeerCredentialV1) -> Result<(), CredentialError> {
        let generation = credential.generation();
        let prior = self
            .credentials
            .keys()
            .filter(|identity| {
                identity.sender_peer_id == *credential.sender_peer_id()
                    && identity.receiver_peer_id == *credential.receiver_peer_id()
                    && identity.key_id == *credential.key_id()
            })
            .cloned()
            .collect::<Vec<_>>();
        if prior
            .iter()
            .any(|identity| identity.generation >= generation)
        {
            return Err(CredentialError::NonIncreasingGeneration);
        }
        self.enroll(credential)?;
        self.revoked.extend(prior);
        Ok(())
    }

    pub fn revoke(
        &mut self,
        sender_peer_id: &StableId,
        receiver_peer_id: &StableId,
        key_id: &StableId,
        generation: u64,
    ) -> Result<(), CredentialError> {
        let identity = CredentialIdentity {
            sender_peer_id: sender_peer_id.clone(),
            receiver_peer_id: receiver_peer_id.clone(),
            key_id: key_id.clone(),
            generation,
        };
        if !self.credentials.contains_key(&identity) {
            return Err(CredentialError::MissingCredential);
        }
        self.revoked.insert(identity);
        Ok(())
    }

    pub fn require_current(
        &self,
        sender_peer_id: &StableId,
        receiver_peer_id: &StableId,
        key_id: &StableId,
        generation: u64,
        now_unix_ms: u64,
    ) -> Result<&PeerCredentialV1, CredentialError> {
        let identity = CredentialIdentity {
            sender_peer_id: sender_peer_id.clone(),
            receiver_peer_id: receiver_peer_id.clone(),
            key_id: key_id.clone(),
            generation,
        };
        if self.revoked.contains(&identity) {
            return Err(CredentialError::Revoked);
        }
        let credential = self
            .credentials
            .get(&identity)
            .ok_or(CredentialError::MissingCredential)?;
        if now_unix_ms < credential.effective_unix_ms() {
            return Err(CredentialError::NotYetEffective);
        }
        if now_unix_ms >= credential.expires_unix_ms() {
            return Err(CredentialError::Expired);
        }
        Ok(credential)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CredentialError {
    SamePeer,
    ZeroGeneration,
    InvalidLifetime,
    ZeroSecret,
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
            Self::DuplicateCredential => "credential identity is already enrolled",
            Self::MissingCredential => "credential identity is not enrolled",
            Self::NonIncreasingGeneration => "rotated credential generation must strictly increase",
            Self::Revoked => "credential is revoked",
            Self::NotYetEffective => "credential is not yet effective",
            Self::Expired => "credential is expired",
        })
    }
}

impl Error for CredentialError {}
