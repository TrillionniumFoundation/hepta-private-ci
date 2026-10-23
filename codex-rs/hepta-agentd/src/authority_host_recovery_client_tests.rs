//! Owned UID60001 successor: original proof/feed/frontier clients, no activation.
use super::*;
use crate::AgentdRootAuthorityPeer;
use crate::AgentdRootAuthoritySession;
use crate::AgentdRootWriterTrust;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::RootFinalUseFrontierClient;
use codex_hepta_contracts::RootPeerIdentity;
use std::os::fd::OwnedFd;

#[test]
#[ignore = "owned UID60001 helper; invoked only by the Root wrapper parent"]
fn recovered_service_client() {
    // SAFETY: geteuid takes no pointers or borrowed memory.
    assert_eq!(unsafe { libc::geteuid() }, 60001);
    let status = std::fs::read_to_string("/proc/self/status").unwrap();
    assert!(status.lines().any(|line| line == "Uid:\t60001\t60001\t60001\t60001"));
    assert!(status.lines().any(|line| line == "Gid:\t60001\t60001\t60001\t60001"));
    assert!(status.lines().any(|line| line == "NoNewPrivs:\t1"));
    assert!(status.lines().any(|line| line.strip_prefix("Groups:").is_some_and(|v| v.trim().is_empty())));
    for name in ["CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:"] {
        assert!(status.lines().any(|line| line.strip_prefix(name).is_some_and(|v| v.trim() == "0000000000000000")));
    }
    assert_eq!(std::fs::read_dir(std::env::var_os("HEPTA_SERVICE_STATE").unwrap()).unwrap_err().kind(),
        io::ErrorKind::PermissionDenied);
    // A distinct trusted-parent prelude pins the public key before parsing the
    // producer's DTO. Neither value is accepted from a socket request/peer.
    let mut public = [0; 32];
    std::io::stdin().read_exact(&mut public).unwrap();
    let mut length = [0; 4];
    std::io::stdin().read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=crate::HOST_AUTHORITY_BOOTSTRAP_BOUND).contains(&length));
    let mut bytes = vec![0; length];
    std::io::stdin().read_exact(&mut bytes).unwrap();
    let bundle: crate::HostAuthorityPublicBootstrapV1 = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(bundle.schema_version, 1);
    assert_eq!(bundle.operation, crate::HOST_AUTHORITY_BOOTSTRAP_V1);
    assert_eq!(bundle.root.uid, 0);
    assert_eq!(bundle.root.pid, std::env::var("HEPTA_SERVICE_PID").unwrap().parse::<u32>().unwrap());
    assert_eq!(bundle.consumer.uid, 60001);
    assert_eq!(bundle.consumer.pid, std::process::id());
    assert_eq!(bundle.consumer, bundle.checkpoint.peer_lifetime);
    assert_eq!(bundle.issuer_key.verifying_key, public);
    assert_eq!(bundle.writer.registered_agent_id, bundle.registered_identity.agent_id);
    assert_eq!(bundle.writer.spawn_generation, 3);
    assert_eq!(bundle.registered_identity.spawn_generation, 3);
    assert_eq!(bundle.writer.local_lease_generation, 2);
    assert_eq!(bundle.writer_proof.claims.sequence, 2);
    assert_eq!(bundle.checkpoint.phase, CognitiveCheckpointPhase::Current);
    assert_eq!((bundle.checkpoint.counter, bundle.checkpoint.publisher_epoch), (3, 2));
    let runtime = std::path::PathBuf::from(std::env::var_os("HEPTA_SERVICE_RUNTIME").unwrap());
    assert_eq!(bundle.sockets.observation, runtime.join("observation.sock"));
    assert_eq!(bundle.sockets.issuer, runtime.join("issuer.sock"));
    assert_eq!(bundle.sockets.checkpoint, runtime.join("checkpoint.sock"));
    assert_eq!(bundle.sockets.device_frontier, runtime.join("device-frontier.sock"));
    assert_eq!(bundle.sockets.notes_frontier, runtime.join("notes-frontier.sock"));
    // All fixed listeners accept before any worker serves its first frame.
    let observation = connect(&bundle.sockets.observation);
    let issuer = connect(&bundle.sockets.issuer);
    let mut checkpoint = connect(&bundle.sockets.checkpoint);
    let device = connect(&bundle.sockets.device_frontier);
    let notes = connect(&bundle.sockets.notes_frontier);
    let fd: i32 = std::env::var("HEPTA_SERVICE_ROOT_PIDFD").unwrap().parse().unwrap();
    assert_eq!(fd, 198);
    // SAFETY: this descriptor was exclusively transferred by the trusted Root
    // parent before spawning this owned helper. We do not reopen a numeric PID.
    let root = unsafe { OwnedFd::from_raw_fd(fd) };
    let executor = tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build().unwrap();
    executor.block_on(async {
        let writer = &bundle.writer;
        let signer = bundle.issuer_key.key_id.clone();
        let session = AgentdRootAuthoritySession::connect(
            observation, AgentdRootAuthorityPeer { pid:bundle.root.pid, boot_id:bundle.root.boot_id.clone(),
                process_start_ticks:bundle.root.process_start_ticks }, root.try_clone().unwrap(),
            Duration::from_millis(500), Duration::from_secs(20), AgentdRootWriterTrust {
                issuer_id:signer.clone(), verifying_key:public, agent_id:writer.registered_agent_id.clone(),
                spawn_generation:writer.spawn_generation, owner_epoch:writer.owner_epoch,
                local_lease_id:writer.local_lease_id.clone(), local_lease_generation:writer.local_lease_generation,
                authority_lease:writer.authority_lease.clone(),
            },
        ).await.unwrap();
        assert_eq!(session.revocations().unwrap(), bundle.revocations);
        // No recovered owner was installed/attached. A successful protected
        // adoption must never silently activate ordinary business writes.
        assert!(session.verifier().verify(&session.authority(), &writer.registered_agent_id).is_err());
        let mut frontiers = Vec::new();
        for (slot, stream) in [(&bundle.consumers.device, device), (&bundle.consumers.notes, notes)] {
            assert_eq!(slot.owner_id, signer);
            let frontier = RootFinalUseFrontierClient::from_stream(stream, signer.clone(), RootPeerIdentity {
                pid:bundle.root.pid, boot_id:bundle.root.boot_id.clone(), process_start_ticks:bundle.root.process_start_ticks,
            }, root.try_clone().unwrap(), Duration::from_secs(5), Duration::from_secs(20)).unwrap();
            assert_eq!(frontier.load(&signer).unwrap(), slot.frontier);
            assert_eq!(frontier.load("peer-selected-owner"), Err(AuthorityTrustError::Invalid));
            frontiers.push(frontier);
        }
        let provider = AgentdUnixFinalUseGrantProvider::from_stream(issuer, AgentdFinalUseIssuerPeer {
            uid:0, pid:bundle.root.pid,
        }, Duration::from_secs(10)).unwrap();
        let key = ed25519_dalek::VerifyingKey::from_bytes(&public).unwrap();
        for sequence in [3, 4] {
            let grant = provider.request_grant(&binding(writer.registered_agent_id.as_str())).unwrap();
            assert_eq!(grant.grant.signer_id, signer);
            assert_eq!(grant.grant.grant_id, format!("{signer}:1:{sequence}"));
            key.verify(&grant.grant.signing_bytes().unwrap(),
                &ed25519_dalek::Signature::from_slice(&grant.signature).unwrap()).unwrap();
        }
        let response = exchange(&mut checkpoint, &serde_json::json!({"schema_version":1,
            "operation":"runtime.cognitive.checkpoint.v1", "request_id":"00000000000000020000000000000001",
            "command":"read_head", "expected":null, "proposal":null}), /*bound*/ 32 * 1024);
        let response: codex_hepta_memory::CognitiveCheckpointResponse = serde_json::from_value(response).unwrap();
        assert_eq!(response.status, codex_hepta_memory::CognitiveCheckpointStatus::Ack);
        assert_eq!(response.head.unwrap(), bundle.checkpoint);
        assert_eq!(session.revocations().unwrap(), bundle.revocations);
        assert!(session.verifier().verify(&session.authority(), &writer.registered_agent_id).is_err());
        let malformed = serde_json::to_vec(&serde_json::json!({"schema_version":1,
            "operation":"runtime.cognitive.checkpoint.v1", "owner":"peer-selected-owner"})).unwrap();
        checkpoint.write_all(&(malformed.len() as u32).to_be_bytes()).unwrap();
        checkpoint.write_all(&malformed).unwrap();
        let mut first = [0];
        assert_eq!(checkpoint.read(&mut first).unwrap(), 0, "closed DTO must emit no ACK prefix");
        drop(frontiers);
        let clock = session.clock();
        drop(session);
        assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    });
}
