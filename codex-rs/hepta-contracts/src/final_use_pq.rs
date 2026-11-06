//! Explicit PQ construction of the existing durable final-use owner.

use super::*;
use crate::PqAuthorityTrustKey;
use crate::authority_authentication::pin_pq_keys;

impl FinalUseAuthority {
    /// Opens a fresh PQ namespace with host-protected time and an independent
    /// external CAS frontier. Classic stores and grants are never migrated or
    /// accepted by this constructor. Concrete service/key custody qualification
    /// remains a deployment requirement.
    pub fn open_pq_state_dir_with_issuer_keys(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<PqAuthorityTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        if !identifier(&signer_id)
            || !valid_head_with_profile(&head, FinalUseAuthenticationProfile::MlDsa65V2)
        {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let keys = pin_pq_keys(issuer_keys).map_err(|()| FinalUseError::InvalidTrust)?;
        let mut hash = Sha256::new();
        hash.update(b"hepta.kernel.authority.final-use-issuer-trust.pq.v2\0");
        let mut issuer_keys = Vec::with_capacity(keys.len());
        for key in keys {
            hash.update((key.key_id.len() as u64).to_be_bytes());
            hash.update(key.key_id.as_bytes());
            hash.update(key.public_key_id);
            hash.update(key.not_before_authority_epoch.to_be_bytes());
            hash.update(key.not_after_authority_epoch.to_be_bytes());
            issuer_keys.push(PinnedIssuerKey {
                key_id: key.key_id,
                key: key.key,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            });
        }
        let (store, state) = store::Store::open_pq_key_ring_exact(
            directory,
            &signer_id,
            hash.finalize().into(),
            head,
        )?;
        let profile = FinalUseAuthenticationProfile::MlDsa65V2;
        let observed = frontier_for_state_with_profile(&state, profile);
        let trusted = frontier_store.load(&signer_id).map_err(map_trust_error)?;
        if trusted != observed {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys,
            profile,
            state: Mutex::new(state),
            active_dispatches: AtomicUsize::new(0),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }
}
