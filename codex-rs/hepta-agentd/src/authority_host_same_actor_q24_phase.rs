//! Explicit same-session, same-actor phase mode. Existing default startup
//! constructors and serving paths retain their behavior.
//!
//! This mode never authorizes a different agent, cell, principal, process or
//! spawn. It does not implement an independent consumer or cold recovery.

use super::*;
use std::sync::Arc;

use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use crate::same_actor_q24_phase_protocol::CONTROL_SOCKET;
use crate::same_actor_q24_phase_protocol::OriginalPhaseBootstrap;
use crate::same_actor_q24_phase_protocol::START_PURPOSE;
use crate::same_actor_q24_phase_record::OriginalPhaseRecord;
use crate::same_actor_q24_phase_record::PhaseIdentity;
use codex_hepta_contracts::RootAuthorityDirectory;

#[path = "authority_host_same_actor_q24_scope_cap.rs"]
mod scope_cap;
pub use scope_cap::RootSameActorScopeEnrollmentCapabilityV1;
pub use scope_cap::RootSameActorScopedEnrollmentV1;

#[path = "authority_host_same_actor_q24_phase_worker.rs"]
mod worker;

#[path = "authority_host_same_actor_q24_host.rs"]
mod host;
pub use host::RootSameActorHostAcknowledgementV1;
pub use host::RootSameActorHostCommandV1;
pub use host::RootSameActorHostInputsV1;

pub struct RootSameActorPhaseStartV1 {
    pub initial_capability: generation_initial::RootSameActorInitialEnrollmentCapabilityV1,
    pub initial_offer: crate::RootGenerationInitialOfferV1,
    pub phase_offer: crate::root_production_handoff::same_actor_phase::RootSameActorPhaseOfferV1,
    pub scope_capability: RootSameActorScopeEnrollmentCapabilityV1,
}

/// The only phase constructor captures both Root-local absolute limits before
/// opening any original service or publishing A. Every phase worker receives
/// these same values. A later enable, owner arrival or ACK cannot restart them.
pub struct PreparedRootSameActorQ24PhaseV1 {
    original: PreparedHostAuthoritySession,
    gate: Arc<SameActorPhaseGate>,
    record: OriginalPhaseRecord,
    descriptor: OriginalPhaseBootstrap,
    model: crate::HostAuthorityQ24ModelFactoryReservationV1,
    scope: scope_cap::ScopeRuntime,
    start: Option<RootSameActorPhaseStartV1>,
    closing: CloseSameActorPhaseOnDrop,
}

impl PreparedRootSameActorQ24PhaseV1 {
    pub fn open(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
        current_directory: Arc<RootAuthorityDirectory>,
        initial: crate::HostGenerationInitialDeploymentV1,
        model: crate::HostAuthorityQ24ModelFactoryReservationV1,
    ) -> io::Result<Self> {
        let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
        let deadline = SameActorPhaseDeadline::at_original_service_start(
            std::time::Duration::from_millis(config.lifetime_ms),
        )?;
        let original =
            PreparedHostAuthoritySession::open(config_file, registration_file, owner_pidfd)?;
        Self::capture_original_phase(
            original,
            config,
            deadline,
            current_directory,
            initial,
            model,
        )
    }

    pub async fn prepare_fresh_from_registered(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
        current_directory: Arc<RootAuthorityDirectory>,
        initial: crate::HostGenerationInitialDeploymentV1,
        model: crate::HostAuthorityQ24ModelFactoryReservationV1,
    ) -> io::Result<Self> {
        let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
        let deadline = SameActorPhaseDeadline::at_original_service_start(
            std::time::Duration::from_millis(config.lifetime_ms),
        )?;
        let original = PreparedHostAuthoritySession::prepare_fresh_from_registered(
            config_file,
            registration_file,
            owner_pidfd,
        )
        .await?;
        Self::capture_original_phase(
            original,
            config,
            deadline,
            current_directory,
            initial,
            model,
        )
    }

