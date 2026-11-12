//! Private custody for retiring only this actual Root serving scope.
//! Wire data cannot mint this owner, a joined handle, a C result or a lease.

use super::*;
use std::sync::Mutex;
use std::sync::MutexGuard;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentAcknowledgement;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentBinding;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentRequest;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentStage;
use crate::same_actor_q24_phase_gate::SameActorPhaseStream;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementAcknowledgement;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementRequest;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementStage;
use crate::same_actor_q24_root_retirement_protocol::RETIREMENT_PURPOSE;

const ALL_PURPOSES: u16 = 0xff;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum OriginalRootRetirementPurpose {
    Observation,
    Issuer,
    Checkpoint,
    DeviceFrontier,
    NotesFrontier,
    Learning,
    Model,
    Publication,
}

impl OriginalRootRetirementPurpose {
    fn bit(self) -> u16 {
        match self {
            Self::Observation => 1,
            Self::Issuer => 2,
            Self::Checkpoint => 4,
            Self::DeviceFrontier => 8,
            Self::NotesFrontier => 16,
            Self::Learning => 32,
            Self::Model => 64,
            Self::Publication => 128,
        }
    }

    pub(crate) fn from_original_lane(lane: HostAuthorityLane) -> Self {
        match lane {
            HostAuthorityLane::Observation => Self::Observation,
            HostAuthorityLane::Issuer => Self::Issuer,
            HostAuthorityLane::Checkpoint => Self::Checkpoint,
            HostAuthorityLane::DeviceConsumerFrontier => Self::DeviceFrontier,
            HostAuthorityLane::NotesConsumerFrontier => Self::NotesFrontier,
        }
    }
}

struct RetirementState {
    registered: u16,
    active_requests: usize,
    original_current: Option<(String, String)>,
    intent: Option<String>,
    intent_acknowledged: bool,
    clean_eof: u16,
    stop_watcher: bool,
    acknowledged: bool,
}

pub(crate) struct OriginalRootRetirementScope {
    gate: Arc<SameActorPhaseGate>,
    binding: OriginalDeploymentBinding,
    registration: HostAuthorityRegistration,
    uid: u32,
    gid: u32,
    owner: OwnedFd,
    state: Mutex<RetirementState>,
}

pub(crate) struct OriginalRootRetirementLane {
    scope: Arc<OriginalRootRetirementScope>,
    purpose: OriginalRootRetirementPurpose,
    closing: CloseSameActorPhaseOnDrop,
}

pub(crate) struct OriginalRootRequestAdmission {
    scope: Arc<OriginalRootRetirementScope>,
}

/// Retains the actual channel/pidfd and shutdown alias after its exact clean
/// EOF. This is not a join witness: the owner scope must still join its thread.
pub(crate) struct OriginalRootRetiredChannel {
    scope: Arc<OriginalRootRetirementScope>,
    purpose: OriginalRootRetirementPurpose,
    channel: HostAuthorityPeerChannel,
    _stream: SameActorPhaseStream,
    _closing: CloseSameActorPhaseOnDrop,
}

impl OriginalRootRetirementScope {
    pub(super) fn from_original_phase(
        phase: &PreparedRootSameActorQ24PhaseV1,
    ) -> io::Result<Arc<Self>> {
        crate::authority_host_service::generation_initial::original_root()?;
        phase.gate.require_open()?;
        let binding = OriginalDeploymentBinding::from_original_phase(&phase.descriptor)?;
        let scope = Arc::new(Self {
            gate: Arc::clone(&phase.gate),
            binding,
            registration: phase.original.registration.clone(),
            uid: phase.original.config.peer_uid,
            gid: phase.original.config.peer_gid,
            owner: phase.original.owner_pidfd.try_clone()?,
            state: Mutex::new(RetirementState {
                registered: 0,
                active_requests: 0,
                original_current: None,
                intent: None,
                intent_acknowledged: false,
                clean_eof: 0,
                stop_watcher: false,
                acknowledged: false,
            }),
        });
        scope.require_original(&phase.gate)?;
        Ok(scope)
    }

    pub(crate) fn gate(&self) -> &Arc<SameActorPhaseGate> {
        &self.gate
    }

