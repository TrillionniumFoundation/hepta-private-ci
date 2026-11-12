//! Explicit signed Material metadata over the original codec and framer.
//! This same-process fixture does not execute either Observer or a training run.
use super::*;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use crate::learning_iteration_evidence_client::command_test_support::pidfd;

fn channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(stream, HostAuthorityPeerPolicy {
        // SAFETY: explicit test-only credentials for this same process.
        peer: HostIssuerPeer { uid: unsafe { libc::geteuid() }, pid: std::process::id() },
        timeout: Duration::from_secs(30), lifetime: Duration::from_secs(300),
        request_bound: 16_384, response_bound: 16_384,
    }, pidfd()?)?)
}

pub(crate) fn retained_version_dataset_fixture(
    config: OriginalCellQ24MaterialReceiptConfigV1,
    snapshot: LearningIterationSnapshotV1,
    evidence: Vec<SignedLearningEvidenceV1>,
) -> anyhow::Result<(
    OriginalCellQ24DatasetCommandReadbackV1,
    std::thread::JoinHandle<anyhow::Result<usize>>,
)> {
    let binding = wire::context_binding(&config, now()?)?;
    let completed = wire::authenticate_cut(&config, Role::Dataset,
        OriginalCellQ24MaterialCommandReceiptV1 {
            snapshot, evidence, original_context: binding,
        }, now()?)?;
    let (client, server) = UnixStream::pair()?;
    let original = OriginalCellQ24MaterialCommandClientV1 {
        channel: Mutex::new(Some(Channel {
            peer: channel(client)?, next_request_id: 1, execution_requested: true,
        })),
        config: config.clone(), role: Role::Dataset, binding,
        retained: Mutex::new(None),
    };
    let client = original.into_original_dataset_readback(&config)?;
    let mut channel = channel(server)?;
    let server = std::thread::spawn(move || -> anyhow::Result<usize> {
        for request_id in 1..=128 {
            let observed = channel.exchange(|bytes| {
                let request: wire::Request = serde_json::from_slice(bytes)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                request.require_context(&config, Role::Dataset, binding, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if request.action != wire::Action::Readback {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                let result = wire::encode_completed(&config, Role::Dataset, completed.clone(),
                    now().map_err(|_| HostIssuerTransportError::InvalidRequest)?)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                serde_json::to_vec(&wire::Response::from_request(&request, result))
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })?;
            if !observed { return Ok((request_id - 1) as usize); }
        }
        Err(anyhow::anyhow!("bounded explicit Dataset fixture"))
    });
    Ok((client, server))
}
