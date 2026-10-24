//! Original Root preparation binds an actual publisher to a candidate proof.
//! The durable record grants no authority and never publishes a Current head.

use super::*;
use crate::deployment_issuer::WriterRegistrationExt;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::RootStoredObservation;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ActivationRecord {
    schema_version: u32,
    previous_token: CognitiveCheckpointToken,
    material_cut_sha256: Sha256Digest,
    root: CognitiveCheckpointPeerLifetime,
    peer: CognitiveCheckpointPeerLifetime,
    candidate: crate::HostAuthorityWriterRegistration,
}

/// Constructed only by the original checkpoint owner after checking the full
/// candidate commitment and its actual protected predecessor. This is private
/// process-observation custody, not a serializable retirement capability.
pub(super) struct RetainedCheckpointActivation {
    record: ActivationRecord,
    stored: RootStoredObservation,
}

fn invalid() -> AuthorityTrustError {
    AuthorityTrustError::Invalid
}
fn unavailable(_: impl std::fmt::Display) -> AuthorityTrustError {
    AuthorityTrustError::Unavailable
}
fn candidate_name(
    candidate: &crate::HostAuthorityWriterRegistration,
) -> Result<String, AuthorityTrustError> {
    let bytes = serde_json::to_vec(candidate).map_err(unavailable)?;
    Ok(format!(
        "checkpoint-activation-v1.{}",
        Sha256Digest::for_bytes(&bytes).as_str()
    ))
}
fn cut_digest(material: &VerifiedCognitiveMaterial) -> Result<Sha256Digest, AuthorityTrustError> {
    Ok(Sha256Digest::for_bytes(
        &serde_json::to_vec(material.anchor()).map_err(unavailable)?,
    ))
}
fn payload_commitment(record: &ActivationRecord) -> Result<[u8; 32], AuthorityTrustError> {
    let mut candidate = record.candidate.clone();
    // The canonical proof signs this exact lease field. Zero only the output
    // position to avoid a circular hash; all other original lease/owner fields
    // and the actual process identities remain in the commitment.
    candidate.authority_lease.binding.payload_sha256 = [0; 32];
    Ok(Sha256::digest(
        serde_json::to_vec(&(
            "hepta.original-checkpoint.activation.v1",
            &candidate,
            &record.previous_token,
            &record.material_cut_sha256,
            &record.root,
            &record.peer,
        ))
        .map_err(unavailable)?,
    )
    .into())
}

fn validate_record(
    record: &ActivationRecord,
    previous: &CognitiveCheckpointReceipt,
) -> Result<(), AuthorityTrustError> {
    let old = &previous.head;
    let candidate = &record.candidate;
    let registered = HostCognitiveCheckpointRegistration {
        owner_agent_id: old.owner_agent_id.clone(),
        publisher_epoch: old.publisher_epoch,
        writer_binding: old.writer_binding.clone(),
        peer_lifetime: old.peer_lifetime.clone(),
    };
    validate_registration(&registered)?;
    validate_head(&registered, old)?;
    candidate.validate().map_err(|_| invalid())?;
    candidate
        .authority_lease
        .validate()
        .map_err(|_| invalid())?;
    if record.schema_version != 1
        || record.previous_token != previous.token
        || token_for(old)? != previous.token
        || record.root.uid != 0
        || record.root.pid == 0
        || record.root.process_start_ticks == 0
        || record.root.boot_id != record.peer.boot_id
        || record.peer.uid != old.peer_lifetime.uid
        || record.peer.uid == 0
        || record.peer.pid == 0
        || record.peer.pid > i32::MAX as u32
        || record.peer.process_start_ticks == 0
        || record.peer == old.peer_lifetime
        || candidate.registered_agent_id != old.owner_agent_id
        || candidate.local_lease_id != old.writer_binding.lease_id
        || old.writer_binding.generation.checked_add(1) != Some(candidate.local_lease_generation)
        || candidate.owner_epoch <= old.writer_binding.owner_epoch
        || candidate.authority_lease.authority_epoch != old.writer_binding.authority_epoch
        || candidate.authority_lease.binding.payload_sha256 != payload_commitment(record)?
    {
        return Err(invalid());
    }
    Ok(())
}

impl RetainedCheckpointActivation {
    pub(super) fn peer(&self) -> &CognitiveCheckpointPeerLifetime {
        &self.record.peer
    }
    pub(super) fn verify_durable(&self) -> Result<(), AuthorityTrustError> {
        self.stored.verify_durable()
    }
    pub(super) fn matches_replacement(
        &self,
        previous: &CognitiveCheckpointReceipt,
        candidate: &crate::HostAuthorityWriterRegistration,
    ) -> Result<(), AuthorityTrustError> {
        if self.record.candidate != *candidate {
            return Err(invalid());
        }
        validate_record(&self.record, previous)?;
        self.verify_durable()
    }
}