    fn capture_original_phase(
        mut original: PreparedHostAuthoritySession,
        config: HostAuthorityServiceConfig,
        deadline: SameActorPhaseDeadline,
        current_directory: Arc<RootAuthorityDirectory>,
        initial: crate::HostGenerationInitialDeploymentV1,
        model: crate::HostAuthorityQ24ModelFactoryReservationV1,
    ) -> io::Result<Self> {
        let gate = SameActorPhaseGate::from_original_deadline(deadline)?;
        let mut closing = CloseSameActorPhaseOnDrop::new(&gate);
        if serde_json::to_vec(&config).map_err(io::Error::other)?
            != serde_json::to_vec(&original.config).map_err(io::Error::other)?
            || original.learning.is_some()
            || original.publication.is_some()
            || original.initial_publication.is_some()
            || original.root_admin.is_some()
            || original.config.sockets.device_frontier.is_none()
            || original.config.sockets.notes_frontier.is_none()
        {
            return Err(io::Error::other(
                "same-actor phase requires the unchanged original startup",
            ));
        }
        gate.require_open()?;
        original
            .service
            .bind_original_same_actor_phase_issuer(&gate)?;
        let (initial_capability, initial_offer) =
            original.enable_generation_initial(initial.clone())?;
        let mut retained = None;
        original.service.with_initial_publication_context(
            &original.config,
            &original.registration,
            &original.owner_pidfd,
            |proof| {
                gate.require_open()?;
                let phase_identity = PhaseIdentity {
                    root: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                        uid: 0,
                        pid: std::process::id(),
                        boot_id: original.registration.boot_id.clone(),
                        process_start_ticks: phase_root_start()?,
                    },
                    consumer: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                        uid: original.config.peer_uid,
                        pid: original.registration.peer_pid,
                        boot_id: original.registration.boot_id.clone(),
                        process_start_ticks: original.registration.process_start_ticks,
                    },
                    identity: crate::neuron_generation_process_identity_digest_v1(
                        &original.registration.registered_identity.identity()?,
                    )
                    .map_err(io::Error::other)?
                    .to_string(),
                    writer: proof,
                    initial: initial.clone(),
                    model_reservation: serde_json::to_string(&model).map_err(io::Error::other)?,
                    root_end_boottime_ns: deadline.boottime_ns(),
                };
                let record = OriginalPhaseRecord::reserve(
                    Arc::clone(&current_directory),
                    phase_identity.clone(),
                )?;
                let descriptor = OriginalPhaseBootstrap {
                    purpose: START_PURPOSE.into(),
                    phase: record.binding()?,
                    original: phase_identity,
                    control_socket: original
                        .config
                        .sockets
                        .observation
                        .parent()
                        .ok_or_else(|| io::Error::other("original Root listener parent missing"))?
                        .join(CONTROL_SOCKET),
                };
                let encoded = serde_json::to_vec(&descriptor).map_err(io::Error::other)?;
                let sealed = crate::authority_host_bootstrap_seal::seal_bytes(&encoded)?;
                gate.require_open()?;
                retained = Some((record, descriptor, sealed));
                Ok(())
            },
        )?;
        gate.require_open()?;
        let (record, descriptor, sealed) =
            retained.ok_or_else(|| io::Error::other("original phase startup capture missing"))?;
        let (scope, scope_capability) =
            scope_cap::ScopeRuntime::mint(descriptor.original.root.clone(), &gate);
        let start = RootSameActorPhaseStartV1 {
            initial_capability: generation_initial::RootGenerationInitialEnrollmentCapabilityV1::into_same_actor_phase(
                initial_capability, &gate, &current_directory,
            ),
            initial_offer,
            phase_offer: crate::root_production_handoff::same_actor_phase::RootSameActorPhaseOfferV1 {
                bootstrap: sealed,
                gate: Arc::clone(&gate),
                closing: CloseSameActorPhaseOnDrop::new(&gate),
            },
            scope_capability,
        };
        closing.disarm();
        let closing = CloseSameActorPhaseOnDrop::new(&gate);
        Ok(Self {
            original,
            gate,
            record,
            descriptor,
            model,
            scope,
            start: Some(start),
            closing,
        })
    }

    pub fn take_start(&mut self) -> io::Result<RootSameActorPhaseStartV1> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.gate.require_open()?;
        let start = self
            .start
            .take()
            .ok_or_else(|| io::Error::other("original phase start was already consumed"))?;
        closing.disarm();
        Ok(start)
    }

    pub fn seal_bootstrap(&self, consumer_state_root: &Path) -> io::Result<File> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        let _admission = self.gate.enter_original_lane()?;
        let bootstrap = self.original.seal_bootstrap(consumer_state_root)?;
        self.gate.require_open()?;
        closing.disarm();
        Ok(bootstrap)
    }

    pub fn handoff_fresh_agent_filesystem(mut self) -> io::Result<(Self, std::path::PathBuf)> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.gate.require_open()?;
        let (original, parent) = self.original.handoff_fresh_agent_filesystem()?;
        self.original = original;
        self.gate.require_open()?;
        closing.disarm();
        Ok((self, parent))
    }

    pub fn with_original_logind_session(
        mut self,
        profile_file: &Path,
        original_login: OwnedFd,
    ) -> io::Result<Self> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.gate.require_open()?;
        self.original = self
            .original
            .with_original_logind_session(profile_file, original_login)?;
        self.gate.require_open()?;
        closing.disarm();
        Ok(self)
    }

    pub fn with_registered_notes_from_session(
        mut self,
        target: &codex_hepta_memory::NotesTargetIdentity,
        lifetime_ms: u64,
    ) -> io::Result<Self> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.gate.require_open()?;
        self.original = self
            .original
            .with_registered_notes_from_session(target, lifetime_ms)?;
        self.gate.require_open()?;
        closing.disarm();
        Ok(self)
    }

    pub fn serve_with_ready(self, ready: impl FnOnce() -> io::Result<()>) -> io::Result<()> {
        worker::serve_original_phase(self, ready)
    }
}

fn phase_root_start() -> io::Result<u64> {
    std::fs::read_to_string("/proc/self/stat")?
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("actual Root incarnation missing"))
}
