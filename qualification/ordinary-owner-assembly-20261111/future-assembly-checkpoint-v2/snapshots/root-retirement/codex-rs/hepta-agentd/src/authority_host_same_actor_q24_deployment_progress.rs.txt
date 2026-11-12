//! One real non-Root connection for bounded deployment observations.
//! The held original pidfd and SO_PEERCRED authenticate the current process.
//! Root-private approvals remain independent of every byte on this lane.

use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;

use crate::same_actor_q24_deployment_protocol::FRAME_BOUND;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentAcknowledgement;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentBinding;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentRequest;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentStage;
use crate::same_actor_q24_deployment_protocol::original_deployment_socket;

pub(super) struct BoundDeploymentProgress {
    listener: UnixListener,
    path: PathBuf,
    device: u64,
    inode: u64,
    original_registration: HostAuthorityRegistration,
    original_uid: u32,
    original_gid: u32,
    original_owner: OwnedFd,
    original_policy: HostAuthorityPeerPolicy,
    original_binding: OriginalDeploymentBinding,
}

impl BoundDeploymentProgress {
    pub(super) fn bind(phase: &PreparedRootSameActorQ24PhaseV1) -> io::Result<Self> {
        phase.gate.require_open()?;
        let path = original_deployment_socket(&phase.descriptor)?;
        let config = &phase.original.config;
        let mut paths: Vec<_> = validate_runtime_lanes(config)?
            .into_iter().map(|(_, path)| path).collect();
        paths.push(&phase.descriptor.control_socket);
        paths.push(&path);
        validate_lane_paths(&paths, config.peer_gid)?;
        verify_pinned_process(
            &phase.original.registration, config.peer_uid, config.peer_gid,
            &phase.original.owner_pidfd, phase.gate.deadline().instant(),
        )?;
        let binding = OriginalDeploymentBinding::from_original_phase(&phase.descriptor)?;
        let owner = phase.original.owner_pidfd.try_clone()?;
        let listener = UnixListener::bind(&path)?;
        let metadata = std::fs::symlink_metadata(&path)?;
        let bound = Self {
            listener,
            path,
            device: metadata.dev(),
            inode: metadata.ino(),
            original_registration: phase.original.registration.clone(),
            original_uid: config.peer_uid,
            original_gid: config.peer_gid,
            original_owner: owner,
            original_policy: HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: config.peer_uid,
                    pid: phase.original.registration.peer_pid,
                },
                timeout: std::time::Duration::from_millis(config.timeout_ms),
                lifetime: std::time::Duration::from_millis(config.lifetime_ms),
                request_bound: FRAME_BOUND,
                response_bound: FRAME_BOUND,
            },
            original_binding: binding,
        };
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid
            || config.timeout_ms == 0 || config.timeout_ms > 500
        {
            return Err(io::Error::other("original deployment listener custody or timeout differs"));
        }
        std::fs::set_permissions(&bound.path, std::fs::Permissions::from_mode(0o660))?;
        bound.listener.set_nonblocking(true)?;
        phase.gate.require_open()?;
        Ok(bound)
    }

    fn accept_original(
        &self,
        gate: &Arc<SameActorPhaseGate>,
    ) -> io::Result<std::os::unix::net::UnixStream> {
        let end = gate.deadline().instant();
        loop {
            let epoch = gate.original_wait_epoch()?;
            owner_alive(&self.original_owner, end)?;
            match self.listener.accept() {
                Ok((stream, _)) => {
                    verify_pinned_process(
                        &self.original_registration, self.original_uid, self.original_gid,
                        &self.original_owner, end,
                    )?;
                    gate.require_open()?;
                    return Ok(stream);
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    gate.wait_original_change(epoch)?;
                }
                Err(error) => return Err(error),
            }
        }
    }

    pub(super) fn serve_original(
        self,
        files: DeploymentFiles,
        commands: mpsc::SyncSender<RootSameActorHostCommandV1>,
        acknowledgements: mpsc::Receiver<RootSameActorHostAcknowledgementV1>,
        gate: Arc<SameActorPhaseGate>,
    ) -> io::Result<()> {
        let _closing = CloseSameActorPhaseOnDrop::new(&gate);
        files.require_deployment_files()?;
        let stream = self.accept_original(&gate)?;
        let _stream_stop = gate.retain_original_stream(&stream)?;
        let mut channel = HostAuthorityPeerChannel::from_stream_until(
            stream, self.original_policy, self.original_owner.try_clone()?,
            gate.deadline().instant(),
        ).map_err(io::Error::other)?;
        gate.require_open()?;
        for stage in [
            OriginalDeploymentStage::Initial,
            OriginalDeploymentStage::Scoped,
            OriginalDeploymentStage::Current,
        ] {
            let mut original_failure: Option<io::Error> = None;
            let mut dispatched = false;
            let exchanged = HostAuthorityPeerChannel::exchange(&mut channel, |bytes| {
                let result: io::Result<Vec<u8>> = (|| {
                    gate.require_open()?;
                    let request = OriginalDeploymentRequest::decode_original(bytes)?;
                    request.require_original_stage(&self.original_binding, stage)?;
                    files.require_deployment_files()?;
                    let registration = bridge::apply_original_progress(
                        &files, &request, &commands, &acknowledgements, &gate, &mut dispatched,
                    )?;
                    // The actual Root ACK and all retained file post-checks
                    // precede encoding. Framing keeps its original request
                    // deadline; the bridge never creates a replacement budget.
                    gate.require_open()?;
                    OriginalDeploymentAcknowledgement::from_actual_registration(
                        &request, registration,
                    )?.encode_original(&request)
                })();
                match result {
                    Ok(response) => Ok(response),
                    Err(error) => {
                        original_failure = Some(error);
                        Err(HostIssuerTransportError::Unavailable)
                    }
                }
            });
            if let Some(error) = original_failure {
                return Err(error);
            }
            let accepted = exchanged.map_err(|error| {
                let original = io::Error::other(error);
                if dispatched {
                    deployment_uncertain("original deployment response", original)
                } else {
                    original
                }
            })?;
            if !accepted {
                return Err(io::Error::other("original deployment peer closed before its stage"));
            }
            gate.require_open()?;
            HostAuthorityPeerChannel::check_peer_lifetime(&channel).map_err(io::Error::other)?;
        }
        // All three registrations are real, but C and its original owners are
        // still live. Retain this one peer until common closure; a fourth frame
        // is refused. Neither EOF nor this lane's end is a completion witness.
        gate.require_open()?;
        match HostAuthorityPeerChannel::exchange(
            &mut channel, |_| Err(HostIssuerTransportError::InvalidRequest),
        ) {
            Ok(false) => Err(io::Error::other("original deployment peer closed without final owner join")),
            Ok(true) => Err(io::Error::other("original deployment replay unexpectedly returned")),
            Err(error) => Err(io::Error::other(error)),
        }
    }
}

