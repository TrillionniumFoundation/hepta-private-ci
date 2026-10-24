//! Actual UID60001 original owners; the sole Root issuer supplies every proof.
use super::*;
use crate::AgentdCognitiveCheckpointPeer;
use crate::AgentdRootAuthorityPeer;
use crate::AgentdRootAuthoritySession;
use crate::AgentdRootWriterTrust;
use crate::AgentdUnixCognitiveCheckpointTransport;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::RootFinalUseFrontierClient;
use codex_hepta_contracts::RootPeerIdentity;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ProductionDurableWriter;
use pretty_assertions::assert_eq;
use std::os::fd::OwnedFd;

fn signal(runtime: &Path, generation: u64, phase: &str, value: serde_json::Value) {
    let path = runtime.join(format!("consumer-local/owner-{generation}-{phase}.json"));
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(path).unwrap();
    file.write_all(&serde_json::to_vec(&value).unwrap()).unwrap();
    file.sync_all().unwrap();
}

fn input<T: serde::de::DeserializeOwned>() -> T {
    let mut length = [0;4]; std::io::stdin().read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=crate::HOST_AUTHORITY_BOOTSTRAP_BOUND).contains(&length));
    let mut bytes = vec![0;length]; std::io::stdin().read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

#[test]
#[ignore = "owned UID60001 canonical generation helper; never a Root top-level test"]
fn canonical_owner_child() {
    // SAFETY: geteuid reads only the actual caller.
    assert_eq!(unsafe { libc::geteuid() }, 60001);
    let status = std::fs::read_to_string("/proc/self/status").unwrap();
    for (name, expected) in [("Uid:","60001 60001 60001 60001"),("Gid:","60001 60001 60001 60001"),
        ("Groups:",""),("NoNewPrivs:","1")] {
        let actual = status.lines().find_map(|line| line.strip_prefix(name)).unwrap()
            .split_whitespace().collect::<Vec<_>>().join(" ");
        assert_eq!(actual, expected);
    }
    for name in ["CapInh:","CapPrm:","CapEff:","CapBnd:","CapAmb:"] {
        let actual = status.lines().find_map(|line| line.strip_prefix(name)).unwrap().trim();
        assert_eq!(actual,"0000000000000000");
    }
    assert_eq!(std::fs::read_dir(std::env::var_os("HEPTA_SERVICE_STATE").unwrap()).unwrap_err().kind(),io::ErrorKind::PermissionDenied);
    let mut public = [0;32]; std::io::stdin().read_exact(&mut public).unwrap();
    let bundle: crate::HostAuthorityPublicBootstrapV1 = input();
    // A controlled trusted-Root fixture prelude carries the actual server
    // receipt, not a client-computed token or a second production wire format.
    let receipt: codex_hepta_memory::CognitiveCheckpointReceipt = input();
    assert_eq!(receipt.head,bundle.checkpoint);
    assert_eq!(bundle.issuer_key.verifying_key,public);
    assert_eq!(bundle.root.uid,0);
    assert_eq!(bundle.root.pid,std::env::var("HEPTA_SERVICE_PID").unwrap().parse::<u32>().unwrap());
    assert_eq!(bundle.consumer.pid,std::process::id());
    assert_eq!(bundle.consumer.uid,60001);
    assert_eq!(bundle.consumer,bundle.checkpoint.peer_lifetime);
    let generation = bundle.writer.local_lease_generation;
    assert!([1,2].contains(&generation));
    assert_eq!(bundle.writer.spawn_generation, if generation==1 {1} else {3});
    let runtime = std::path::PathBuf::from(std::env::var_os("HEPTA_SERVICE_RUNTIME").unwrap());
    let observation = connect(&bundle.sockets.observation);
    let mut issuer = connect(&bundle.sockets.issuer);
    let checkpoint = connect(&bundle.sockets.checkpoint);
    let device = connect(&bundle.sockets.device_frontier);
    let notes = connect(&bundle.sockets.notes_frontier);
    let fd:i32 = std::env::var("HEPTA_SERVICE_ROOT_PIDFD").unwrap().parse().unwrap(); assert_eq!(fd,198);
    // SAFETY: exclusively transferred by this actual Root parent before spawn.
    let root = unsafe { OwnedFd::from_raw_fd(fd) };
    let executor = tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build().unwrap();
    executor.block_on(async {
        let writer = &bundle.writer;
        let session = AgentdRootAuthoritySession::connect(observation,
            AgentdRootAuthorityPeer { pid:bundle.root.pid,boot_id:bundle.root.boot_id.clone(),
                process_start_ticks:bundle.root.process_start_ticks },root.try_clone().unwrap(),
            Duration::from_millis(500),Duration::from_secs(20),AgentdRootWriterTrust {
                issuer_id:bundle.issuer_key.key_id.clone(),verifying_key:public,
                agent_id:writer.registered_agent_id.clone(),spawn_generation:writer.spawn_generation,
                owner_epoch:writer.owner_epoch,local_lease_id:writer.local_lease_id.clone(),
                local_lease_generation:generation,authority_lease:writer.authority_lease.clone(),
            }).await.unwrap();
        let signer = bundle.issuer_key.key_id.clone();
        let mut owners = Vec::new();
        for (slot,stream) in [(&bundle.consumers.device,device),(&bundle.consumers.notes,notes)] {
            assert_eq!(slot.owner_id,signer);
            let frontier = Arc::new(RootFinalUseFrontierClient::from_stream(stream,signer.clone(),
                RootPeerIdentity {pid:bundle.root.pid,boot_id:bundle.root.boot_id.clone(),process_start_ticks:bundle.root.process_start_ticks},
                root.try_clone().unwrap(),Duration::from_secs(5),Duration::from_secs(20)).unwrap());
            owners.push(FinalUseAuthority::open_state_dir_with_issuer_keys(&slot.local_state_dir,signer.clone(),
                vec![FinalUseIssuerTrustKey {key_id:signer.clone(),verifying_key:public,
                    not_before_authority_epoch:bundle.revocations.authority_epoch,
                    not_after_authority_epoch:bundle.revocations.authority_epoch}],
                bundle.revocations.clone(),session.clock(),frontier).unwrap());
        }
        session.activate_final_use_owners(owners).await.unwrap();
        let authority = session.authority();
        let verifier = session.verifier();
        verifier.verify(&authority,&writer.registered_agent_id).unwrap();
        verifier.verify_sender_process_binding(&authority,&writer.registered_agent_id,&writer.local_lease_id,
            generation,writer.spawn_generation).unwrap();
        let layout = bundle.registered_identity.identity().unwrap().layout;
        for entry in std::fs::read_dir("/proc/self/fd").unwrap() {
            if let Ok(path) = std::fs::read_link(entry.unwrap().path()) {
                assert!(!path.starts_with(layout.cognitive_root()),"no inherited owner/source database handle");
                assert!(!path.starts_with(std::path::PathBuf::from(std::env::var_os("HEPTA_SERVICE_STATE").unwrap())),
                    "no inherited protected authority or material descriptor");
            }
        }
        let store = CognitiveStore::open_with_recovery(&layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&receipt.head.last_current),&authority,verifier.as_ref()).await.unwrap();
        assert_eq!(store.recovery_anchor().await.unwrap(),receipt.head.last_current);
        signal(&runtime,generation,"ready",serde_json::json!({"owner_ready":true,"generation":generation,
            "spawn":writer.spawn_generation,"recovered_cut":receipt.head.last_current}));
        let mut go = [0]; std::io::stdin().read_exact(&mut go).unwrap(); assert_eq!(go,[1]);
        let transport = Arc::new(AgentdUnixCognitiveCheckpointTransport::from_stream(checkpoint,
            AgentdCognitiveCheckpointPeer {pid:bundle.root.pid,boot_id:bundle.root.boot_id.clone(),process_start_ticks:bundle.root.process_start_ticks},
            root.try_clone().unwrap(),Duration::from_secs(5),Duration::from_secs(20)).unwrap());
        let (store,coordinator) = store.bind_protected_checkpoint(transport,receipt,Duration::from_secs(5)).await.unwrap();
        let observed = store.clone();
        let production = Arc::new(ProductionDurableWriter::open_with_live_verifier(store,authority,verifier,
            writer.local_lease_id.clone(),generation).await.unwrap());
        let sender = production.objective_sender_for_spawn_generation(coordinator.clone(),Duration::from_secs(5),writer.spawn_generation).unwrap();
        // Original no-ticket startup publication. No Objective request, grant,
        // FinalUse nonce, provider entry, cancellation or external effect exists.
        sender.acknowledge_owner_cut().await.unwrap();
        let terminal = production.release().await.unwrap();
        assert_eq!(terminal.state,"released"); assert_eq!(terminal.generation,generation);
        assert!(production.checkpoint_fenced());
        assert!(production.admit("retired-must-not-enqueue","no-effect","{}").await.is_err());
        let final_cut = production.recovery_anchor().await.unwrap();
        assert_eq!(observed.inspect_local_lease_head(&writer.local_lease_id).await.unwrap().head.unwrap().lease_sha256,terminal.lease_head_digest);
        drop(sender); drop(production); drop(coordinator);
        observed.close().await;
        signal(&runtime,generation,"terminal",serde_json::json!({"terminal":terminal,"cut":final_cut,"owner_closed":true}));
        std::io::stdin().read_exact(&mut go).unwrap(); assert_eq!(go,[2]);
        // End on a definite closed issuer DTO refusal, independent of EOF/pidfd
        // scheduling. This never touches checkpoint Current or consumer state.
        let invalid = b"{\"unexpected\":true}";
        issuer.write_all(&(invalid.len() as u32).to_be_bytes()).unwrap(); issuer.write_all(invalid).unwrap();
        let mut first=[0]; assert_eq!(issuer.read(&mut first).unwrap(),0);
        drop(session);
    });
}
