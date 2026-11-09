//! Explicit learning-data extension of the original retained Root service.
//! The concrete checkpoint capability is supplied by the trusted launcher;
//! peer authentication alone never authorizes or registers a learning owner.

use super::*;
use crate::HostAuthorityRegistration;
use crate::LearningIterationCheckpointOwnerV1;
use crate::authority_host_runtime::verify_pinned_process;
use crate::learning_iteration_checkpoint::transport::AgentdLearningCheckpointClientV1;
use crate::learning_iteration_checkpoint::transport::FRAME_LIMIT;
use crate::learning_iteration_checkpoint::transport::LearningCheckpointBackend;
use crate::learning_iteration_checkpoint::transport::decode_snapshot;
use crate::learning_iteration_checkpoint::transport::encode_snapshot;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::os::unix::net::UnixDatagram;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

const BOOTSTRAP_DOMAIN: &str = "runtime.agentd.learning_checkpoint.bootstrap.v1";

#[cfg(test)]
#[path = "authority_host_learning_checkpoint_tests.rs"]
mod tests;

/// An explicit trusted-launcher input, separate from the existing five lanes.
/// Neither this description nor a writer identity creates checkpoint authority.
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootLearningCheckpointProfileV1 {
    pub consumer: HostAuthorityRegistration,
    pub peer_uid: u32,
    pub peer_gid: u32,
    pub endpoint: PathBuf,
    pub timeout_ms: u64,
    pub lifetime_ms: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Bootstrap {
    schema_version: u8,
    operation: String,
    root: CognitiveCheckpointPeerLifetime,
    profile: RootLearningCheckpointProfileV1,
    owner_id: String,
    initial: String,
}

/// One server with one original checkpoint and consumer incarnation. Serving
/// consumes it; no wire request can select a store, peer, policy or issuer.
pub struct PreparedRootLearningCheckpointV1 {
    service: Arc<HostAuthorityService>,
    backend: LearningCheckpointBackend,
    profile: RootLearningCheckpointProfileV1,
    root: CognitiveCheckpointPeerLifetime,
    consumer_pidfd: OwnedFd,
    end: Instant,
}

impl HostAuthorityService {
    /// Opt in using the existing concrete capability, same registered writer
    /// and actual consumer pidfd. This opens no pathname and creates no owner.
    pub fn learning_checkpoint_profile(
        self: &Arc<Self>,
        checkpoint: LearningIterationCheckpointOwnerV1,
        profile: RootLearningCheckpointProfileV1,
        consumer_pidfd: OwnedFd,
    ) -> io::Result<PreparedRootLearningCheckpointV1> {
        require_root()?;
        profile.validate()?;
        if profile.consumer.registered_identity.identity()? != self.identity {
            return Err(io::Error::other(
                "learning consumer differs from original writer",
            ));
        }
        let backend = LearningCheckpointBackend::new(checkpoint);
        if backend.initial.request.agent_id.as_str() != self.identity.agent_id.as_str() {
            return Err(io::Error::other(
                "learning checkpoint belongs to another agent",
            ));
        }
        let writer = self.writer.as_ref().ok_or_else(|| {
            io::Error::other("original registered writer required for checkpoint delivery")
        })?;
        if writer.registration.registered_agent_id != self.identity.agent_id
            || writer.registration.spawn_generation != self.identity.spawn_generation
        {
            return Err(io::Error::other("original learning writer binding differs"));
        }
        let end = Instant::now() + Duration::from_millis(profile.lifetime_ms);
        verify_pinned_process(
            &profile.consumer,
            profile.peer_uid,
            profile.peer_gid,
            &consumer_pidfd,
            end,
        )?;
        self.check_logind_lifetime()?;
        let root = CognitiveCheckpointPeerLifetime {
            uid: 0,
            pid: std::process::id(),
            boot_id: profile.consumer.boot_id.clone(),
            process_start_ticks: process_start(std::process::id())?,
        };
        Ok(PreparedRootLearningCheckpointV1 {
            service: Arc::clone(self),
            backend,
            profile,
            root,
            consumer_pidfd,
            end,
        })
    }
}

impl PreparedRootLearningCheckpointV1 {
    /// Seal only fixed data for the original anonymous Root handoff carrier.
    /// Admission still requires a new live authenticated restore; this is not
    /// a permission, a receipt attestation or a cached successful checkpoint.
    pub fn seal_handoff(&self) -> io::Result<File> {
        require_root()?;
        if self.root.pid != std::process::id()
            || process_start(self.root.pid)? != self.root.process_start_ticks
        {
            return Err(io::Error::other("learning Root incarnation changed"));
        }
        self.profile.validate()?;
        verify_pinned_process(
            &self.profile.consumer,
            self.profile.peer_uid,
            self.profile.peer_gid,
            &self.consumer_pidfd,
            self.end,
        )?;
        let bundle = Bootstrap {
            schema_version: 1,
            operation: BOOTSTRAP_DOMAIN.into(),
            root: self.root.clone(),
            profile: self.profile.clone(),
            owner_id: self.backend.owner_id.clone(),
            initial: encode_snapshot(&self.backend.initial).map_err(io::Error::other)?,
        };
        // Bound the complete descriptor during serialization, before sealing.
        let mut buffer = [0_u8; FRAME_LIMIT];
        let mut output = io::Cursor::new(buffer.as_mut_slice());
        serde_json::to_writer(&mut output, &bundle).map_err(io::Error::other)?;
        let length = output.position() as usize;
        self.service.check_logind_lifetime()?;
        crate::authority_host_bootstrap_seal::seal_bytes(&buffer[..length])
    }

    /// Serve a pre-accepted stream from the fixed listener. The actual peer and
    /// retained pidfd are rechecked before every original writer-fenced CAS.
    pub fn serve(mut self, stream: UnixStream) -> Result<(), HostIssuerTransportError> {
        require_root().map_err(unavailable)?;
        if self.root.pid != std::process::id()
            || stream.local_addr().map_err(unavailable)?.as_pathname()
                != Some(self.profile.endpoint.as_path())
        {
            return Err(HostIssuerTransportError::PeerDenied);
        }
        let policy = HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: self.profile.peer_uid,
                pid: self.profile.consumer.peer_pid,
            },
            timeout: Duration::from_millis(self.profile.timeout_ms),
            lifetime: remaining(self.end).map_err(unavailable)?,
            request_bound: FRAME_LIMIT,
            response_bound: FRAME_LIMIT,
        };
        let mut channel = HostAuthorityPeerChannel::from_stream(
            stream,
            policy,
            self.consumer_pidfd.try_clone().map_err(unavailable)?,
        )?;
        while channel.exchange(|bytes| {
            verify_pinned_process(
                &self.profile.consumer,
                self.profile.peer_uid,
                self.profile.peer_gid,
                &self.consumer_pidfd,
                self.end,
            )
            .map_err(unavailable)?;
            self.service.check_logind_lifetime().map_err(unavailable)?;
            let response = self
                .service
                .writer
                .as_ref()
                .ok_or(HostIssuerTransportError::Unavailable)?
                .exchange_learning_checkpoint(
                    &self.service.issuer,
                    &self.service.clock,
                    &mut self.backend,
                    bytes,
                )?;
            self.service.check_logind_lifetime().map_err(unavailable)?;
            verify_pinned_process(
                &self.profile.consumer,
                self.profile.peer_uid,
                self.profile.peer_gid,
                &self.consumer_pidfd,
                self.end,
            )
            .map_err(unavailable)?;
            Ok(response)
        })? {}
        Ok(())
    }
}

