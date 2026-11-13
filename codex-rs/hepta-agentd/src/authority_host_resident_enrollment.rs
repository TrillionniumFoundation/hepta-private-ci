//! Root's once-only late enrollment and original candidate service composition.

use super::*;
use std::time::Duration;
use crate::HostAuthorityServiceConfig;
use crate::authority_host_runtime::listeners::resident::ResidentListener;
use crate::authority_host_runtime::listeners::resident::ResidentSocketGuard;

#[path = "authority_host_resident_enrollment_wire.rs"]
mod wire;
#[path = "authority_host_resident_enrollment_connect.rs"]
mod connect;
pub(crate) use connect::connect_original_resident_enrollment;

#[path = "authority_host_task_resident_enrollment.rs"]
mod original_task;
pub(crate) use original_task::{OriginalTaskResidentInputs, OriginalTaskResidentPaths,
    OriginalTaskResidentPrepared, OriginalTaskResidentPurpose, prepare_original_task_resident,
    OriginalTaskPrefreezeState, prepare_original_task_prefreeze};

/// No stream created before the daemon's credential drop is accepted here.
/// Root creates one protected listener; the actual daemon connects after A.
pub struct RootResidentCandidateEnrollmentInputsV3 {
    pub stage_handoff: UnixDatagram,
    pub enrollment_handoff: UnixDatagram,
    pub original_root_pidfd: OwnedFd,
    pub original_consumer_pidfd: OwnedFd,
    pub baseline_files: CellQ24ModelFilesV1,
}

pub async fn prepare_host_resident_candidate_enrollment_v3(
    config_file: &Path,
    deployment_file: &Path,
    trusted_evidence_file: &Path,
    original: RootResidentCandidateEnrollmentInputsV3,
) -> io::Result<RootResidentCandidateEnrollmentServiceV3> {
    prepare_enrollment(config_file, deployment_file, trusted_evidence_file, original, Purpose::Fresh).await
}

pub async fn recover_host_resident_candidate_enrollment_v3(
    config_file: &Path,
    deployment_file: &Path,
    trusted_evidence_file: &Path,
    original: RootResidentCandidateEnrollmentInputsV3,
    readback_file: &Path,
) -> io::Result<RootResidentCandidateEnrollmentServiceV3> {
    prepare_enrollment(config_file, deployment_file, trusted_evidence_file, original, Purpose::Readback(readback_file)).await
}

