//! Same original Root objects across writer, Current and Notes policy CAS.
use super::*;
use crate::RetainedCheckpointPublisher;
use crate::authority_host_checkpoint::RetiredCurrentRecovery;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::deployment_issuer::NotesRecoveryPolicyCheck;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::NotesTargetIdentity;

/// Exact trusted-launcher predecessor inputs. No Deserialize implementation:
/// an ordinary request or a current local database is never recovery evidence.
/// Capture checks the receipt against the original protected store before any
/// mutation and verifies the old signed proof under the existing issuer key.
pub struct HostNotesRecoveryPredecessor {
    pub writer: HostAuthorityWriterRegistration,
    pub writer_proof: HostSignedWriterAuthorizationV1,
    pub checkpoint: CognitiveCheckpointReceipt,
    pub notes_target: NotesTargetIdentity,
    pub notes_lifetime_ms: u64,
}

pub(crate) struct RetainedNotesRecovery {
    service: HostAuthorityService,
    previous: HostNotesRecoveryPredecessor,
    successor_writer: HostAuthorityWriterRegistration,
    publisher_epoch: u64,
    peer: CognitiveCheckpointPeerLifetime,
    successor: RetainedCheckpointPublisher,
    current: RetiredCurrentRecovery,
    policy: Option<NotesRecoveryPolicyCheck>,
    ready: bool,
}

impl RetainedNotesRecovery {
    pub(crate) fn capture(
        mut service: HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        previous: HostNotesRecoveryPredecessor,
    ) -> io::Result<Self> {
        previous.notes_target.validate().map_err(io::Error::other)?;
        previous.writer.validate()?;
        let successor_writer = config.writer.clone().ok_or_else(|| {
            io::Error::other("recovery requires the original successor writer registration")
        })?;
        successor_writer.validate()?;
        if previous.notes_lifetime_ms == 0
            || previous.writer.registered_agent_id != service.identity.agent_id
            || successor_writer.registered_agent_id != service.identity.agent_id
            || successor_writer.spawn_generation != service.identity.spawn_generation
            || previous.checkpoint.head.publisher_epoch.checked_add(1)
                != Some(registration.publisher_epoch)
            || previous.checkpoint.head.counter.checked_add(1).is_none()
            || previous.checkpoint.head.peer_lifetime.uid != config.peer_uid
            || previous.checkpoint.head.peer_lifetime.boot_id != registration.boot_id
            || (previous.checkpoint.head.peer_lifetime.pid == registration.peer_pid
                && previous.checkpoint.head.peer_lifetime.process_start_ticks
                    == registration.process_start_ticks)
        {
            return Err(io::Error::other(
                "exact original Notes predecessor and successor required",
            ));
        }
        if crate::authority_host_runtime::validate_runtime_lanes(config)?.len() != 5 {
            return Err(io::Error::other(
                "all five original authority lanes required",
            ));
        }
        let directory = config
            .checkpoint_state_dir
            .as_ref()
            .filter(|path| path.starts_with(&config.state_dir) && *path != &config.state_dir)
            .ok_or_else(|| {
                io::Error::other("existing private protected Current directory required")
            })?;
        let registry = service
            .root_registry
            .as_ref()
            .ok_or_else(|| io::Error::other("retained original Root Registry required"))?;
        successor_writer.with_live(&registry.verifier(), |_| Ok(()))?;
        let old_registration = super::super::checkpoint::registration_from_proof(
            &service.issuer,
            &previous.writer,
            &previous.writer_proof,
            previous.checkpoint.head.publisher_epoch,
            previous.checkpoint.head.peer_lifetime.clone(),
        )?;
        let current = RetiredCurrentRecovery::capture(
            codex_hepta_contracts::RootAuthorityDirectory::open(directory)
                .map_err(io::Error::other)?,
            previous.checkpoint.clone(),
            old_registration,
            service.clock.clone(),
        )
        .map_err(io::Error::other)?;
        let peer = CognitiveCheckpointPeerLifetime {
            uid: config.peer_uid,
            pid: registration.peer_pid,
            boot_id: registration.boot_id.clone(),
            process_start_ticks: registration.process_start_ticks,
        };
        let successor =
            RetainedCheckpointPublisher::capture(peer.clone()).map_err(io::Error::other)?;
        // Both external frontiers must already exist. Opening this retained
        // service never initializes a namespace or changes a consumer owner.
        service.consumers = Some(RegisteredConsumers::open(
            &config.state_dir,
            config
                .consumers
                .as_ref()
                .ok_or_else(|| io::Error::other("both original consumer namespaces required"))?,
            &service.issuer.trust_key()?.key_id,
            service.clock.clone(),
            successor_writer.authority_lease.expires_at_unix_ms,
        )?);
        Ok(Self {
            service,
            previous,
            successor_writer,
            publisher_epoch: registration.publisher_epoch,
            peer,
            successor,
            current,
            policy: None,
            ready: false,
        })
    }