    fn state(&self) -> io::Result<MutexGuard<'_, RetirementState>> {
        self.state.lock().map_err(|_| {
            self.gate.close();
            io::Error::other("original Root retirement state poisoned")
        })
    }

    pub(crate) fn require_original(&self, gate: &Arc<SameActorPhaseGate>) -> io::Result<()> {
        if !Arc::ptr_eq(&self.gate, gate) {
            self.gate.close();
            return Err(io::Error::other("Root retirement replaced its original phase gate"));
        }
        let checked = (|| {
            self.gate.require_open()?;
            verify_pinned_process(
                &self.registration,
                self.uid,
                self.gid,
                &self.owner,
                self.gate.deadline().instant(),
            )?;
            self.gate.require_open()?;
            Ok(())
        })();
        if checked.is_err() {
            self.gate.close();
        }
        checked
    }

    pub(crate) fn register_original_lane(
        self: &Arc<Self>,
        purpose: OriginalRootRetirementPurpose,
        gate: &Arc<SameActorPhaseGate>,
    ) -> io::Result<OriginalRootRetirementLane> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.require_original(gate)?;
        let mut state = self.state()?;
        let bit = purpose.bit();
        if state.intent.is_some() || state.registered & bit != 0 {
            return Err(io::Error::other("original Root retirement lane reused or too late"));
        }
        state.registered |= bit;
        drop(state);
        self.require_original(gate)?;
        closing.disarm();
        Ok(OriginalRootRetirementLane {
            scope: Arc::clone(self),
            purpose,
            closing: CloseSameActorPhaseOnDrop::new(gate),
        })
    }

    pub(super) fn retain_original_current(
        &self,
        request: &OriginalDeploymentRequest,
        acknowledgement: &OriginalDeploymentAcknowledgement,
    ) -> io::Result<()> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.require_original(&self.gate)?;
        request.require_original_stage(&self.binding, OriginalDeploymentStage::Current)?;
        acknowledgement.require_original_request(request)?;
        let binding = acknowledgement.registration_binding.clone()
            .ok_or_else(|| io::Error::other("actual Root CURRENT registration missing"))?;
        let mut state = self.state()?;
        if state.original_current.is_some() || state.intent.is_some() {
            return Err(io::Error::other("Root retirement CURRENT registration reused"));
        }
        state.original_current = Some((binding, acknowledgement.original_request.clone()));
        drop(state);
        self.require_original(&self.gate)?;
        closing.disarm();
        Ok(())
    }

    pub(super) fn authorize_original_retirement(
        &self,
        request: &OriginalRootRetirementRequest,
    ) -> io::Result<Vec<u8>> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.require_original(&self.gate)?;
        let mut state = self.state()?;
        let (registration, current_request) = state.original_current.as_ref()
            .ok_or_else(|| io::Error::other("Root retirement requires its actual CURRENT registration"))?;
        request.require_original(
            &self.binding,
            registration,
            current_request,
            OriginalRootRetirementStage::AuthorizeRootRetirement,
            None,
        )?;
        if state.intent.is_some()
            || state.registered != ALL_PURPOSES
            || state.clean_eof != 0
            || state.active_requests != 0
        {
            return Err(io::Error::other("original Root retirement is busy, incomplete, or consumed"));
        }
        // This mutex is also the request-admission cut. No later original
        // effect or response exchange can enter after this one-shot intent.
        let intent = request.digest()?;
        state.intent = Some(intent.clone());
        drop(state);
        self.require_original(&self.gate)?;
        let response = retirement_response(request, &intent)?;
        closing.disarm();
        Ok(response)
    }

    pub(super) fn acknowledge_original_intent(&self) -> io::Result<()> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.require_original(&self.gate)?;
        let mut state = self.state()?;
        if state.intent.is_none() || state.intent_acknowledged {
            return Err(io::Error::other("original Root retirement intent ACK reused"));
        }
        state.intent_acknowledged = true;
        drop(state);
        self.require_original(&self.gate)?;
        self.gate.notify_original_waiters();
        closing.disarm();
        Ok(())
    }

    pub(super) fn require_original_intent(
        &self,
        request: &OriginalRootRetirementRequest,
    ) -> io::Result<String> {
        self.require_original(&self.gate)?;
        let state = self.state()?;
        let intent = state.intent.as_ref()
            .ok_or_else(|| io::Error::other("original Root retirement intent missing"))?;
        let (registration, current_request) = state.original_current.as_ref()
            .ok_or_else(|| io::Error::other("actual original CURRENT registration missing"))?;
        request.require_original(
            &self.binding,
            registration,
            current_request,
            OriginalRootRetirementStage::ObserveRootWorkersJoined,
            Some(intent),
        )?;
        if !state.intent_acknowledged || state.acknowledged {
            return Err(io::Error::other("original Root retirement ACK state differs"));
        }
        Ok(intent.clone())
    }

    pub(super) fn stop_original_deadline_worker(
        &self,
        joined: &super::deployment::OriginalRootDeploymentJoined,
    ) -> io::Result<()> {
        joined.require_original(self)?;
        loop {
            let epoch = self.gate.original_wait_epoch()?;
            self.require_original(&self.gate)?;
            let mut state = self.state()?;
            if state.active_requests != 0 || state.clean_eof != ALL_PURPOSES {
                return Err(io::Error::other("original Root business lanes have not retired"));
            }
            if state.intent_acknowledged {
                if state.stop_watcher {
                    return Err(io::Error::other("original Root deadline worker already released"));
                }
                state.stop_watcher = true;
                drop(state);
                self.gate.notify_original_waiters();
                return self.require_original(&self.gate);
            }
            drop(state);
            self.gate.wait_original_change(epoch)?;
        }
    }

    pub(super) fn watch_original_deadline(&self) -> io::Result<()> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        loop {
            let epoch = self.gate.original_wait_epoch()?;
            self.require_original(&self.gate)?;
            if self.state()?.stop_watcher {
                self.require_original(&self.gate)?;
                closing.disarm();
                return Ok(());
            }
            self.gate.wait_original_change(epoch)?;
        }
    }

    pub(super) fn acknowledge_original_workers(
        &self,
        request: &OriginalRootRetirementRequest,
        joined: &super::deployment::OriginalRootAllWorkersJoined,
    ) -> io::Result<Vec<u8>> {
        joined.require_original(self)?;
        let intent = self.require_original_intent(request)?;
        let state = self.state()?;
        if !state.stop_watcher || state.clean_eof != ALL_PURPOSES || state.active_requests != 0 {
            return Err(io::Error::other("original Root worker scope is not joined"));
        }
        drop(state);
        retirement_response(request, &intent)
    }

    pub(super) fn mark_original_workers_acknowledged(
        &self,
        joined: &super::deployment::OriginalRootAllWorkersJoined,
    ) -> io::Result<()> {
        joined.require_original(self)?;
        self.require_original(&self.gate)?;
        let mut state = self.state()?;
        if !state.stop_watcher || !state.intent_acknowledged || state.acknowledged {
            return Err(io::Error::other("original Root workers ACK reused or incomplete"));
        }
        state.acknowledged = true;
        drop(state);
        self.require_original(&self.gate)
    }
}

