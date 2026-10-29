//! Explicit opaque Windows namespace input for the original final-use owner.
//! Ordinary path factories remain closed pending complete native qualification.

use super::FinalUseAuthority;
use super::FinalUseError;
use super::FinalUseFrontier;
use super::FinalUseIssuerTrustKey;
use super::FinalUseRevocations;
use super::Inner;
use super::PinnedIssuerKey;
use super::frontier_for_state;
use super::identifier;
use super::map_trust_error;
use super::pin_issuer_keys;
use super::store;
use super::valid_head;
use crate::AuthorityClock;
use crate::AuthorityFrontierStore;
use ed25519_dalek::VerifyingKey;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;

impl FinalUseAuthority {
    /// Open the original one-key owner using a real private namespace capability.
    /// Cold marker/schema/trust/claims and actual external frontier are checked
    /// before migration or recovery writes. No path or receipt grants authority.
    pub fn open_windows_private_with_trust(
        directory: crate::windows_private_owner::PrivateStoreDirectory,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        let key =
            VerifyingKey::from_bytes(&verifying_key).map_err(|_| FinalUseError::InvalidTrust)?;
        if !identifier(&signer_id) || key.is_weak() || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (store, state) = store::Store::open_windows(
            directory,
            &signer_id,
            store::StoreTrust::SingleKey(verifying_key),
            head,
            frontier_store.as_ref(),
        )?;
        let observed = frontier_for_state(&state);
        let trusted = frontier_store.load(&signer_id).map_err(map_trust_error)?;
        if trusted != observed {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys: vec![PinnedIssuerKey {
                key_id: "single-key".into(),
                key: super::IssuerVerifier::Ed25519V1(key),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: u64::MAX,
            }],
            state: Mutex::new(state),
            active_dispatches: AtomicUsize::new(0),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }

    /// Open the original rotating issuer owner through the same held capability.
    /// This retains original V3/legacy migrations and external anti-rollback checks.
    pub fn open_windows_private_with_issuer_keys(
        directory: crate::windows_private_owner::PrivateStoreDirectory,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        if !identifier(&signer_id) || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (issuer_keys, issuer_trust_sha256) = pin_issuer_keys(issuer_keys)?;
        let (store, state) = store::Store::open_windows(
            directory,
            &signer_id,
            store::StoreTrust::IssuerKeyRing(issuer_trust_sha256),
            head,
            frontier_store.as_ref(),
        )?;
        let observed = frontier_for_state(&state);
        let trusted = frontier_store.load(&signer_id).map_err(map_trust_error)?;
        if trusted != observed {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys,
            state: Mutex::new(state),
            active_dispatches: AtomicUsize::new(0),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }
}

#[cfg(test)]
#[path = "final_use_windows_tests.rs"]
mod tests;
