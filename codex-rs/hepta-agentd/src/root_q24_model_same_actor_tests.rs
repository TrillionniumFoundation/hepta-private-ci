//! Same-UID negative transport components. The profile below is explicit
//! synthetic public data, and files/owner remain absent. This does not call a
//! successful Root factory constructor or create/qualify a Model owner.

use super::*;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use crate::AgentdRootAuthorityPeer;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

fn pidfd() -> OwnedFd {
    // SAFETY: opens a new owned pidfd for this actual live component process.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(fd >= 0);
    // SAFETY: the successful syscall returned this uniquely owned descriptor.
    unsafe { OwnedFd::from_raw_fd(fd as i32) }
}

fn peer() -> AgentdRootAuthorityPeer {
    let pid = std::process::id();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
    AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
            .unwrap()
            .trim()
            .into(),
        process_start_ticks: stat
            .rsplit_once(") ")
            .unwrap()
            .1
            .split_whitespace()
            .nth(19)
            .unwrap()
            .parse()
            .unwrap(),
    }
}

struct Fixture {
    _directory: tempfile::TempDir,
    factory: AgentdRootQ24ModelFactoryV1,
    server: Option<UnixStream>,
    gate: Arc<SameActorPhaseGate>,
    _other: RequiredSameActorPhaseChannel,
    other_peer: UnixStream,
}

impl Fixture {
    fn new() -> anyhow::Result<Self> {
        let (directory, _, coordinator) =
            crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
        let initial = coordinator.snapshot().clone();
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request,
            &initial.owners,
            LearningUpdateScopeV2::Cell,
            Digest32::of_bytes(b"model-transport-component-rule"),
        )?;
        let digest = Digest32::of_bytes(b"synthetic-model-profile-pin").to_string();
        // Public description only. Zero file pins cannot admit real owner
        // rights and no test treats this description as a creation permit.
        let profile = serde_json::from_value(serde_json::json!({
            "schema_version": 1, "purpose": PURPOSE, "backend": "Q24SingleHeadSgdV1",
            "operation_id": initial.request.operation_id.to_string(),
            "initial_head": initial.head_digest.to_string(),
            "scope_binding": scope.binding().to_string(),
            "proposal_owner_id": initial.owners.proposal.to_string(),
            "process_identity_digest": digest, "writer_proof_digest": digest,
            "journal_slot_binding": digest, "witness_enrollment_binding": digest,
            "local_policy_digest": digest, "registry_epoch": 1,
            "expiry_unix_seconds": initial.request.envelope.expiry_unix_seconds,
            "factory_binding": digest,
            "journal": { "device": 0, "inode": 0 },
            "witness": { "device": 0, "inode": 0 }, "witness_domain": digest
        }))?;
        let gate = SameActorPhaseGate::from_original_deadline(
            SameActorPhaseDeadline::at_original_service_start(Duration::from_secs(10))?,
        )?;
        let (stream, server) = UnixStream::pair()?;
        let phase = gate.retain_required_original_stream(&stream)?;
        // SAFETY: observes, without changing, this process's kernel credential.
        let uid = unsafe { libc::geteuid() };
        let transport = RootObservationStream::from_stream_for_uid(
            stream,
            peer(),
            pidfd(),
            Duration::from_millis(500),
            Duration::from_secs(5),
            uid,
        )?;
        let (other, other_peer) = UnixStream::pair()?;
        let other = gate.retain_required_original_stream(&other)?;
        other_peer.set_read_timeout(Some(Duration::from_secs(2)))?;
        Ok(Self {
            _directory: directory,
            factory: AgentdRootQ24ModelFactoryV1 {
                transport: Some(transport),
                next_request_id: 1,
                profile,
                initial,
                scope,
                generation: Generation::new(1).unwrap(),
                files: None,
                owner: None,
                fenced: false,
                phase: Some(phase),
            },
            server: Some(server),
            gate,
            _other: other,
            other_peer,
        })
    }

    fn assert_closed(&mut self) {
        assert!(self.gate.require_open().is_err());
        assert_eq!(self.other_peer.read(&mut [0]).unwrap(), 0);
        assert!(self.factory.owner.is_none());
        assert!(self.factory.files.is_none());
    }
}

fn receive(server: &mut UnixStream) -> Request {
    let mut length = [0; 4];
    server.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!(length > 0 && length <= 16 * 1024);
    let mut bytes = vec![0; length];
    server.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

#[tokio::test]
async fn phase_model_wrong_semantic_ack_closes_shared_gate_before_any_reuse()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let mut server = fixture.server.take().unwrap();
    let worker = std::thread::spawn(move || {
        server.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        let request = receive(&mut server);
        let response = Response {
            schema: 1,
            operation: PURPOSE.into(),
            request_id: request.request_id,
            binding: Digest32::of_bytes(b"another-model-scope").to_string(),
            reply: Reply {
                lease: FactoryLease {
                    epoch: 1,
                    material: None,
                    revocations: Digest32::of_bytes(b"component-revocations").to_string(),
                },
                newly_bound: false,
            },
        };
        let bytes = serde_json::to_vec(&response).unwrap();
        server.write_all(&(bytes.len() as u32).to_be_bytes()).unwrap();
        server.write_all(&bytes).unwrap();
        assert_eq!(server.read(&mut [0]).unwrap(), 0);
    });
    assert!(fixture.factory.require_current().await.is_err());
    fixture.assert_closed();
    assert!(fixture.factory.fenced);
    assert!(fixture.factory.transport.is_none());
    assert!(fixture.factory.require_current().await.is_err());
    worker.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn phase_model_cancelled_borrowed_observation_closes_all_lanes()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let mut server = fixture.server.take().unwrap();
    let (sent, seen) = tokio::sync::oneshot::channel();
    let (release, released) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
        server.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        let request = receive(&mut server);
        assert!(matches!(request.command, Command::Observe));
        sent.send(()).unwrap();
        released.recv_timeout(Duration::from_secs(2)).unwrap();
        assert_eq!(server.read(&mut [0]).unwrap(), 0);
    });
    let mut pending = Box::pin(fixture.factory.require_current());
    tokio::select! {
        result = &mut pending => panic!("observation finished before held ACK: {result:?}"),
        result = seen => result?,
    }
    drop(pending);
    // The actual borrowed factory remains alive. Cancelling this operation,
    // not dropping its Required owner, must stop the unrelated original lane.
    fixture.assert_closed();
    assert!(fixture.factory.fenced);
    assert!(fixture.factory.transport.is_none());
    assert!(fixture.factory.require_current().await.is_err());
    release.send(())?;
    worker.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn phase_model_constructor_rejects_foreign_files_before_first_observe()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let transport = fixture.factory.transport.take().unwrap();
    let phase = fixture.factory.phase.take().unwrap();
    let result = AgentdRootQ24ModelFactoryV1::from_original_same_actor_handoff(
        transport,
        fixture.factory.profile.clone(),
        fixture.factory.initial.clone(),
        fixture.factory.scope.clone(),
        1,
        (tempfile::tempfile()?, tempfile::tempfile()?),
        phase,
    )
    .await;
    assert!(result.is_err());
    fixture.assert_closed();
    let mut server = fixture.server.take().unwrap();
    server.set_read_timeout(Some(Duration::from_secs(2)))?;
    assert_eq!(server.read(&mut [0])?, 0);
    Ok(())
}