impl HostCognitiveCheckpoint {
    /// Before original lease publication/signing, bind the candidate's existing
    /// payload field to the actual retained publisher and full original cut.
    /// Return only after complete witness file/directory durability/readback.
    /// An existing unequal candidate record is never replaced.
    pub(crate) fn prepare_activation_for_root(
        directory: Arc<RootAuthorityDirectory>,
        clock: &HostAuthorityClock,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &RetiredCheckpointPublisher,
        successor: &RetainedCheckpointPublisher,
        material: &VerifiedCognitiveMaterial,
        candidate: crate::HostAuthorityWriterRegistration,
    ) -> Result<crate::HostAuthorityWriterRegistration, AuthorityTrustError> {
        let root =
            crate::HostAuthorityService::current_root_lifetime_for_admin().map_err(unavailable)?;
        let observed = clock.refresh_projection()?;
        if observed.projection.boot_id != root.boot_id
            || successor.lifetime.boot_id != root.boot_id
            || material.anchor() != &previous.head.last_current
        {
            return Err(invalid());
        }
        let mut record = ActivationRecord {
            schema_version: 1,
            previous_token: previous.token.clone(),
            material_cut_sha256: cut_digest(material)?,
            root: root.clone(),
            peer: successor.lifetime.clone(),
            candidate,
        };
        record.candidate.authority_lease.binding.payload_sha256 = payload_commitment(&record)?;
        validate_record(&record, previous)?;
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            directory.clone(),
            STORE_OWNER.into(),
        )?;
        let stored = store.with_locked_durable(STORE_OWNER, |actual| {
            if actual != &previous.head {
                return Err(AuthorityTrustError::Conflict);
            }
            predecessor.require_physical_successor(previous, &successor.lifetime)?;
            successor.require_alive()?;
            material.verify_unchanged().map_err(unavailable)?;
            let stored = directory.save_observation(
                &candidate_name(&record.candidate)?,
                &serde_json::to_vec(&record).map_err(unavailable)?,
            )?;
            material.verify_unchanged().map_err(unavailable)?;
            predecessor.require_retired()?;
            successor.require_alive()?;
            Ok::<_, AuthorityTrustError>(stored)
        })??;
        stored.verify_durable()?;
        if crate::HostAuthorityService::current_root_lifetime_for_admin().map_err(unavailable)?
            != root
        {
            return Err(AuthorityTrustError::Unavailable);
        }
        successor.require_alive()?;
        Ok(record.candidate)
    }

    /// Select only the original issuer's actual verified canonical candidate.
    /// A saved unsigned candidate alone cannot construct this retirement.
    pub(crate) fn observe_unactivated_publisher_for_root(
        directory: Arc<RootAuthorityDirectory>,
        issuer: &crate::DeploymentFinalUseIssuer,
        clock: &HostAuthorityClock,
        previous: &CognitiveCheckpointReceipt,
        material: &VerifiedCognitiveMaterial,
    ) -> Result<RetiredCheckpointPublisher, AuthorityTrustError> {
        let root =
            crate::HostAuthorityService::current_root_lifetime_for_admin().map_err(unavailable)?;
        let projected = clock.refresh_projection()?;
        if projected.projection.boot_id != root.boot_id
            || material.anchor() != &previous.head.last_current
        {
            return Err(invalid());
        }
        let canonical = issuer
            .retained_writer_state_for_root()
            .map_err(unavailable)?;
        let stored = directory.open_observation(&candidate_name(&canonical.registration)?)?;
        let record: ActivationRecord =
            serde_json::from_slice(stored.payload()).map_err(|_| invalid())?;
        validate_record(&record, previous)?;
        if record.candidate != canonical.registration
            || record.material_cut_sha256 != cut_digest(material)?
        {
            return Err(invalid());
        }
        let prepared = RetainedCheckpointActivation { record, stored };
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            directory,
            STORE_OWNER.into(),
        )?;
        let retired = store.with_locked_durable(STORE_OWNER, |actual| {
            if actual != &previous.head {
                return Err(AuthorityTrustError::Conflict);
            }
            material.verify_unchanged().map_err(unavailable)?;
            prepared.verify_durable()?;
            let retired = if prepared.peer().boot_id == root.boot_id {
                RetiredCheckpointPublisher::observe(prepared.peer().clone())?
            } else {
                RetiredCheckpointPublisher::from_prior_boot_activation(root.clone(), prepared)?
            };
            retired.require_retired()?;
            Ok::<_, AuthorityTrustError>(retired)
        })??;
        if issuer
            .retained_writer_state_for_root()
            .map_err(unavailable)?
            != canonical
            || crate::HostAuthorityService::current_root_lifetime_for_admin()
                .map_err(unavailable)?
                != root
        {
            return Err(AuthorityTrustError::Unavailable);
        }
        material.verify_unchanged().map_err(unavailable)?;
        retired.require_retired()?;
        Ok(retired)
    }
}