impl Drop for BoundDeploymentProgress {
    fn drop(&mut self) {
        if std::fs::symlink_metadata(&self.path)
            .is_ok_and(|value| value.dev() == self.device && value.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

impl BoundDeploymentProgress {
    pub(super) fn serve_for_original_root_retirement(
        self,
        files: DeploymentFiles,
        commands: mpsc::SyncSender<RootSameActorHostCommandV1>,
        acknowledgements: mpsc::Receiver<RootSameActorHostAcknowledgementV1>,
        retirement: Arc<crate::OriginalRootRetirementScope>,
    ) -> io::Result<OriginalRootRetirementHandoff> {
        let gate = Arc::clone(retirement.gate());
        let mut closing = CloseSameActorPhaseOnDrop::new(&gate);
        retirement.require_original(&gate)?;
        files.require_deployment_files()?;
        let stream = self.accept_original(&gate)?;
        let stream_stop = gate.retain_original_stream(&stream)?;
        let mut channel = HostAuthorityPeerChannel::from_stream_until(
            stream, self.original_policy, self.original_owner.try_clone()?,
            gate.deadline().instant(),
        ).map_err(io::Error::other)?;
        gate.require_open()?;
        for stage in [
            OriginalDeploymentStage::Initial,
            OriginalDeploymentStage::Scoped,
            OriginalDeploymentStage::Current,
        ] {
            let mut original_failure: Option<io::Error> = None;
            let mut dispatched = false;
            let mut original_current = None;
            let exchanged = HostAuthorityPeerChannel::exchange(&mut channel, |bytes| {
                let result: io::Result<Vec<u8>> = (|| {
                    gate.require_open()?;
                    let request = OriginalDeploymentRequest::decode_original(bytes)?;
                    request.require_original_stage(&self.original_binding, stage)?;
                    files.require_deployment_files()?;
                    let registration = bridge::apply_original_progress(
                        &files, &request, &commands, &acknowledgements, &gate, &mut dispatched,
                    )?;
                    // The actual Root ACK and all retained file post-checks
                    // precede encoding. Framing keeps its original request
                    // deadline; the bridge never creates a replacement budget.
                    gate.require_open()?;
                    let acknowledgement = OriginalDeploymentAcknowledgement::from_actual_registration(
                        &request, registration,
                    )?;
                    let encoded = acknowledgement.encode_original(&request)?;
                    if stage == OriginalDeploymentStage::Current {
                        original_current = Some((request, acknowledgement));
                    }
                    Ok(encoded)
                })();
                match result {
                    Ok(response) => Ok(response),
                    Err(error) => {
                        original_failure = Some(error);
                        Err(HostIssuerTransportError::Unavailable)
                    }
                }
            });
            if let Some(error) = original_failure {
                return Err(error);
            }
            let accepted = exchanged.map_err(|error| {
                let original = io::Error::other(error);
                if dispatched {
                    deployment_uncertain("original deployment response", original)
                } else {
                    original
                }
            })?;
            if !accepted {
                return Err(io::Error::other("original deployment peer closed before its stage"));
            }
            gate.require_open()?;
            HostAuthorityPeerChannel::check_peer_lifetime(&channel).map_err(io::Error::other)?;
            if let Some((request, acknowledgement)) = original_current {
                retirement.retain_original_current(&request, &acknowledgement)?;
            }
        }
        let mut original_failure = None;
        let exchanged = HostAuthorityPeerChannel::exchange(&mut channel, |bytes| {
            let result = (|| {
                retirement.require_original(&gate)?;
                files.require_deployment_files()?;
                let request =
                    crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementRequest::decode_original(bytes)?;
                retirement.authorize_original_retirement(&request)
            })();
            result.map_err(|error| {
                original_failure = Some(error);
                HostIssuerTransportError::Unavailable
            })
        });
        if let Some(error) = original_failure {
            return Err(error);
        }
        let accepted = exchanged.map_err(|error| {
            deployment_uncertain("original Root retirement intent response", io::Error::other(error))
        })?;
        if !accepted {
            return Err(io::Error::other("original deployment peer closed without Root retirement"));
        }
        retirement.require_original(&gate)?;
        HostAuthorityPeerChannel::check_peer_lifetime(&channel).map_err(io::Error::other)?;
        retirement.acknowledge_original_intent()?;
        closing.disarm();
        Ok(OriginalRootRetirementHandoff {
            channel,
            stream_stop,
            retirement: Arc::clone(&retirement),
            bound: self,
            files,
            closing: CloseSameActorPhaseOnDrop::new(&gate),
        })
    }
}

pub(super) struct OriginalRootRetirementHandoff {
    channel: HostAuthorityPeerChannel,
    stream_stop: crate::same_actor_q24_phase_gate::SameActorPhaseStream,
    retirement: Arc<crate::OriginalRootRetirementScope>,
    bound: BoundDeploymentProgress,
    files: DeploymentFiles,
    closing: CloseSameActorPhaseOnDrop,
}

/// The same actual final peer never leaves the common shutdown registry.
pub(super) struct OriginalRootRetirementPeer {
    channel: HostAuthorityPeerChannel,
    _stream_stop: crate::same_actor_q24_phase_gate::SameActorPhaseStream,
    retirement: Arc<crate::OriginalRootRetirementScope>,
    _closing: CloseSameActorPhaseOnDrop,
}

pub(super) struct OriginalRootRetainedDeployment {
    bound: BoundDeploymentProgress,
    files: DeploymentFiles,
    retirement: Arc<crate::OriginalRootRetirementScope>,
}

impl OriginalRootRetirementHandoff {
    pub(super) fn into_original_parts(
        self,
        retirement: &Arc<crate::OriginalRootRetirementScope>,
    ) -> io::Result<(OriginalRootRetirementPeer, OriginalRootRetainedDeployment)> {
        if !Arc::ptr_eq(&self.retirement, retirement) {
            return Err(io::Error::other("actual Root retirement peer belongs to another scope"));
        }
        retirement.require_original(retirement.gate())?;
        HostAuthorityPeerChannel::check_peer_lifetime(&self.channel).map_err(io::Error::other)?;
        let Self { channel, stream_stop, retirement, bound, files, closing } = self;
        Ok((
            OriginalRootRetirementPeer {
                channel,
                _stream_stop: stream_stop,
                retirement: Arc::clone(&retirement),
                _closing: closing,
            },
            OriginalRootRetainedDeployment { bound, files, retirement },
        ))
    }
}

impl OriginalRootRetainedDeployment {
    pub(super) fn require_original(
        &self,
        retirement: &crate::OriginalRootRetirementScope,
    ) -> io::Result<()> {
        if !std::ptr::eq(self.retirement.as_ref(), retirement) {
            return Err(io::Error::other("retained Root deployment replaced its original scope"));
        }
        retirement.require_original(retirement.gate())?;
        self.files.require_deployment_files()?;
        verify_pinned_process(
            &self.bound.original_registration,
            self.bound.original_uid,
            self.bound.original_gid,
            &self.bound.original_owner,
            retirement.gate().deadline().instant(),
        )?;
        retirement.require_original(retirement.gate())
    }
}

impl OriginalRootRetirementPeer {
    pub(super) fn acknowledge_original_joined(
        mut self,
        joined: &super::OriginalRootAllWorkersJoined,
    ) -> io::Result<()> {
        self.retirement.require_original(self.retirement.gate())?;
        joined.require_original(&self.retirement)?;
        HostAuthorityPeerChannel::check_peer_lifetime(&self.channel).map_err(io::Error::other)?;
        let mut original_failure = None;
        let exchanged = HostAuthorityPeerChannel::exchange(&mut self.channel, |bytes| {
            let result = (|| {
                let request =
                    crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementRequest::decode_original(bytes)?;
                let encoded = self.retirement.acknowledge_original_workers(&request, joined)?;
                self.retirement.require_original(self.retirement.gate())?;
                Ok(encoded)
            })();
            result.map_err(|error| {
                original_failure = Some(error);
                HostIssuerTransportError::Unavailable
            })
        });
        if let Some(error) = original_failure {
            return Err(error);
        }
        let accepted = exchanged.map_err(|error| {
            deployment_uncertain("actual Root workers joined response", io::Error::other(error))
        })?;
        if !accepted {
            return Err(io::Error::other("original final peer closed before the joined acknowledgement"));
        }
        // Same BOOTTIME/Instant and same original pidfd after the complete
        // frame. Failure remains uncertain and closes this stream; never retry.
        self.retirement.require_original(self.retirement.gate())?;
        HostAuthorityPeerChannel::check_peer_lifetime(&self.channel).map_err(io::Error::other)?;
        self.retirement.mark_original_workers_acknowledged(joined)?;
        // Keep this Root process and every actual returned owner alive while
        // the client performs its original response and pidfd postchecks. The
        // client must then close this same stream while its process stays
        // alive. This EOF orders release; it proves neither ACK consumption
        // nor any daemon/C completion.
        HostAuthorityPeerChannel::wait_for_original_peer_eof(&mut self.channel).map_err(|error| {
            deployment_uncertain("original final peer release after joined ACK", io::Error::other(error))
        })?;
        self.retirement.require_original(self.retirement.gate())?;
        joined.require_original(&self.retirement)?;
        Ok(())
    }
}
