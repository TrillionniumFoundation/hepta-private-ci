//! Same-process test transport only. Actual Published Circuit/Source owners
//! provide every successful response. Public custody constructors reject this
//! process/UID, and no production constructor accepts a response fixture.

#[path = "circuit_feature_current_read_support_tests.rs"]
pub(crate) mod current_slots;

use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::Channel;
use super::Error;
use super::OriginalCircuitEvaluatedLearningReadContextV1;
use super::OriginalCircuitLearningReadClientV1;
use super::OriginalCircuitLearningReadContextV1;
use super::OriginalCircuitLearningReadOwnerV1;
use super::now;
use super::profile::ReadProfile;
use super::wire;
use crate::AgentdRootAuthorityPeer;

pub(crate) fn pidfd() -> anyhow::Result<OwnedFd> {
    // SAFETY: obtain a new lifetime descriptor for this live fixture process.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(fd >= 0, "fixture original pidfd");
    // SAFETY: the successful syscall returned one owned descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(fd as i32) })
}

pub(crate) fn identity() -> anyhow::Result<AgentdRootAuthorityPeer> {
    let pid = std::process::id();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    Ok(AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: stat
            .rsplit_once(") ")
            .ok_or_else(|| anyhow::anyhow!("fixture process stat"))?
            .1
            .split_whitespace()
            .nth(19)
            .ok_or_else(|| anyhow::anyhow!("fixture start ticks"))?
            .parse()?,
    })
}

fn channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                // SAFETY: observe this test process's credentials only.
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        pidfd()?,
    )?)
}

pub(crate) fn client(
    context: OriginalCircuitLearningReadContextV1,
) -> anyhow::Result<(
    OriginalCircuitLearningReadClientV1,
    HostAuthorityPeerChannel,
)> {
    profile_client(ReadProfile::TrainingNoUpdate(context))
}

pub(crate) fn evaluated_client(
    context: OriginalCircuitEvaluatedLearningReadContextV1,
) -> anyhow::Result<(
    OriginalCircuitLearningReadClientV1,
    HostAuthorityPeerChannel,
)> {
    profile_client(ReadProfile::Evaluated(context))
}

fn profile_client(
    context: ReadProfile,
) -> anyhow::Result<(
    OriginalCircuitLearningReadClientV1,
    HostAuthorityPeerChannel,
)> {
    let (stream, server) = UnixStream::pair()?;
    let binding = context.binding(now()?)?;
    Ok((
        OriginalCircuitLearningReadClientV1 {
            context,
            binding,
            channel: Mutex::new(Some(Channel {
                peer: channel(stream)?,
                next_request_id: 1,
            })),
            retained: Mutex::new(None),
        },
        channel(server)?,
    ))
}

pub(crate) fn serve<
    C: AnchorWitnessStore + Send + 'static,
    S: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCircuitLearningReadOwnerV1<C, S>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_channel(&mut channel))
}

pub(crate) fn changed_nonce<
    C: AnchorWitnessStore + Send + 'static,
    S: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCircuitLearningReadOwnerV1<C, S>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        let mut read_original = false;
        let result = channel.exchange(|bytes| {
            let actual = owner
                .response(bytes, 1)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            read_original = true;
            let mut response: wire::Response = serde_json::from_slice(&actual)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            response.request.request_id += 1;
            serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
        });
        anyhow::ensure!(
            read_original,
            "actual original read preceded nonce mutation"
        );
        anyhow::ensure!(result.is_ok(), "the malformed response was actually sent");
        Ok(())
    })
}

pub(crate) fn delayed_response<
    C: AnchorWitnessStore + Send + 'static,
    S: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCircuitLearningReadOwnerV1<C, S>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        let mut read_original = false;
        let result = channel.exchange(|bytes| {
            let actual = owner
                .response(bytes, 1)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            read_original = true;
            // Only the response is delayed. Original owner IO already occurred,
            // and no lock, journal mutation, clock or signature is fabricated.
            std::thread::sleep(Duration::from_millis(650));
            Ok(actual)
        });
        anyhow::ensure!(
            read_original,
            "actual original read preceded lost response window"
        );
        anyhow::ensure!(
            result.is_err(),
            "original bounded exchange rejects the late response"
        );
        Ok(())
    })
}

