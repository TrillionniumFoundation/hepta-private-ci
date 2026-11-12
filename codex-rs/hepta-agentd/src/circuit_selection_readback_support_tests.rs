//! Same-UID fixture for the actual original Selector read-only purpose.
use super::*;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_neuron::AnchorWitnessStore;
use std::sync::Arc;
use std::thread::JoinHandle;

pub(crate) fn connection(
    material: OriginalCellQ24MaterialReceiptConfigV1,
) -> anyhow::Result<(
    OriginalCircuitSelectionReadbackConnectionV1,
    HostAuthorityPeerChannel,
)> {
    let (initial_binding, _) =
        OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
    let (stream, server) = UnixStream::pair()?;
    let channel = |stream| -> anyhow::Result<HostAuthorityPeerChannel> {
        Ok(HostAuthorityPeerChannel::from_stream(
            stream,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    // SAFETY: explicit test process credentials only.
                    uid: unsafe { libc::geteuid() },
                    pid: std::process::id(),
                },
                timeout: Duration::from_secs(30),
                lifetime: Duration::from_secs(300),
                request_bound: 16_384,
                response_bound: 16_384,
            },
            crate::learning_iteration_evidence_client::command_test_support::pidfd()?,
        )?)
    };
    Ok((
        OriginalCircuitSelectionReadbackConnectionV1 {
            peer: channel(stream)?,
            material,
            initial_binding,
        },
        channel(server)?,
    ))
}

pub(crate) fn serve<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<crate::OriginalCircuitSelectionCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_original_selection_readback_channel(&mut channel))
}
