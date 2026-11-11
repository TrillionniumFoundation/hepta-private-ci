//! Real Material journals and framing with explicit test-only same-UID transport.
//! Public service/client constructors still reject that custody. These fixtures
//! do not establish external-host deployment, independent operators or Root cold
//! restart; the exact original signatures and all source bytes remain observable.

use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::thread::JoinHandle;

use codex_hepta_contracts::HostIssuerPeer;
use pretty_assertions::assert_eq;

use super::*;
use super::super::Channel;
use super::super::LearningIterationEvidenceClientV1;
use crate::AgentdRootAuthorityPeer;
use crate::cell_q24_material_receipt_owner::ReadbackServiceFixture;
use crate::root_observation_stream::RootObservationStream;

type Role = OriginalCellQ24MaterialEvidenceRoleV1;

fn pidfd() -> anyhow::Result<OwnedFd> {
    // SAFETY: pin this live fixture process and own the newly returned FD.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(fd >= 0, "{}", std::io::Error::last_os_error());
    Ok(unsafe { OwnedFd::from_raw_fd(fd as i32) })
}

fn peer() -> anyhow::Result<AgentdRootAuthorityPeer> {
    let pid = std::process::id();
    let status = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    Ok(AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim().into(),
        process_start_ticks: status.rsplit_once(") ")
            .ok_or_else(|| anyhow::anyhow!("fixture process stat"))?.1.split_whitespace()
            .nth(19).ok_or_else(|| anyhow::anyhow!("fixture process start"))?.parse()?,
    })
}

fn policy() -> HostAuthorityPeerPolicy {
    HostAuthorityPeerPolicy {
        peer: HostIssuerPeer {
            // SAFETY: observe only the fixture process's UID.
            uid: unsafe { libc::getuid() },
            pid: std::process::id(),
        },
        timeout: Duration::from_millis(500),
        lifetime: Duration::from_secs(30),
        request_bound: 16 * 1024,
        response_bound: 16 * 1024,
    }
}

fn request(f: &ReadbackServiceFixture, role: Role, request_id: u64) -> wire::Request {
    let receipt = match role {
        Role::Experience => &f.experience_receipt,
        Role::Dataset => &f.dataset.receipts[1],
    };
    wire::Request {
        schema: 1,
        operation: wire::OPERATION.into(),
        request_id,
        binding: f.initial.head_digest.to_string(),
        snapshot_head: f.dataset.head_digest.to_string(),
        operation_id: receipt.operation_id.to_string(),
        actor_id: receipt.actor_id.to_string(),
        predecessor: receipt.predecessor.to_string(),
        receipt_digest: Digest32::of_bytes(
            &learning_iteration_receipt_signing_bytes_v1(receipt).expect("original fixture receipt"),
        ).to_string(),
    }
}