impl OriginalRootRetirementLane {
    /// Kept by the actual channel owner until the original framed ACK finishes.
    /// Root retirement never waits for this count inside its 500 ms request.
    pub(crate) fn enter_original_request(&self) -> io::Result<OriginalRootRequestAdmission> {
        self.scope.require_original(&self.scope.gate)?;
        let mut state = self.scope.state()?;
        if state.intent.is_some() || state.clean_eof & self.purpose.bit() != 0 {
            return Err(io::Error::other("original Root lane is retiring"));
        }
        state.active_requests = state.active_requests.checked_add(1)
            .ok_or_else(|| io::Error::other("original Root request count overflow"))?;
        Ok(OriginalRootRequestAdmission { scope: Arc::clone(&self.scope) })
    }

    /// Called only after the original peer channel returned Ok(false). Every
    /// framing/handler/ACK error remains an error in that actual caller.
    pub(crate) fn accept_original_clean_eof(
        mut self,
        channel: HostAuthorityPeerChannel,
        stream: SameActorPhaseStream,
    ) -> io::Result<OriginalRootRetiredChannel> {
        self.scope.require_original(&self.scope.gate)?;
        HostAuthorityPeerChannel::check_peer_lifetime(&channel).map_err(io::Error::other)?;
        let mut state = self.scope.state()?;
        let bit = self.purpose.bit();
        if state.intent.is_none() || state.clean_eof & bit != 0 {
            return Err(io::Error::other("required original Root lane ended without its retirement"));
        }
        state.clean_eof |= bit;
        drop(state);
        self.scope.require_original(&self.scope.gate)?;
        self.closing.disarm();
        Ok(OriginalRootRetiredChannel {
            scope: Arc::clone(&self.scope),
            purpose: self.purpose,
            channel,
            _stream: stream,
            _closing: CloseSameActorPhaseOnDrop::new(&self.scope.gate),
        })
    }
}

impl OriginalRootRetiredChannel {
    pub(crate) fn require_original(
        &self,
        scope: &OriginalRootRetirementScope,
        purpose: OriginalRootRetirementPurpose,
    ) -> io::Result<()> {
        if !std::ptr::eq(self.scope.as_ref(), scope) || self.purpose != purpose {
            self.scope.gate.close();
            return Err(io::Error::other("original Root retired channel origin differs"));
        }
        self.scope.require_original(&self.scope.gate)?;
        HostAuthorityPeerChannel::check_peer_lifetime(&self.channel).map_err(io::Error::other)?;
        let state = self.scope.state()?;
        if state.intent.is_none() || state.clean_eof & purpose.bit() == 0 {
            return Err(io::Error::other("actual original Root clean EOF is missing"));
        }
        Ok(())
    }
}

impl Drop for OriginalRootRequestAdmission {
    fn drop(&mut self) {
        let outcome = self.scope.state().and_then(|mut state| {
            state.active_requests = state.active_requests.checked_sub(1)
                .ok_or_else(|| io::Error::other("original Root request custody underflow"))?;
            Ok(())
        });
        if outcome.is_err() {
            self.scope.gate.close();
        }
        self.scope.gate.notify_original_waiters();
    }
}

impl Drop for OriginalRootRetirementScope {
    fn drop(&mut self) {
        self.gate.close();
    }
}

fn retirement_response(
    request: &OriginalRootRetirementRequest,
    intent: &str,
) -> io::Result<Vec<u8>> {
    OriginalRootRetirementAcknowledgement {
        schema_version: 1,
        purpose: RETIREMENT_PURPOSE.into(),
        binding: request.binding.clone(),
        sequence: request.sequence,
        stage: request.stage,
        original_request: request.digest()?,
        original_intent: intent.into(),
    }
    .encode_original(request, intent)
}
