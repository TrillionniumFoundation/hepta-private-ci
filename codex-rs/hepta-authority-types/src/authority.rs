use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::ProductionWriterError;

/// Opaque authority token supplied by an external grant verifier.
///
/// There is deliberately no seed/random/default constructor. The only public
/// constructor is named `from_verified_bytes`; callers are expected to obtain
/// the bytes from a supervisor/grant verifier. The token is never rendered or
/// serialized; only a one-way digest is used as the local SQLite fencing token.
#[derive(Clone, Eq, PartialEq)]
pub struct ProductionAuthorityToken(Arc<[u8]>);

impl ProductionAuthorityToken {
    pub fn from_verified_bytes(bytes: impl Into<Vec<u8>>) -> Result<Self, ProductionWriterError> {
        let bytes = bytes.into();
        if bytes.is_empty() || bytes.len() > 4096 || bytes.contains(&0) {
            return Err(ProductionWriterError::Invalid(
                "authority token must contain 1..=4096 non-NUL bytes".to_string(),
            ));
        }
        Ok(Self(Arc::from(bytes)))
    }

    fn fencing_digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        hasher.update(b"hepta:production-authority-token:v1\0");
        hasher.update(self.0.as_ref());
        Sha256Digest::for_bytes(&hasher.finalize())
    }

    /// Bind the local fence to both the opaque verifier token and the exact
    /// signed grant it authorizes. Persisting only a token digest would let a
    /// lease be reopened under a different grant that reused the same
    /// token/epochs. The grant-bound digest makes that cross-grant reopen fail
    /// closed without adding a mutable column to the append-only lease journal.
    fn fencing_digest_for_grant(&self, grant_digest: &Sha256Digest) -> Sha256Digest {
        let mut hasher = Sha256::new();
        hasher.update(b"hepta:production-authority-token-grant:v2\0");
        hasher.update(grant_digest.as_str().as_bytes());
        hasher.update(self.0.as_ref());
        Sha256Digest::for_bytes(&hasher.finalize())
    }
}

impl fmt::Debug for ProductionAuthorityToken {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionAuthorityToken")
            .field("digest", &self.fencing_digest())
            .finish()
    }
}

/// Minimum externally supplied authority material needed by H4.
///
/// `grant_digest` identifies the signed supervisor/OPE grant. The opaque token
/// is supplied by that verifier and is not derived from a local seed. Epochs
/// and expiry are persisted in the lease chain and checked on each mutation.
#[derive(Clone, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionAuthorityLease {
    pub agent_id: AgentId,
    pub grant_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub lease_expires_at_unix_seconds: u64,
    #[serde(skip)]
    token: Option<ProductionAuthorityToken>,
}

impl fmt::Debug for ProductionAuthorityLease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionAuthorityLease")
            .field("agent_id", &self.agent_id)
            .field("grant_digest", &self.grant_digest)
            .field("authority_epoch", &self.authority_epoch)
            .field("owner_epoch", &self.owner_epoch)
            .field(
                "lease_expires_at_unix_seconds",
                &self.lease_expires_at_unix_seconds,
            )
            .field(
                "token",
                &self
                    .token
                    .as_ref()
                    .map(ProductionAuthorityToken::fencing_digest),
            )
            .finish()
    }
}

impl ProductionAuthorityLease {
    /// Construct lease material after an external verifier has checked the
    /// signed grant and supplied its opaque token. This performs shape checks
    /// only; `ProductionDurableWriter::open` still requires a verifier.
    pub fn from_verified_parts(
        agent_id: AgentId,
        grant_digest: Sha256Digest,
        authority_epoch: u64,
        owner_epoch: u64,
        lease_expires_at_unix_seconds: u64,
        token: ProductionAuthorityToken,
    ) -> Result<Self, ProductionWriterError> {
        if authority_epoch == 0 || owner_epoch == 0 {
            return Err(ProductionWriterError::Invalid(
                "authority and owner epochs must be non-zero".to_string(),
            ));
        }
        if lease_expires_at_unix_seconds == 0 {
            return Err(ProductionWriterError::Invalid(
                "authority lease expiry must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            agent_id,
            grant_digest,
            authority_epoch,
            owner_epoch,
            lease_expires_at_unix_seconds,
            token: Some(token),
        })
    }

    pub fn fencing_token_digest(&self) -> Result<Sha256Digest, ProductionWriterError> {
        self.token
            .as_ref()
            .map(|token| token.fencing_digest_for_grant(&self.grant_digest))
            .ok_or_else(|| {
                ProductionWriterError::AuthorityRejected(
                    "deserialized authority lease has no opaque token".to_string(),
                )
            })
    }

    pub fn is_expired_at(&self, now_unix_seconds: u64) -> bool {
        now_unix_seconds >= self.lease_expires_at_unix_seconds
    }
}

/// External verifier hook. Implementations should verify the signed grant,
/// scope, epoch, and opaque token before returning `Ok(())`.
///
/// The writer never treats a boolean field on the lease as authority and has
/// no built-in/self-signing implementation of this trait.
pub trait ProductionAuthorityVerifier: Send + Sync {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String>;

    /// Authenticate a sender's process generation separately from the local
    /// lease CAS generation. Existing verifiers retain the original equal-
    /// generation profile. A verifier admitting different values must bind
    /// both and the lease id to its independently verified live registration;
    /// possession of a writer handle alone does not authorize a new process.
    fn verify_sender_process_binding(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
        _local_lease_id: &str,
        local_generation: u64,
        spawn_generation: u64,
    ) -> Result<(), String> {
        self.verify(authority, expected_agent)?;
        if spawn_generation == 0 || spawn_generation != local_generation {
            return Err("sender process generation is not authorized by this verifier".into());
        }
        Ok(())
    }
}

impl<F> ProductionAuthorityVerifier for F
where
    F: Fn(&ProductionAuthorityLease, &AgentId) -> Result<(), String> + Send + Sync,
{
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        self(authority, expected_agent)
    }
}