pub(crate) fn reject_wrong_context<C: AnchorWitnessStore, S: AnchorWitnessStore>(
    owner: &OriginalCircuitLearningReadOwnerV1<C, S>,
    context: &OriginalCircuitLearningReadContextV1,
) -> anyhow::Result<()> {
    let binding = wire::context_binding(context, now()?)?;
    let mut request = wire::Request::new(context, binding, 1)?;
    request.operation_id.push_str("-changed");
    anyhow::ensure!(owner.response(&serde_json::to_vec(&request)?, 1).is_err());
    let request = wire::Request::new(context, binding, 1)?;
    anyhow::ensure!(owner.response(&serde_json::to_vec(&request)?, 2).is_err());
    let mut value = serde_json::to_value(&request)?;
    value
        .as_object_mut()
        .ok_or_else(|| anyhow::anyhow!("fixture request"))?
        .insert(
            "observation".into(),
            serde_json::json!({"selected": "caller supplied"}),
        );
    anyhow::ensure!(owner.response(&serde_json::to_vec(&value)?, 1).is_err());
    Ok(())
}

pub(crate) fn reject_evaluated_request_substitutions<
    C: AnchorWitnessStore,
    S: AnchorWitnessStore,
>(
    owner: &OriginalCircuitLearningReadOwnerV1<C, S>,
    context: &OriginalCircuitEvaluatedLearningReadContextV1,
) -> anyhow::Result<()> {
    let profile = ReadProfile::Evaluated(context.clone());
    let binding = profile.binding(now()?)?;
    let request = profile.request(binding, 1)?;
    let original = serde_json::to_value(&request)?;
    let wrong_mode = match profile.mode()? {
        wire::Mode::Selection => "next_use",
        wire::Mode::NextUse => "selection",
    };
    for (field, replacement) in [
        ("schema", serde_json::json!(2)),
        ("operation", serde_json::json!(wire::OPERATION)),
        ("request_id", serde_json::json!(2)),
        (
            "binding",
            serde_json::json!(codex_hepta_types::Digest32::of_bytes(b"other").to_string()),
        ),
        (
            "prefix_head",
            serde_json::json!(codex_hepta_types::Digest32::of_bytes(b"head").to_string()),
        ),
        (
            "operation_id",
            serde_json::json!("other-original-operation"),
        ),
        ("mode", serde_json::json!(wrong_mode)),
    ] {
        let mut changed = original.clone();
        changed[field] = replacement;
        anyhow::ensure!(
            matches!(
                owner.response(&serde_json::to_vec(&changed)?, 1),
                Err(Error::Binding("original fixed evaluated read request"))
            ),
            "changed evaluated read field: {field}"
        );
    }
    let mut uploaded = original;
    uploaded["observation"] = serde_json::json!({"selected": "caller supplied"});
    anyhow::ensure!(matches!(
        owner.response(&serde_json::to_vec(&uploaded)?, 1),
        Err(Error::Encoding(_))
    ));
    // Both legacy protocols must reject before accepting a new transport.
    let (stream, _unused) = UnixStream::pair()?;
    anyhow::ensure!(matches!(
        owner.serve_completion_readiness(
            stream,
            identity()?,
            // SAFETY: observe fixture credentials, never switch a process role.
            unsafe { libc::geteuid() },
            pidfd()?,
            Duration::from_millis(500),
            Duration::from_secs(300),
        ),
        Err(Error::Binding("legacy TrainingNoUpdate read purpose"))
    ));
    let (stream, _unused) = UnixStream::pair()?;
    let mut retained = channel(stream)?;
    anyhow::ensure!(matches!(
        owner.serve_original_retained_channel(&mut retained),
        Err(Error::Binding("legacy TrainingNoUpdate read purpose"))
    ));
    Ok(())
}

pub(crate) fn withdraw_source_before_final_selection_read<
    C: AnchorWitnessStore + Send + 'static,
    S: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCircuitLearningReadOwnerV1<C, S>>,
    mut channel: HostAuthorityPeerChannel,
    source_file: std::fs::File,
) -> std::thread::JoinHandle<anyhow::Result<u64>> {
    std::thread::spawn(move || {
        for request_id in 1..=3 {
            // Two actual reads reached the same Source/Cell. The final read
            // must reject this physical withdrawal after the S journal commit.
            if request_id == 3 {
                source_file.set_len(0)?;
            }
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                owner.response(bytes, request_id).map_err(|error| {
                    failure = Some(error);
                    HostIssuerTransportError::InvalidRequest
                })
            });
            if request_id == 3 {
                anyhow::ensure!(matches!(failure, Some(Error::Source(_))));
                anyhow::ensure!(exchanged.is_err());
                return Ok(request_id);
            }
            anyhow::ensure!(matches!(exchanged, Ok(true)));
        }
        anyhow::bail!("actual final Selection read was not attempted")
    })
}
