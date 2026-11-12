//! The independent source process transfers existing signed data. It receives
//! no Evaluator key, learning owner, holdout reader or result-write capability.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::os::unix::fs::MetadataExt;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::RootIndependentBSourceHandoffV1;
use crate::root_generation_current_client::OriginalPublicationStream;
use crate::root_independent_b_protocol::digest;
use crate::root_independent_b_source_protocol::*;

#[path = "root_independent_b_source_data.rs"]
mod data;
pub(crate) use data::require_original_source_file;

/// Data supplied by the original independent owners. Root authenticates the
/// two fixed roles; constructing this structure grants no authority.
pub struct OriginalBSourceSignedDataV1 {
    pub source: Vec<u8>,
    pub observed_statement: Vec<u8>,
    pub policy_statement: Vec<u8>,
}

/// An input-delivery observation, never an evaluation result or capability.
#[derive(Debug, Eq, PartialEq)]
pub enum OriginalBSourceIngressStatusV1 {
    RetainedInput { source_digest: Digest32 },
    AlreadyRetained,
    NoUpdate,
}

pub async fn submit_original_root_b_source(
    handoff: RootIndependentBSourceHandoffV1,
    read_original: impl FnOnce() -> io::Result<OriginalBSourceSignedDataV1>,
) -> Result<OriginalBSourceIngressStatusV1, AgentdError> {
    submit_original_root_b_source_with_candidate(handoff, |_| read_original()).await
}

