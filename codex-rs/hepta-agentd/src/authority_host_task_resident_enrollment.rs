//! The existing V3 registration is opened on the task's SAME retained Root
//! service. Its late signed Material must match the earlier fixed disclosure
//! and uses that same evidence trust; no second Source lane is constructed.

use super::*;
use std::path::PathBuf;
use std::time::Instant;
use codex_hepta_neuron::FileAnchorWitnessStore;
use crate::{AgentdError, HostAuthorityService, OriginalRootCircuitTaskCustodyV1,
    RootCandidateStageHandoffV1};
use crate::authority_host_config::HostAuthorityRegistration;

#[path = "authority_host_task_prefreeze_inputs.rs"]
mod prefreeze;
pub(crate) use prefreeze::{OriginalTaskPrefreezeState, prepare_original_task_prefreeze};

pub(crate) struct OriginalTaskResidentPaths {
    pub(crate) deployment: PathBuf,
}

pub(crate) enum OriginalTaskResidentPurpose {
    Fresh,
    Readback(PathBuf),
}

pub(crate) struct OriginalTaskResidentInputs {
    pub(crate) stage_transport: crate::root_production_handoff::OriginalRootCandidateStageTransportV1,
    pub(crate) enrollment_handoff: UnixDatagram,
    pub(crate) original_root_pidfd: OwnedFd,
    pub(crate) original_consumer_pidfd: OwnedFd,
    pub(crate) baseline_files: CellQ24ModelFilesV1,
}

pub(crate) struct OriginalTaskResidentPrepared {
    registration: RootResidentLearningRegistrationV3,
    inputs: crate::RootResidentCandidateInputsV1,
    handoff: RootCandidateStageHandoffV1,
    listener: ResidentListener,
    packet: wire::Packet,
    enrollment_handoff: UnixDatagram,
    original_root_pidfd: OwnedFd,
    original_consumer_pidfd: OwnedFd,
    peer: crate::AgentdRootAuthorityPeer,
    uid: u32,
    timeout: Duration,
    connect_end: Instant,
    session_end: Instant,
}

