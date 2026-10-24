//! Read the original protected head before selecting its retained material.
//! This observation is neither a live publisher nor a physical recovery proof.

use super::*;

impl HostCognitiveCheckpoint {
    /// Return the complete actual durable head and its original opaque token.
    /// Root uses this read to locate the exact retained last-Current image.
    /// Retirement, physical integrity, authority-lease retirement and successor
    /// adoption remain independent required operations. No runtime lane exposes
    /// this method and no phase, expiry, counter or writer binding is changed.
    pub(crate) fn retained_head_for_root(
        directory: Arc<RootAuthorityDirectory>,
    ) -> Result<CognitiveCheckpointReceipt, AuthorityTrustError> {
        let root = crate::HostAuthorityService::current_root_lifetime_for_admin()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            directory,
            STORE_OWNER.into(),
        )?;
        let receipt = store.with_locked_durable(STORE_OWNER, |head| {
            let registration = HostCognitiveCheckpointRegistration {
                owner_agent_id: head.owner_agent_id.clone(),
                publisher_epoch: head.publisher_epoch,
                writer_binding: head.writer_binding.clone(),
                peer_lifetime: head.peer_lifetime.clone(),
            };
            validate_registration(&registration)?;
            validate_head(&registration, head)?;
            Ok::<_, AuthorityTrustError>(CognitiveCheckpointReceipt {
                token: token_for(head)?,
                head: head.clone(),
            })
        })??;
        if crate::HostAuthorityService::current_root_lifetime_for_admin()
            .map_err(|_| AuthorityTrustError::Unavailable)?
            != root
        {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(receipt)
    }
}
