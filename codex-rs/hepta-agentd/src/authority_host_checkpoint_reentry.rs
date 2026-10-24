//! Trusted observation of an actually retired publisher and its original cut.
//! No peer lane, writer capability, token counter or replacement cut is created.

use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use std::io;

impl HostCognitiveCheckpoint {
    /// Reconcile the actual complete durable head after a launch has ended.
    /// Unlike a runtime read, this observation does not revive an expired or
    /// closed publisher. The exact registered publisher must actually be
    /// retired, and the independently retained physical last-Current image
    /// must still match. Dirty/Publishing/Fenced phases are returned unchanged.
    pub(crate) fn read_retired_head_for_root(
        directory: Arc<RootAuthorityDirectory>,
        registration: &HostCognitiveCheckpointRegistration,
        predecessor: &RetiredCheckpointPublisher,
        material: &VerifiedCognitiveMaterial,
    ) -> Result<CognitiveCheckpointReceipt, AuthorityTrustError> {
        if unsafe { libc::geteuid() } != 0 || registration.peer_lifetime != predecessor.lifetime {
            return Err(AuthorityTrustError::Invalid);
        }
        validate_registration(registration)?;
        predecessor.require_retired()?;
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            directory,
            STORE_OWNER.into(),
        )?;
        store.with_locked_durable(STORE_OWNER, |head| {
            validate_head(registration, head)?;
            if material.anchor() != &head.last_current {
                return Err(AuthorityTrustError::Invalid);
            }
            material
                .verify_unchanged()
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            predecessor.require_retired()?;
            // This is the original owner's encoding of the actually retained
            // full head. No requested phase, cut, counter or token is accepted.
            Ok(CognitiveCheckpointReceipt {
                token: token_for(head)?,
                head: head.clone(),
            })
        })?
    }

    /// Hold the original head's publication lock and the held physical image
    /// across one canonical issuer operation. The failed writer's local
    /// generation must be precisely the next one not installed in this head.
    /// Its original lease retirement is enforced by the surrounding issuer's
    /// registry boundary; this method cannot issue or replace that authority.
    pub(crate) fn with_unactivated_writer_cut_for_root<R>(
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &RetiredCheckpointPublisher,
        failed: &crate::HostAuthorityWriterRegistration,
        failed_publisher: &RetiredCheckpointPublisher,
        successor: &RetainedCheckpointPublisher,
        material: &VerifiedCognitiveMaterial,
        replace_authorization: impl FnOnce() -> io::Result<R>,
    ) -> io::Result<R> {
        if unsafe { libc::geteuid() } != 0 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "actual Root required",
            ));
        }
        let old = &previous.head;
        let registration = HostCognitiveCheckpointRegistration {
            owner_agent_id: old.owner_agent_id.clone(),
            publisher_epoch: old.publisher_epoch,
            writer_binding: old.writer_binding.clone(),
            peer_lifetime: old.peer_lifetime.clone(),
        };
        validate_registration(&registration).map_err(io::Error::other)?;
        validate_head(&registration, old).map_err(io::Error::other)?;
        if token_for(old).map_err(io::Error::other)? != previous.token
            || predecessor.lifetime != old.peer_lifetime
            || failed.registered_agent_id != old.owner_agent_id
            || failed.local_lease_id != old.writer_binding.lease_id
            || old.writer_binding.generation.checked_add(1) != Some(failed.local_lease_generation)
            || failed.authority_lease.authority_epoch != old.writer_binding.authority_epoch
            || failed.owner_epoch <= old.writer_binding.owner_epoch
            || failed_publisher.lifetime == old.peer_lifetime
            || failed_publisher.lifetime.uid != old.peer_lifetime.uid
            || successor.lifetime == old.peer_lifetime
            || successor.lifetime == failed_publisher.lifetime
            || successor.lifetime.uid != old.peer_lifetime.uid
            || material.anchor() != &old.last_current
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "unactivated writer differs from original predecessor",
            ));
        }
        // Ordinary failed publishers remain strictly same-boot. A failure
        // from an earlier boot additionally needs the original pre-signing
        // Root observation committed by that exact canonical candidate's
        // signed payload; it cannot be substituted for a protected head.
        failed_publisher
            .require_unactivated_successor(previous, failed, &successor.lifetime)
            .map_err(io::Error::other)?;
        predecessor
            .require_physical_successor(previous, &successor.lifetime)
            .map_err(io::Error::other)?;
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            directory,
            STORE_OWNER.into(),
        )
        .map_err(io::Error::other)?;
        store
            .with_locked_durable(STORE_OWNER, |actual| {
                if actual != old {
                    return Err(io::Error::other(AuthorityTrustError::Conflict));
                }
                predecessor.require_retired().map_err(io::Error::other)?;
                failed_publisher
                    .require_retired()
                    .map_err(io::Error::other)?;
                successor.require_alive().map_err(io::Error::other)?;
                material.verify_unchanged().map_err(io::Error::other)?;
                let outcome = replace_authorization();
                // Even a failed replacement can have reserved an issuer sequence
                // or retained its exact new proof. Never refund or replace the cut.
                material.verify_unchanged().map_err(io::Error::other)?;
                predecessor.require_retired().map_err(io::Error::other)?;
                failed_publisher
                    .require_retired()
                    .map_err(io::Error::other)?;
                outcome
                // The canonical issuer may already have committed inside the
                // callback. An unavailable or malformed post-read cannot report an
                // unchanged authorization; the trusted caller must reconcile it.
            })
            .map_err(|_| io::Error::other(AuthorityTrustError::Unavailable))?
    }
}

#[path = "authority_host_checkpoint_observation.rs"]
mod observation;