    pub(crate) fn previous_target(&self) -> &NotesTargetIdentity {
        &self.previous.notes_target
    }

    /// The same object and actual Session reservation must survive any error.
    /// Each original CAS reconciles only these exact retained inputs; no retry
    /// selects another generation, rereads a new predecessor or resets state.
    pub(crate) fn advance(
        &mut self,
        target: &NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<()> {
        self.ready = false;
        target.validate().map_err(io::Error::other)?;
        if target == &self.previous.notes_target || lifetime_ms == 0 {
            return Err(io::Error::other(
                "distinct actual successor Notes target required",
            ));
        }
        if let Some(checked) = &self.policy {
            self.service.issuer.recheck_notes_recovery_policy(
                checked,
                &self.successor_writer,
                target,
                lifetime_ms,
            )?;
        } else {
            self.policy = Some(self.service.issuer.prepare_notes_recovery_policy(
                &self.successor_writer,
                &self.previous.notes_target,
                self.previous.notes_lifetime_ms,
                target,
                lifetime_ms,
            )?);
        }
        let registry = self
            .service
            .root_registry
            .as_ref()
            .ok_or_else(|| io::Error::other("retained original Root Registry required"))?;
        let proof = self.service.issuer.rotate_writer_authorization(
            &self.previous.writer,
            &self.previous.writer_proof,
            &self.successor_writer,
        )?;
        let writer = RegisteredWriter::open(
            &self.service.issuer,
            &self.service.identity,
            self.successor_writer.clone(),
            registry.verifier(),
        )?;
        if writer.proof != proof {
            return Err(io::Error::other("original successor proof changed"));
        }
        let registration = writer.checkpoint_registration(
            &self.service.issuer,
            self.publisher_epoch,
            self.peer.clone(),
        )?;
        let checkpoint = writer.registration.with_live(&writer.leases, |_| {
            if self
                .service
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != proof
            {
                return Err(io::Error::other("original successor proof changed"));
            }
            let checkpoint = RegisteredCheckpoint::adopt_or_reconcile(
                &self.current,
                registration,
                &self.successor,
            )?;
            if self
                .service
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != proof
            {
                return Err(io::Error::other(
                    "original successor proof changed after Current CAS",
                ));
            }
            Ok(checkpoint)
        })?;
        let head = checkpoint
            .backend
            .current_for_handoff()
            .map_err(io::Error::other)?;
        // This original API acquires the same canonical writer dispatch fence.
        // Do not nest it inside with_live and re-enter the Registry owner lock.
        self.service.issuer.replace_registered_notes_policy(
            &writer.registration,
            &self.previous.notes_target,
            self.previous.notes_lifetime_ms,
            target,
            lifetime_ms,
        )?;
        let notes = crate::RootNotesGrantAdmission::from_registered_notes(
            &self.service.issuer,
            Arc::clone(registry),
            writer.registration.clone(),
            target,
            lifetime_ms,
        )?;
        if checkpoint
            .backend
            .current_for_handoff()
            .map_err(io::Error::other)?
            != head
        {
            return Err(io::Error::other(
                "protected Current changed during Notes policy CAS",
            ));
        }
        self.service.writer = Some(writer);
        self.service.checkpoint = Some(checkpoint);
        self.service.notes = Some(notes);
        self.ready = true;
        Ok(())
    }

    pub(crate) fn into_service(self) -> io::Result<HostAuthorityService> {
        if !self.ready {
            return Err(io::Error::other(
                "original Notes recovery has no reconciled result",
            ));
        }
        Ok(self.service)
    }
}