fn reply(
    f: &ReadbackServiceFixture,
    role: Role,
    next: &mut u64,
    request: &wire::Request,
) -> Result<wire::Response, Error> {
    let bytes = f.service.as_ref().expect("original fixture owner")
        .respond(role, next, &serde_json::to_vec(request)?)?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn connected_fixture(
    f: &ReadbackServiceFixture,
    role: Role,
) -> anyhow::Result<(LearningIterationEvidenceClientV1, JoinHandle<Result<(), HostIssuerTransportError>>)> {
    let owner = Arc::clone(f.service.as_ref().expect("original service"));
    let (client, server) = UnixStream::pair()?;
    let transport = RootObservationStream::from_stream_for_uid(
        client, peer()?, pidfd()?, Duration::from_millis(500), Duration::from_secs(30),
        policy().peer.uid,
    )?;
    let original_pidfd = pidfd()?;
    let thread = std::thread::spawn(move || {
        // Explicit mechanism fixture: production serve_readback refuses this UID.
        let mut channel = HostAuthorityPeerChannel::from_stream(server, policy(), original_pidfd)?;
        let mut next = 1;
        while channel.exchange(|bytes| owner.respond(role, &mut next, bytes)
            .map_err(|_| HostIssuerTransportError::Unavailable))? {}
        Ok(())
    });
    let client = LearningIterationEvidenceClientV1 {
        channel: Mutex::new(Some(Channel { transport, next_request_id: 1 })),
        initial: f.initial.clone(),
        actor_id: f.initial.owners.owner(role.stage()).clone(),
        verifier: f.config.verifier.clone(),
    };
    Ok((client, thread))
}

fn finish(
    client: LearningIterationEvidenceClientV1,
    thread: JoinHandle<Result<(), HostIssuerTransportError>>,
) -> anyhow::Result<()> {
    drop(client);
    thread.join().map_err(|_| anyhow::anyhow!("original fixture service panicked"))??;
    Ok(())
}

#[tokio::test]
async fn material_readback_service_returns_original_signatures_and_cold_rereads() -> anyhow::Result<()> {
    let mut f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    for role in [Role::Experience, Role::Dataset] {
        let (client, thread) = connected_fixture(&f, role)?;
        let receipt = match role {
            Role::Experience => &f.experience_receipt,
            Role::Dataset => &f.dataset.receipts[1],
        };
        let expected = match role {
            Role::Experience => &f.experience_attestation,
            Role::Dataset => f.dataset_attestation.as_ref().expect("completed Dataset"),
        };
        let first = client.readback(&f.dataset, receipt).await?;
        let second = client.readback(&f.dataset, receipt).await?;
        assert_eq!(&first, expected);
        assert_eq!(second, first);
        finish(client, thread)?;
        assert_eq!(f.bytes()?, before);
    }
    f.reopen()?;
    for role in [Role::Experience, Role::Dataset] {
        let mut next = 1;
        let response = reply(&f, role, &mut next, &request(&f, role, 1))?;
        let signed = response.evidence.decode()?;
        let expected = match role {
            Role::Experience => &f.experience_attestation,
            Role::Dataset => f.dataset_attestation.as_ref().expect("completed Dataset"),
        };
        assert_eq!(&signed, expected);
        assert_eq!(next, 2);
    }
    assert_eq!(f.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn material_readback_service_refuses_request_rebinding_and_replay_without_writes() -> anyhow::Result<()> {
    let f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    for field in ["operation", "binding", "operation_id", "actor_id", "predecessor", "receipt_digest", "snapshot_head"] {
        let mut encoded = serde_json::to_value(request(&f, Role::Dataset, 1))?;
        encoded[field] = serde_json::Value::String(Digest32::of_bytes(b"substituted").to_string());
        let mut next = 1;
        assert!(matches!(
            f.service.as_ref().expect("owner").respond(Role::Dataset, &mut next, &serde_json::to_vec(&encoded)?),
            Err(Error::Request)
        ));
        assert_eq!(next, 1);
        assert_eq!(f.bytes()?, before);
    }
    for field in ["payload", "signature", "snapshot", "observation"] {
        let mut encoded = serde_json::to_value(request(&f, Role::Dataset, 1))?;
        encoded[field] = serde_json::Value::String("caller supplied".into());
        assert!(matches!(
            f.service.as_ref().expect("owner").respond(Role::Dataset, &mut 1, &serde_json::to_vec(&encoded)?),
            Err(Error::Encoding(_))
        ));
    }
    let original = request(&f, Role::Experience, 1);
    let mut next = 1;
    let response = reply(&f, Role::Experience, &mut next, &original)?;
    assert_eq!(response.evidence.decode()?, f.experience_attestation);
    assert!(matches!(reply(&f, Role::Experience, &mut next, &original), Err(Error::Request)));
    assert_eq!(next, 2);
    assert_eq!(f.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn material_readback_service_refuses_withdrawn_source_and_busy_ledger() -> anyhow::Result<()> {
    let mut f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    let query = request(&f, Role::Dataset, 1);
    {
        let held = f.ledger.lock().expect("original unique ledger");
        assert!(matches!(reply(&f, Role::Dataset, &mut 1, &query), Err(Error::Unavailable)));
        drop(held);
    }
    assert_eq!(f.bytes()?, before);
    reply(&f, Role::Dataset, &mut 1, &query)?;
    f.withdraw()?;
    assert!(matches!(
        reply(&f, Role::Dataset, &mut 1, &query),
        Err(Error::Material(OriginalCellQ24MaterialReceiptErrorV1::Material(_)))
    ));
    assert_eq!(f.bytes()?, before);
    f.reopen()?;
    assert!(matches!(
        reply(&f, Role::Dataset, &mut 1, &query),
        Err(Error::Material(OriginalCellQ24MaterialReceiptErrorV1::Material(_)))
    ));
    assert_eq!(f.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn material_readback_service_never_finishes_missing_dataset() -> anyhow::Result<()> {
    let mut f = ReadbackServiceFixture::new(false).await?;
    let before = f.bytes()?;
    let query = request(&f, Role::Experience, 1);
    assert!(matches!(
        reply(&f, Role::Experience, &mut 1, &query),
        Err(Error::Material(OriginalCellQ24MaterialReceiptErrorV1::Owner(_)))
    ));
    assert_eq!(f.bytes()?, before);
    f.reopen()?;
    assert!(matches!(
        reply(&f, Role::Experience, &mut 1, &query),
        Err(Error::Material(OriginalCellQ24MaterialReceiptErrorV1::Owner(_)))
    ));
    assert_eq!(f.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn material_readback_service_rejects_same_uid_peer_and_widened_transport() -> anyhow::Result<()> {
    let f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    let owner = f.service.as_ref().expect("owner");
    let mut policies = vec![policy()];
    let mut timeout = policy();
    timeout.peer.uid = timeout.peer.uid.wrapping_add(1);
    timeout.peer.pid += 1;
    timeout.timeout = Duration::from_millis(501);
    policies.push(timeout);
    let mut lifetime = timeout;
    lifetime.timeout = Duration::from_millis(500);
    lifetime.lifetime = Duration::from_secs(301);
    policies.push(lifetime);
    for policy in policies {
        let (server, peer) = UnixStream::pair()?;
        assert!(matches!(owner.serve_readback(Role::Dataset, server, policy, pidfd()?), Err(Error::Request)));
        drop(peer);
        assert_eq!(f.bytes()?, before);
    }
    Ok(())
}

#[tokio::test]
async fn material_readback_service_failed_frame_permanently_consumes_channel() -> anyhow::Result<()> {
    let f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    let owner = Arc::clone(f.service.as_ref().expect("owner"));
    let wrong_role = serde_json::to_vec(&request(&f, Role::Dataset, 1))?;
    let (mut client, server) = UnixStream::pair()?;
    let original_pidfd = pidfd()?;
    let thread = std::thread::spawn(move || -> anyhow::Result<()> {
        let mut channel = HostAuthorityPeerChannel::from_stream(server, policy(), original_pidfd)?;
        let mut next = 1;
        assert!(matches!(
            channel.exchange(|bytes| owner.respond(Role::Experience, &mut next, bytes)
                .map_err(|_| HostIssuerTransportError::Unavailable)),
            Err(HostIssuerTransportError::Unavailable)
        ));
        assert!(matches!(channel.exchange(|_| Ok(vec![1])), Err(HostIssuerTransportError::Closed)));
        assert_eq!(next, 1);
        Ok(())
    });
    client.set_read_timeout(Some(Duration::from_secs(2)))?;
    client.write_all(&(wrong_role.len() as u32).to_be_bytes())?;
    client.write_all(&wrong_role)?;
    let mut byte = [0];
    assert_eq!(client.read(&mut byte)?, 0);
    drop(client);
    thread.join().map_err(|_| anyhow::anyhow!("fixture service panicked"))??;
    assert_eq!(f.bytes()?, before);
    Ok(())
}
