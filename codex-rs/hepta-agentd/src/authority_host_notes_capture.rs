//! Historical observation of the same stopped Root service. Issuer, Registry
//! and checkpoint state are unchanged; the original clock may persist its time.
use super::*;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;

impl HostAuthorityService {
    pub(crate) fn require_notes_capture(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
    ) -> io::Result<()> {
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original registered Notes writer required"))?;
        if config.writer.as_ref() != Some(&writer.registration)
            || registration.registered_identity.identity()? != self.identity
            || self
                .notes
                .as_ref()
                .is_none_or(|notes| !writer.matches_notes(notes))
            || self.root_registry.is_none()
            || self.checkpoint.is_none()
            || self.consumers.is_none()
            || crate::authority_host_runtime::validate_runtime_lanes(config)?.len() != 5
        {
            return Err(io::Error::other(
                "same original five-lane Notes service required",
            ));
        }
        Ok(())
    }

    pub(crate) fn capture_notes_predecessor(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
    ) -> io::Result<HostNotesRecoveryPredecessor> {
        self.require_notes_capture(config, registration)?;
        let (Some(writer), Some(registry), Some(notes), Some(checkpoint)) = (
            &self.writer,
            &self.root_registry,
            &self.notes,
            &self.checkpoint,
        ) else {
            return Err(io::Error::other(
                "original Notes capture owners unavailable",
            ));
        };
        let checkpoint = &checkpoint.backend;
        let lease = &writer.registration.authority_lease;
        // Read only this exact retained Registry. Missing/pruned/replaced leases
        // are refused by this narrow capture, never inferred from a timestamp.
        let frontier = registry.frontier().map_err(io::Error::other)?;
        if registry
            .read_lease(&lease.lease_id)
            .map_err(io::Error::other)?
            .is_none_or(|actual| actual.lease != *lease)
            || self.clock.now_unix_ms().map_err(io::Error::other)? < lease.expires_at_unix_ms
        {
            return Err(io::Error::other(
                "exact expired original writer lease required",
            ));
        }
        let original =
            notes.inspect_retired(&self.issuer, registry, &writer.registration, &writer.proof)?;
        let expected = writer.checkpoint_registration(
            &self.issuer,
            registration.publisher_epoch,
            CognitiveCheckpointPeerLifetime {
                uid: config.peer_uid,
                pid: registration.peer_pid,
                boot_id: registration.boot_id.clone(),
                process_start_ticks: registration.process_start_ticks,
            },
        )?;
        let current = checkpoint
            .current_for_retired_capture(&expected)
            .map_err(io::Error::other)?;
        // The historical issuer check releases its request lock before any
        // Registry read, preserving the original Registry -> issuer lock order.
        if notes.inspect_retired(&self.issuer, registry, &writer.registration, &writer.proof)?
            != original
            || checkpoint
                .current_for_retired_capture(&expected)
                .map_err(io::Error::other)?
                != current
            || registry.frontier().map_err(io::Error::other)? != frontier
            || self.clock.now_unix_ms().map_err(io::Error::other)? < lease.expires_at_unix_ms
        {
            return Err(io::Error::other(
                "original Notes predecessor changed during capture",
            ));
        }
        Ok(HostNotesRecoveryPredecessor {
            writer: writer.registration.clone(),
            writer_proof: writer.proof.clone(),
            checkpoint: current,
            notes_target: original.target,
            notes_lifetime_ms: original.lifetime_ms,
        })
    }
}