async fn prepare_enrollment(
    config_file: &Path,
    deployment_file: &Path,
    trusted_evidence_file: &Path,
    original: RootResidentCandidateEnrollmentInputsV3,
    purpose: Purpose<'_>,
) -> io::Result<RootResidentCandidateEnrollmentServiceV3> {
    // SAFETY: both calls inspect only actual current credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::other("original Root resident process required"));
    }
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    config.required_bind.verify()?;
    let trust = trust::OriginalHostTrust::read(trusted_evidence_file)?;
    let RootResidentCandidateEnrollmentInputsV3 {
        stage_handoff, enrollment_handoff, original_root_pidfd,
        original_consumer_pidfd, baseline_files,
    } = original;
    let baseline = Arc::new(LoadedCellQ24ModelV1::open_files(baseline_files).map_err(io::Error::other)?);
    let inputs::OriginalDeployment { profile, inputs, consumer, handoff_timeout, enrollment_profile } =
        inputs::OriginalDeployment::read(deployment_file, &trust, baseline)?;
    let (peer, uid, timeout, lifetime) = consumer.into_peer();
    if uid != config.peer_uid || matches!(config.peer_gid, 0 | u32::MAX) {
        return Err(io::Error::other("resident recipient differs from original host config"));
    }
    let recipient = wire::Process::from_peer(&peer);
    recipient.require_original()?;
    crate::authority_host_runtime::verify_process_credentials(peer.pid, uid, config.peer_gid)?;
    crate::root_production_handoff::require_original_resident_process_pin(&original_consumer_pidfd, peer.pid)
        .map_err(io::Error::other)?;
    let now = wire::now_ns()?;
    let connect_before_ns = now.checked_add(u64::try_from(handoff_timeout.as_nanos()).map_err(io::Error::other)?)
        .ok_or_else(|| io::Error::other("resident handoff deadline overflow"))?;
    let session_end_ns = now.checked_add(u64::try_from(lifetime.as_nanos()).map_err(io::Error::other)?)
        .ok_or_else(|| io::Error::other("resident session deadline overflow"))?;
    let connect_end = wire::absolute(connect_before_ns, Duration::from_secs(30))?;
    let session_end = wire::absolute(session_end_ns, Duration::from_secs(300))?;
    let (authorization, readback) = match purpose {
        Purpose::Fresh => (wire::Authorization::Fresh, None),
        Purpose::Readback(path) => {
            let value: ReadbackFile = read_root_json(path)?;
            if value.schema_version != 3
                || value.purpose != "hepta.host-resident-learning.readback-deployment.v3"
            { return Err(io::Error::other("resident readback purpose differs")); }
            let authorization = wire::Authorization::Readback { intent: value.intent.clone(), lease: value.lease.clone() };
            let original = RootResidentLearningReadbackAuthorizationV3::from_original_root(&profile, value.intent, value.lease)?;
            (authorization, Some(original))
        }
    };
    let handoff = crate::receive_root_candidate_stage_handoff(stage_handoff, &profile, wire::remaining(connect_end)?)
        .map_err(io::Error::other)?;
    // After this call fails or its ACK is uncertain, only explicit readback of
    // the same operation is legal. No listener/send failure restores freshness.
    let binding = profile.binding();
    // Use the same concrete config already checked for recipient and listener
    // custody. Reuse the original open-only issuer factory without a second
    // path read that could select a different Root configuration.
    let super::super::OriginalHostIssuerCustodyV3 { issuer, leases, root, .. } =
        super::super::open_original_issuer_custody(&config)?;
    let registration = match readback {
        Some(readback) => RootResidentLearningRegistrationV3::recover_original_root(
            root, issuer, Arc::new(leases), profile, readback,
        )?,
        None => RootResidentLearningRegistrationV3::register_original_root(
            root, issuer, Arc::new(leases), profile,
        )?,
    };
    wire::remaining(connect_end)?;
    let listener = ResidentListener::bind_original(&config, binding)?;
    let (path, device, inode) = listener.original_node();
    let packet = wire::Packet {
        schema_version: 3, purpose: wire::PURPOSE.into(), root: wire::Process::current()?,
        consumer: recipient, consumer_uid: uid, consumer_gid: config.peer_gid,
        profile: enrollment_profile,
        trusted_evidence: String::from_utf8(trust.encoded).map_err(io::Error::other)?,
        socket: path.clone(), socket_device: device, socket_inode: inode,
        connect_before_ns, session_end_ns,
        command_timeout_ms: u64::try_from(timeout.as_millis()).map_err(io::Error::other)?,
        authorization,
    };
    let sealed = wire::seal(&packet)?;
    crate::root_production_handoff::send_original_resident_enrollment(
        enrollment_handoff, &sealed, &original_root_pidfd, wire::remaining(connect_end)?,
    ).map_err(io::Error::other)?;
    let (stream, socket_guard) = listener.accept_original(connect_end).await?;
    packet.consumer.require_original()?;
    crate::authority_host_runtime::verify_process_credentials(peer.pid, uid, config.peer_gid)?;
    crate::root_production_handoff::require_original_resident_process_pin(&original_consumer_pidfd, peer.pid)
        .map_err(io::Error::other)?;
    wire::remaining(connect_end)?;
    let service = RootResidentLearningRegistrationV3::into_candidate_service(
        registration, inputs, handoff,
        RootResidentLearningConsumerV3 {
            stream, peer, uid, original_consumer_pidfd,
            timeout, lifetime: wire::remaining(session_end)?,
        },
    ).map_err(io::Error::other)?;
    wire::remaining(connect_end)?;
    Ok(RootResidentCandidateEnrollmentServiceV3 { service, socket_guard, session_end })
}

/// Retains the exact Root socket node through the original service lifetime.
/// The underlying continuation, cancellation and terminal join remain original.
pub struct RootResidentCandidateEnrollmentServiceV3 {
    service: RootResidentCandidateServiceV1,
    socket_guard: ResidentSocketGuard,
    session_end: std::time::Instant,
}

impl RootResidentCandidateEnrollmentServiceV3 {
    pub async fn run(self, cancellation: tokio_util::sync::CancellationToken) -> Result<(), crate::AgentdError> {
        let Self { service, socket_guard, session_end } = self;
        let bounded = cancellation.child_token();
        let work = RootResidentCandidateServiceV1::run(service, bounded.clone());
        tokio::pin!(work);
        let result = tokio::select! {
            result = &mut work => result,
            _ = tokio::time::sleep_until(tokio::time::Instant::from_std(session_end)) => {
                bounded.cancel();
                work.await
            }
        };
        drop(socket_guard);
        result
    }
}