/// Receive actual candidate DATA before the independent owners produce their
/// policy/outcomes. The callback receives no handoff, FD or authority object.
pub async fn submit_original_root_b_source_with_candidate(
    mut handoff: RootIndependentBSourceHandoffV1,
    read_original: impl FnOnce(
        &crate::OriginalRootBCandidateDataV1,
    ) -> io::Result<OriginalBSourceSignedDataV1>,
) -> Result<OriginalBSourceIngressStatusV1, AgentdError> {
    let length = handoff.bootstrap.metadata()?.len();
    if length == 0 || length > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
        return Err(refused("bounded original B source bootstrap required"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&handoff.bootstrap, length)?;
    handoff.bootstrap.rewind()?;
    let mut bytes = Vec::with_capacity(length as usize);
    handoff
        .bootstrap
        .by_ref()
        .take(length + 1)
        .read_to_end(&mut bytes)?;
    crate::authority_host_bootstrap_seal::validate_sealed(&handoff.bootstrap, length)?;
    let bootstrap: SourceBootstrap = serde_json::from_slice(&bytes)?;
    if bytes.len() != length as usize
        || serde_json::to_vec(&bootstrap)? != bytes
        || bootstrap.schema != 3
        || bootstrap.purpose != PURPOSE
        || bootstrap.root.uid != 0
        || bootstrap.root.pid != handoff.root_pid
        || bootstrap.registered_at_seconds == 0
        || bootstrap.frame_timeout_ms == 0
        || bootstrap.frame_timeout_ms > 500
        || (bootstrap.mode == SourceMode::FreshInput) != handoff.source.is_some()
        || (bootstrap.mode == SourceMode::FreshInput) != handoff.candidate_data.is_some()
        || (bootstrap.mode == SourceMode::FreshInput) != handoff.candidate_notice.is_some()
        || (bootstrap.mode == SourceMode::FreshInput) != handoff.source_finalized.is_some()
    {
        return Err(refused("original B source bootstrap differs"));
    }
    let initial = digest(&bootstrap.initial)?;
    if digest(&bootstrap.binding)?
        != Digest32::of_parts(&[
            b"hepta.root.independent-b.custodian.v1\0",
            initial.as_array(),
        ])
    {
        return Err(refused("original B source binding differs"));
    }
    require_process(&bootstrap.root)?;
    crate::root_observation_stream::check_lifetime(&handoff.root_pidfd)
        .map_err(|_| refused("original B source Root ended"))?;
    let end = receive_original_end(bootstrap.absolute_end_monotonic_ns)?;
    // Closed routes do not inspect the old source process, open input files,
    // reconnect a source lane or turn a new PID into an old admitted owner.
    match bootstrap.mode {
        SourceMode::Retained => return Ok(OriginalBSourceIngressStatusV1::AlreadyRetained),
        SourceMode::NoUpdate => return Ok(OriginalBSourceIngressStatusV1::NoUpdate),
        SourceMode::FreshInput => {}
    }
    if bootstrap.source_peer.uid == 0
        || bootstrap.source_peer.uid == bootstrap.learner.uid
        || bootstrap.source_peer.pid == bootstrap.learner.pid
        || bootstrap.source_peer.pid != std::process::id()
    {
        return Err(refused("actual independent B source process required"));
    }
    require_process(&bootstrap.source_peer)?;
    let paths = [&bootstrap.socket];
    crate::authority_host_runtime::validate_lane_paths(&paths, bootstrap.socket_gid)?;
    if bootstrap.socket.file_name() != Some(std::ffi::OsStr::new(SOCKET)) {
        return Err(refused("original B source socket purpose differs"));
    }
    let socket = std::fs::symlink_metadata(&bootstrap.socket)?;
    if !std::os::unix::fs::FileTypeExt::is_socket(&socket.file_type())
        || socket.uid() != 0
        || socket.gid() != bootstrap.socket_gid
        || socket.mode() & 0o7777 != 0o660
    {
        return Err(refused("original B source socket custody differs"));
    }
    let notice = handoff
        .candidate_notice
        .take()
        .ok_or_else(|| refused("original B candidate notice missing"))?;
    let raw = crate::root_independent_b_notice::receive_original_notice(
        notice,
        handoff.root_pid,
        end,
        || {
            require_process(&bootstrap.root)?;
            require_process(&bootstrap.source_peer)?;
            crate::root_observation_stream::check_lifetime(&handoff.root_pidfd)
                .map_err(|_| io::Error::other("original B source Root ended"))
        },
    )?;
    let candidate_file = handoff
        .candidate_data
        .take()
        .ok_or_else(|| refused("original B readonly candidate missing"))?;
    let candidate =
        crate::root_independent_b_candidate_notice::CandidateNotice::read_original_data(
            &raw,
            &candidate_file,
            &bootstrap,
            end,
            || {
                require_process(&bootstrap.root)?;
                require_process(&bootstrap.source_peer)?;
                crate::root_observation_stream::check_lifetime(&handoff.root_pidfd)
                    .map_err(|_| io::Error::other("original B source Root ended"))
            },
        )?;
    drop(candidate_file);
    let original = read_original(&candidate)?;
    require_process(&bootstrap.root)?;
    require_process(&bootstrap.source_peer)?;
    crate::root_observation_stream::check_lifetime(&handoff.root_pidfd)
        .map_err(|_| refused("original B source Root ended"))?;
    if Instant::now() >= end {
        return Err(refused("original B source end elapsed"));
    }
    if original.source.is_empty() || original.source.len() > SOURCE_BOUND {
        return Err(refused("bounded original signed B source required"));
    }
    let source_digest = Digest32::of_bytes(&original.source);
    let observed_digest = Digest32::of_bytes(&original.observed_statement);
    let policy_digest = Digest32::of_bytes(&original.policy_statement);
    let request = SourceRequest {
        schema: 1,
        purpose: PURPOSE.into(),
        binding: bootstrap.binding.clone(),
        source_digest: source_digest.to_string(),
        observed_statement: original.observed_statement,
        policy_statement: original.policy_statement,
    };
    let request = serde_json::to_vec(&request)?;
    if request.len() > FRAME_BOUND {
        return Err(refused("original B source statement frame oversized"));
    }
    let file = handoff
        .source
        .take()
        .ok_or_else(|| refused("original B source writer missing"))?;
    data::write_original_source(file, &bootstrap, &original.source, end)?;
    // The only source writer is closed before the Root input-admission request.
    require_process(&bootstrap.source_peer)?;
    require_process(&bootstrap.root)?;
    let timeout = Duration::from_millis(bootstrap.frame_timeout_ms);
    let remaining = end
        .checked_duration_since(Instant::now())
        .ok_or_else(|| refused("original B source end expired"))?;
    let stream = tokio::time::timeout(
        timeout.min(remaining),
        tokio::net::UnixStream::connect(&bootstrap.socket),
    )
    .await
    .map_err(|_| refused("original B source connection timed out"))??;
    let original_root = handoff.root_pidfd.try_clone()?;
    let mut stream = OriginalPublicationStream::from_stream_until(
        stream.into_std()?,
        handoff.root_pidfd,
        AgentdRootAuthorityPeer {
            pid: bootstrap.root.pid,
            boot_id: bootstrap.root.boot_id.clone(),
            process_start_ticks: bootstrap.root.process_start_ticks,
        },
        timeout,
        end,
    )?;
    let bytes = stream.exchange(&request)?;
    let response: SourceAcknowledgement = serde_json::from_slice(&bytes)?;
    if serde_json::to_vec(&response)? != bytes
        || response.schema != 1
        || response.purpose != PURPOSE
        || response.binding != bootstrap.binding
        || response.source_digest != source_digest.to_string()
        || response.observed_digest != observed_digest.to_string()
        || response.policy_digest != policy_digest.to_string()
        || Instant::now() >= end
    {
        return Err(refused("original B source acknowledgement differs"));
    }
    require_process(&bootstrap.source_peer)?;
    require_process(&bootstrap.root)?;
    // A response alone precedes the server's final source-pidfd check. Stay
    // alive until its separate terminal DATA notification has reached EOF.
    let finalized = handoff
        .source_finalized
        .take()
        .ok_or_else(|| refused("original B source finalization missing"))?;
    let bytes = crate::root_independent_b_notice::receive_original_notice(
        finalized,
        handoff.root_pid,
        end,
        || {
            require_process(&bootstrap.root)?;
            require_process(&bootstrap.source_peer)?;
            crate::root_observation_stream::check_lifetime(&original_root).map_err(io::Error::other)
        },
    )?;
    crate::root_independent_b_source_finalized::require_original_source_finalized(
        &bytes, &candidate, &response,
    )?;
    require_process(&bootstrap.root)?;
    require_process(&bootstrap.source_peer)?;
    crate::root_observation_stream::check_lifetime(&original_root).map_err(io::Error::other)?;
    if Instant::now() >= end {
        return Err(refused("original B source end elapsed after finalization"));
    }
    Ok(OriginalBSourceIngressStatusV1::RetainedInput { source_digest })
}

fn require_process(life: &CognitiveCheckpointPeerLifetime) -> io::Result<()> {
    if life.pid == 0 || life.pid > i32::MAX as u32 || life.process_start_ticks == 0 {
        return Err(io::Error::other(
            "original B source process identity missing",
        ));
    }
    let read = |path: &str, max: u64| -> io::Result<String> {
        let mut value = String::new();
        File::open(path)?.take(max + 1).read_to_string(&mut value)?;
        if value.len() as u64 > max {
            return Err(io::Error::other("process metadata oversized"));
        }
        Ok(value)
    };
    let status = read(&format!("/proc/{}/status", life.pid), 16_384)?;
    let stat = read(&format!("/proc/{}/stat", life.pid), 8192)?;
    let uid = life.uid.to_string();
    if read("/proc/sys/kernel/random/boot_id", 128)?.trim() != life.boot_id
        || stat
            .rsplit_once(") ")
            .and_then(|(_, values)| values.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok())
            != Some(life.process_start_ticks)
        || !status
            .lines()
            .find_map(|line| line.strip_prefix("Uid:"))
            .is_some_and(|value| {
                let mut values = value.split_whitespace();
                (0..4).all(|_| values.next() == Some(uid.as_str())) && values.next().is_none()
            })
    {
        return Err(io::Error::other("original B process incarnation differs"));
    }
    Ok(())
}

fn refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}

#[cfg(test)]
#[path = "root_independent_b_source_tests.rs"]
mod tests;
