//! Explicit same-process framing fixture for the new read-only purpose.
//! Only these tests bypass public UID admission; owners and file reads are real.
use super::*;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;

pub(in crate::learning_iteration_evidence_client::training_command) fn connection(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    lifetime: Duration,
) -> anyhow::Result<(
    OriginalCellQ24TrainingReadbackConnectionV1,
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
                    // SAFETY: the fixture observes its own credentials.
                    uid: unsafe { libc::geteuid() },
                    pid: std::process::id(),
                },
                timeout: Duration::from_secs(30),
                lifetime,
                request_bound: 16_384,
                response_bound: 16_384,
            },
            crate::learning_iteration_evidence_client::command_test_support::pidfd()?,
        )?)
    };
    Ok((
        OriginalCellQ24TrainingReadbackConnectionV1 {
            peer: channel(stream)?,
            material,
            initial_binding,
        },
        channel(server)?,
    ))
}
