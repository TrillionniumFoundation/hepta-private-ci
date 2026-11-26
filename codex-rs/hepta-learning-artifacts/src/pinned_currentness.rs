//! Immutable time facts retained from an authenticated CURRENT refresh.

use crate::ArtifactOwnerHostError;
use crate::RegistryHeadWitnessV1;
use crate::TrustedArtifactSignerV1;

/// Read-only validity facts from an opaque, authority-verified CURRENT view.
/// This is not a registry refresh and cannot admit a candidate or issue a view.
#[derive(Clone, Copy, Debug)]
pub struct VerifiedCurrentRegistryUseWindowV1 {
    verified_at: u64,
    issued_at: u64,
    head_expires_at: u64,
    signer_valid_from: u64,
    signer_expires_at: u64,
    signer_revoked_at: Option<u64>,
}

impl VerifiedCurrentRegistryUseWindowV1 {
    pub(crate) fn from_verified_head(
        head: &RegistryHeadWitnessV1,
        signer: &TrustedArtifactSignerV1,
        verified_at: u64,
    ) -> Self {
        Self {
            verified_at,
            issued_at: head.issued_at,
            head_expires_at: head.expires_at,
            signer_valid_from: signer.valid_from,
            signer_expires_at: signer.expires_at,
            signer_revoked_at: signer.revoked_at,
        }
    }

    /// Recheck the exact verified head and actor windows without owner I/O or
    /// signatures. Expiry remains inclusive; known revocation is exclusive.
    pub fn revalidate_at(&self, now: u64) -> Result<(), ArtifactOwnerHostError> {
        if now < self.verified_at || now < self.issued_at || self.issued_at < self.signer_valid_from
        {
            return Err(ArtifactOwnerHostError::SignerContext);
        }
        if now > self.head_expires_at {
            return Err(ArtifactOwnerHostError::CurrentHeadExpired);
        }
        if now > self.signer_expires_at || self.signer_revoked_at.is_some_and(|at| now >= at) {
            return Err(ArtifactOwnerHostError::SignerRevoked);
        }
        Ok(())
    }
}