impl RootLearningCheckpointProfileV1 {
    fn validate(&self) -> io::Result<()> {
        if matches!(self.peer_uid, 0 | u32::MAX)
            || matches!(self.peer_gid, 0 | u32::MAX)
            || self.consumer.schema_version != 1
            || self.consumer.checkpoint_owner_agent_id != self.consumer.registered_identity.agent_id
            || !(1..=30_000).contains(&self.timeout_ms)
            || !(1..=300_000).contains(&self.lifetime_ms)
        {
            return Err(io::Error::other("invalid explicit learning profile"));
        }
        crate::authority_host_runtime::validate_lane_paths(&[&self.endpoint], self.peer_gid)
    }
}

/// Receive the original Root-created anonymous pair, admit the exact process,
/// connect once to its fixed endpoint and complete a fresh restore. No fallback
/// supplies a missing production owner or grants a learning receipt role.
pub async fn receive_learning_checkpoint_handoff_v1(
    handoff: UnixDatagram,
    expected: AgentdIdentity,
    timeout: Duration,
) -> io::Result<AgentdLearningCheckpointClientV1> {
    let started = Instant::now();
    let (bundle, initial, root_pidfd) = tokio::task::spawn_blocking(move || {
        let (mut file, root_pidfd) =
            crate::receive_root_production_handoff(handoff, timeout).map_err(io::Error::other)?;
        let length = file.metadata()?.len();
        if length == 0 || length > FRAME_LIMIT as u64 {
            return Err(io::Error::other("learning descriptor exceeds bound"));
        }
        crate::authority_host_bootstrap_seal::validate_sealed(&file, length)?;
        file.rewind()?;
        let mut bytes = Vec::new();
        Read::by_ref(&mut file)
            .take(FRAME_LIMIT as u64 + 1)
            .read_to_end(&mut bytes)?;
        crate::authority_host_bootstrap_seal::validate_sealed(&file, length)?;
        if bytes.len() as u64 != length {
            return Err(io::Error::other("learning descriptor length changed"));
        }
        let bundle: Bootstrap = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        bundle.profile.validate()?;
        let initial = decode_snapshot(&bundle.initial).map_err(io::Error::other)?;
        // SAFETY: these calls only read this process's kernel credentials.
        let (uid, gid) = unsafe { (libc::geteuid(), libc::getegid()) };
        if bundle.schema_version != 1
            || bundle.operation != BOOTSTRAP_DOMAIN
            || bundle.root.uid != 0
            || bundle.root.pid == 0
            || bundle.root.pid == std::process::id()
            || bundle.profile.peer_uid != uid
            || bundle.profile.peer_gid != gid
            || bundle.profile.consumer.peer_pid != std::process::id()
            || bundle.profile.consumer.registered_identity.identity()? != expected
            || initial.request.agent_id.as_str() != expected.agent_id.as_str()
            || !initial.receipts.is_empty()
            || bundle.owner_id.is_empty()
            || bundle.owner_id.len() > 128
            || !bundle.owner_id.is_ascii()
        {
            return Err(io::Error::other(
                "learning handoff differs from original process",
            ));
        }
        crate::authority_host_runtime::verify_process(&bundle.profile.consumer, uid, gid)?;
        let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?;
        if boot.trim() != bundle.root.boot_id
            || process_start(bundle.root.pid)? != bundle.root.process_start_ticks
        {
            return Err(io::Error::other("learning Root incarnation differs"));
        }
        Ok((bundle, initial, root_pidfd))
    })
    .await
    .map_err(io::Error::other)??;
    let end = started + Duration::from_millis(bundle.profile.lifetime_ms);
    let timeout = Duration::from_millis(bundle.profile.timeout_ms).min(remaining(end)?);
    let stream = tokio::time::timeout(
        timeout,
        tokio::net::UnixStream::connect(&bundle.profile.endpoint),
    )
    .await
    .map_err(io::Error::other)??
    .into_std()?;
    tokio::task::spawn_blocking(move || {
        let channel = HostAuthorityPeerChannel::from_stream(
            stream,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: 0,
                    pid: bundle.root.pid,
                },
                timeout,
                lifetime: remaining(end)?,
                request_bound: FRAME_LIMIT,
                response_bound: FRAME_LIMIT,
            },
            root_pidfd,
        )
        .map_err(io::Error::other)?;
        let client = AgentdLearningCheckpointClientV1::from_admitted_channel(
            channel,
            bundle.owner_id,
            initial.clone(),
        );
        client.restore(&initial.request).map_err(io::Error::other)?;
        Ok(client)
    })
    .await
    .map_err(io::Error::other)?
}

fn require_root() -> io::Result<()> {
    // SAFETY: getuid/geteuid read actual kernel credentials without pointers.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::other(
            "original Root checkpoint producer required",
        ));
    }
    Ok(())
}

fn process_start(pid: u32) -> io::Result<u64> {
    if pid == 0 || pid > i32::MAX as u32 {
        return Err(io::Error::other("invalid learning process identity"));
    }
    let mut stat = String::new();
    File::open(format!("/proc/{pid}/stat"))?
        .take(8193)
        .read_to_string(&mut stat)?;
    if stat.len() > 8192 {
        return Err(io::Error::other("process identity exceeds bound"));
    }
    stat.rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("missing original process start identity"))
}

fn remaining(end: Instant) -> io::Result<Duration> {
    end.checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero())
        .ok_or_else(|| io::Error::other("learning checkpoint profile lifetime elapsed"))
}
