//! Same-UID mechanism fixture only. The public constructor still requires
//! original external process custody. These held channels retain their first
//! deadlines and serve the actual deferred host, without response replay.
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;

use super::*;
use crate::learning_iteration_evidence_client::command_test_support as transport;

fn pair(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    origin: Origin,
    lifetime: Duration,
) -> anyhow::Result<(
    OriginalCellQ24TrainingCommandConnectionV1,
    HostAuthorityPeerChannel,
)> {
    let (client, server) = UnixStream::pair()?;
    let policy = || HostAuthorityPeerPolicy {
        // SAFETY: explicit same-process fixture credentials.
        peer: HostIssuerPeer {
            uid: unsafe { libc::geteuid() },
            pid: std::process::id(),
        },
        timeout: Duration::from_secs(30).min(lifetime),
        lifetime,
        request_bound: 16_384,
        response_bound: 16_384,
    };
    let peer = HostAuthorityPeerChannel::from_stream(client, policy(), transport::pidfd()?)?;
    let server = HostAuthorityPeerChannel::from_stream(server, policy(), transport::pidfd()?)?;
    let (initial_binding, _) =
        OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
    Ok((
        OriginalCellQ24TrainingCommandConnectionV1 {
            peer,
            material,
            initial_binding,
            origin,
        },
        server,
    ))
}

pub(crate) fn fresh_peer(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    lifetime: Duration,
) -> anyhow::Result<(
    OriginalCellQ24TrainingCommandConnectionV1,
    HostAuthorityPeerChannel,
)> {
    pair(material, Origin::Fresh, lifetime)
}

pub(crate) fn recovered_peer(
    material: OriginalCellQ24MaterialReceiptConfigV1,
    expected: Option<OriginalCellQ24TrainingCommandReceiptV1>,
    lifetime: Duration,
) -> anyhow::Result<(
    OriginalCellQ24TrainingCommandConnectionV1,
    HostAuthorityPeerChannel,
)> {
    pair(material, Origin::Recovered(expected), lifetime)
}