/// Crate-private fixed assembly. It accepts the concrete retained task custody,
/// never a caller checker or a decoded Source/Cell receipt. Root's old issuer
/// factory is deliberately absent: the provided service already owns it.
pub(crate) fn prepare_original_task_resident(
    service: &HostAuthorityService, config: &HostAuthorityServiceConfig,
    original_registration: &HostAuthorityRegistration,
    custody: &OriginalRootCircuitTaskCustodyV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    paths: OriginalTaskResidentPaths, original: OriginalTaskResidentInputs,
    prefreeze: &OriginalTaskPrefreezeState,
    purpose: OriginalTaskResidentPurpose, startup_end: Instant, task_end: Instant,
) -> Result<OriginalTaskResidentPrepared, AgentdError> {
    wire::remaining(startup_end)?;
    prefreeze.require_original_prefreeze_trust()?;
    let trust = prefreeze.evidence();
    let OriginalTaskResidentInputs { stage_transport, enrollment_handoff, original_root_pidfd,
        original_consumer_pidfd, baseline_files } = original;
    let baseline = Arc::new(LoadedCellQ24ModelV1::open_files(baseline_files).map_err(protocol)?);
    let inputs::OriginalDeployment { profile, inputs, consumer, handoff_timeout, enrollment_profile } =
        inputs::OriginalDeployment::read(&paths.deployment, trust, baseline)?;
    prefreeze.require_material(&inputs.material)?;
    let (peer, uid, requested_timeout, lifetime) = consumer.into_peer();
    if uid != config.peer_uid || matches!(config.peer_gid, 0 | u32::MAX)
        || peer.pid != original_registration.peer_pid
        || peer.boot_id != original_registration.boot_id
        || peer.process_start_ticks != original_registration.process_start_ticks
    { return Err(protocol("resident recipient is not this original registered daemon")); }
    let timeout = requested_timeout.min(Duration::from_millis(config.timeout_ms.min(500)));
    if timeout.is_zero() { return Err(protocol("original resident command timeout is empty")); }
    let recipient = wire::Process::from_peer(&peer);
    wire::Process::require_original(&recipient)?;
    crate::authority_host_runtime::verify_process_credentials(peer.pid, uid, config.peer_gid)?;
    crate::root_production_handoff::require_original_resident_process_pin(&original_consumer_pidfd, peer.pid)?;
    let connect_end = (Instant::now() + handoff_timeout).min(startup_end).min(task_end);
    let session_end = (Instant::now() + lifetime).min(task_end);
    wire::remaining(connect_end)?;
    let (authorization, readback) = match purpose {
        OriginalTaskResidentPurpose::Fresh => (wire::Authorization::Fresh, None),
        OriginalTaskResidentPurpose::Readback(path) => {
            let value: ReadbackFile = read_root_json(&path)?;
            if value.schema_version != 3 || value.purpose != "hepta.host-resident-learning.readback-deployment.v3" {
                return Err(protocol("original resident readback purpose differs"));
            }
            let authorization = wire::Authorization::Readback { intent: value.intent.clone(), lease: value.lease.clone() };
            let readback = RootResidentLearningReadbackAuthorizationV3::from_original_root(
                &profile, value.intent, value.lease)?;
            (authorization, Some(readback))
        }
    };
    let handoff = crate::root_production_handoff::OriginalRootCandidateStageTransportV1::bind_original_profile(stage_transport, &profile)?;
    wire::remaining(connect_end)?;
    // A protected configuration and signed freeze do not prove A ran. Reach
    // the retained original Source and same-Arc Cell before any registration.
    let _actual_source = OriginalRootCircuitTaskCustodyV1::read_original_material_source(
        custody, &inputs.material.initial.request)?;
    prefreeze.require_material(&inputs.material)?;
    wire::remaining(connect_end)?;
    let binding = profile.binding();
    let registration = match readback {
        Some(readback) => HostAuthorityService::recover_resident_learning_v3(service, profile, readback)?,
        None => HostAuthorityService::register_resident_learning_v3(service, profile)?,
    };
    wire::remaining(connect_end)?;
    let listener: ResidentListener = ResidentListener::bind_original(config, binding)?;
    let (path, device, inode) = listener.original_node();
    // Read monotonic first. Subsequent Instant sampling can only reduce each
    // transmitted remainder; neither deadline is reset by enrollment.
    let now_ns = wire::now_ns()?;
    let connect_before_ns = now_ns.checked_add(u64::try_from(wire::remaining(connect_end)?.as_nanos()).map_err(protocol)?)
        .ok_or_else(|| protocol("original resident connect deadline overflow"))?;
    let session_end_ns = now_ns.checked_add(u64::try_from(wire::remaining(session_end)?.as_nanos()).map_err(protocol)?)
        .ok_or_else(|| protocol("original resident session deadline overflow"))?;
    let packet = wire::Packet { schema_version: 3, purpose: wire::PURPOSE.into(),
        root: wire::Process::current()?, consumer: recipient, consumer_uid: uid, consumer_gid: config.peer_gid,
        profile: enrollment_profile, trusted_evidence: String::from_utf8(trust.encoded.clone()).map_err(protocol)?,
        socket: path.clone(), socket_device: device, socket_inode: inode,
        connect_before_ns, session_end_ns, command_timeout_ms: u64::try_from(timeout.as_millis()).map_err(protocol)?,
        authorization };
    wire::remaining(connect_end)?;
    prefreeze.require_original_prefreeze_trust()?;
    Ok(OriginalTaskResidentPrepared { registration, inputs, handoff, listener, packet,
        enrollment_handoff, original_root_pidfd, original_consumer_pidfd, peer, uid, timeout,
        connect_end, session_end })
}

impl OriginalTaskResidentPrepared {
    pub(crate) async fn enroll(self) -> Result<RootResidentCandidateEnrollmentServiceV3, AgentdError> {
        let Self { registration, inputs, handoff, listener, packet, enrollment_handoff,
            original_root_pidfd, original_consumer_pidfd, peer, uid, timeout, connect_end, session_end } = self;
        wire::remaining(connect_end)?;
        let sealed = wire::seal(&packet)?;
        crate::root_production_handoff::send_original_resident_enrollment(
            enrollment_handoff, &sealed, &original_root_pidfd, wire::remaining(connect_end)?)?;
        let (stream, socket_guard) = ResidentListener::accept_original(listener, connect_end).await?;
        wire::Process::require_original(&packet.consumer)?;
        crate::authority_host_runtime::verify_process_credentials(peer.pid, uid, packet.consumer_gid)?;
        crate::root_production_handoff::require_original_resident_process_pin(&original_consumer_pidfd, peer.pid)?;
        wire::remaining(connect_end)?;
        let service = RootResidentLearningRegistrationV3::into_candidate_service(registration, inputs, handoff,
            RootResidentLearningConsumerV3 { stream, peer, uid, original_consumer_pidfd,
                timeout, lifetime: wire::remaining(session_end)? }).map_err(protocol)?;
        wire::remaining(connect_end)?;
        Ok(RootResidentCandidateEnrollmentServiceV3 { service, socket_guard, session_end })
    }
}

fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("same-session original resident assembly: {error}"))
}
