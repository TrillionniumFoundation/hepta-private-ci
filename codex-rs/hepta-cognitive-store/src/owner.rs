//! Compile-time contract for the one physical cognitive-store owner.
//!
//! This module deliberately contains no SQL handle or mutation API. The
//! durable implementation lives in the owner crate and implements this trait;
//! semantic/in-memory stores must not claim this binding.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableStoreProfileV1 {
    SqliteWalSynchronousFull,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableWriterFenceProfileV1 {
    ExternalAuthorityGrantProcessLockAndCas,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableRecoveryProfileV1 {
    OrdinaryVerifiedOpen,
    DescriptorSafeReadOnlyCurrentCut,
    DescriptorSafeWriterUnavailable,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveStoreOwnerDescriptorV1 {
    pub owner_identity_digest: Digest32,
    pub physical_store_digest: Digest32,
    pub schema_version: u32,
    pub durability: DurableStoreProfileV1,
    pub writer_fence: DurableWriterFenceProfileV1,
    pub recovery: DurableRecoveryProfileV1,
    pub authority: AuthorityPosture,
}

impl CognitiveStoreOwnerDescriptorV1 {
    pub fn validate(&self) -> Result<(), OwnerDescriptorError> {
        if self.owner_identity_digest.is_zero() {
            return Err(OwnerDescriptorError::EmptyDigest("owner_identity"));
        }
        if self.physical_store_digest.is_zero() {
            return Err(OwnerDescriptorError::EmptyDigest("physical_store"));
        }
        if self.schema_version == 0 {
            return Err(OwnerDescriptorError::ZeroSchemaVersion);
        }
        if self.authority.grants_any() {
            return Err(OwnerDescriptorError::AuthorityGranted);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OwnerDescriptorError {
    EmptyDigest(&'static str),
    ZeroSchemaVersion,
    AuthorityGranted,
}

/// Implemented only by the selected physical owner.
///
/// Returning this descriptor is evidence of compile-time ownership binding,
/// not a write grant, runtime activation, recovery admission, or release.
pub trait AuthoritativeCognitiveStoreOwnerV1 {
    fn owner_descriptor_v1(&self) -> CognitiveStoreOwnerDescriptorV1;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn descriptor_is_authority_free_and_rejects_empty_identity() {
        let valid = CognitiveStoreOwnerDescriptorV1 {
            owner_identity_digest: Digest32::of_bytes(b"owner"),
            physical_store_digest: Digest32::of_bytes(b"store"),
            schema_version: 1,
            durability: DurableStoreProfileV1::SqliteWalSynchronousFull,
            writer_fence: DurableWriterFenceProfileV1::ExternalAuthorityGrantProcessLockAndCas,
            recovery: DurableRecoveryProfileV1::DescriptorSafeWriterUnavailable,
            authority: AuthorityPosture::DENY_ALL,
        };
        assert_eq!(valid.validate(), Ok(()));

        let invalid = CognitiveStoreOwnerDescriptorV1 {
            owner_identity_digest: Digest32::ZERO,
            ..valid
        };
        assert_eq!(
            invalid.validate(),
            Err(OwnerDescriptorError::EmptyDigest("owner_identity"))
        );
    }
}
