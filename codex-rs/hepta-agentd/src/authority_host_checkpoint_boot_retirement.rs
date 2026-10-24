//! Root observation of a former boot's original publisher and physical cut.
//! This proves process retirement only. The original lease registry, canonical
//! signed writer rotation, and strict checkpoint CAS remain separate gates.

use super::super::*;
use super::*;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_memory::VerifiedCognitiveMaterial;

impl HostCognitiveCheckpoint {
    /// Read the actual complete protected head and construct nonserializable
    /// prior-boot retirement evidence. No caller supplies the former boot,
    /// publisher, replacement token, phase, cut or a claimed termination.
    ///
    /// The concrete original clock must have durably admitted the actual new
    /// boot under its existing highwater rule. A boot change does not expire
    /// or revoke an authority lease and does not authorize a new CPU namespace.
    pub(crate) fn observe_previous_boot_for_root(
        directory: Arc<RootAuthorityDirectory>,
        clock: &HostAuthorityClock,
        material: &VerifiedCognitiveMaterial,
    ) -> Result<(CognitiveCheckpointReceipt, RetiredCheckpointPublisher), AuthorityTrustError> {
        let root = crate::HostAuthorityService::current_root_lifetime_for_admin()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        // refresh_projection uses actual OS time and boot identity. It never
        // resets the retained time highwater to make a new boot acceptable.
        let observed = clock.refresh_projection()?;
        if observed.projection.boot_id != root.boot_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            directory,
            STORE_OWNER.into(),
        )?;
        let (receipt, retired) = store.with_locked_durable(STORE_OWNER, |head| {
            let registration = HostCognitiveCheckpointRegistration {
                owner_agent_id: head.owner_agent_id.clone(),
                publisher_epoch: head.publisher_epoch,
                writer_binding: head.writer_binding.clone(),
                peer_lifetime: head.peer_lifetime.clone(),
            };
            validate_registration(&registration)?;
            validate_head(&registration, head)?;
            if head.peer_lifetime.boot_id == root.boot_id {
                return Err(AuthorityTrustError::Conflict);
            }
            if material.anchor() != &head.last_current {
                return Err(AuthorityTrustError::Invalid);
            }
            material
                .verify_unchanged()
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            let receipt = CognitiveCheckpointReceipt {
                token: token_for(head)?,
                head: head.clone(),
            };
            let retired = RetiredCheckpointPublisher {
                lifetime: head.peer_lifetime.clone(),
                evidence: RetirementEvidence::PriorBoot {
                    root: root.clone(),
                    predecessor: receipt.token.clone(),
                },
            };
            retired.require_retired()?;
            Ok((receipt, retired))
        })??;
        material
            .verify_unchanged()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        retired.require_retired()?;
        Ok((receipt, retired))
    }
}
