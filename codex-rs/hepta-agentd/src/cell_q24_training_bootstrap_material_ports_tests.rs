//! Same-UID mechanism connections to the actual original Material command
//! host. Production factories reject this fixture custody; no signatures or
//! response payloads are supplied by these adapters.
use std::thread::JoinHandle;

use super::super::super::super::source;
use super::transport;
use super::*;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCellQ24MaterialSourceConnectionV1;
use crate::learning_iteration_evidence_client::Channel as EvidenceChannel;
use crate::root_observation_stream::RootObservationStream;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;

pub(crate) type Peer = JoinHandle<anyhow::Result<u64>>;

pub(crate) fn commands(
    fixture: &MaterialCommandFixture,
    role: Role,
) -> anyhow::Result<(OriginalCellQ24MaterialCommandClientV1, Peer)> {
    transport::connected(fixture, role, Mode::ExecuteOnce, None, Effect::Original)
}

fn policy(timeout: Duration, lifetime: Duration) -> HostAuthorityPeerPolicy {
    HostAuthorityPeerPolicy {
        // SAFETY: explicit same-process mechanism fixture only.
        peer: HostIssuerPeer {
            uid: unsafe { libc::geteuid() },
            pid: std::process::id(),
        },
        timeout,
        lifetime,
        request_bound: 16_384,
        response_bound: 16_384,
    }
}

pub(crate) fn source_connection(
    fixture: &MaterialCommandFixture,
    lifetime: Duration,
) -> anyhow::Result<(OriginalCellQ24MaterialSourceConnectionV1, Peer)> {
    let host = Arc::clone(fixture.host.as_ref().expect("same original Material pair"));
    let (client, server) = UnixStream::pair()?;
    let timeout = Duration::from_millis(500).min(lifetime);
    let transport = RootObservationStream::from_stream_for_uid(
        client,
        transport::identity()?,
        transport::pidfd()?,
        timeout,
        lifetime,
        policy(timeout, lifetime).peer.uid,
    )?;
    let mut channel = HostAuthorityPeerChannel::from_stream(
        server,
        policy(timeout, lifetime),
        transport::pidfd()?,
    )?;
    let connection = source::retained_connection_fixture(
        transport,
        fixture.config.initial.clone(),
        fixture.config.scope.clone(),
        fixture.training_baseline(),
    );
    let peer = std::thread::spawn(move || {
        let mut next = 1;
        for count in 0..128_u64 {
            let mut original_error = None;
            let exchanged = channel.exchange(|bytes| {
                source::original_material_response_for_bootstrap(&host.original, &mut next, bytes)
                    .map_err(|error| {
                        original_error = Some(error);
                        HostIssuerTransportError::InvalidRequest
                    })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(count),
                Err(error) => {
                    return Err(original_error
                        .map(anyhow::Error::from)
                        .unwrap_or_else(|| anyhow::Error::from(error)));
                }
            }
        }
        anyhow::bail!("bounded original Material source fixture")
    });
    Ok((connection, peer))
}

pub(crate) fn evidence(
    fixture: &MaterialCommandFixture,
    role: Role,
) -> anyhow::Result<(LearningIterationEvidenceClientV1, Peer)> {
    let host = Arc::clone(fixture.host.as_ref().expect("same original Material pair"));
    let (client, server) = UnixStream::pair()?;
    let timeout = Duration::from_millis(500);
    let lifetime = Duration::from_secs(300);
    let transport = RootObservationStream::from_stream_for_uid(
        client,
        transport::identity()?,
        transport::pidfd()?,
        timeout,
        lifetime,
        policy(timeout, lifetime).peer.uid,
    )?;
    let mut channel = HostAuthorityPeerChannel::from_stream(
        server,
        policy(timeout, lifetime),
        transport::pidfd()?,
    )?;
    let owner = LearningIterationEvidenceClientV1 {
        command: None,
        channel: Mutex::new(Some(EvidenceChannel {
            transport,
            next_request_id: 1,
        })),
        initial: fixture.config.initial.clone(),
        actor_id: fixture.config.initial.owners.owner(role.stage()).clone(),
        verifier: fixture.config.verifier.clone(),
    };
    let peer = std::thread::spawn(move || {
        let mut next = 1;
        for count in 0..128_u64 {
            let exchanged = channel.exchange(|bytes| {
                host.original
                    .respond(role, &mut next, bytes)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })?;
            if !exchanged {
                return Ok(count);
            }
        }
        anyhow::bail!("bounded original Material evidence fixture")
    });
    Ok((owner, peer))
}

pub(crate) fn finish(peer: Peer) -> anyhow::Result<u64> {
    peer.join()
        .map_err(|_| anyhow::anyhow!("original Material fixture panicked"))?
}
