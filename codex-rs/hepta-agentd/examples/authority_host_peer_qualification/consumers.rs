//! Two original consumers and one canonical signer; no external effect occurs.
use codex_hepta_agentd::AgentdRootAuthorityPeer;
use codex_hepta_agentd::AgentdRootAuthoritySession;
use codex_hepta_agentd::AgentdRootWriterTrust;
use codex_hepta_agentd::HOST_AUTHORITY_BOOTSTRAP_BOUND;
use codex_hepta_agentd::HOST_AUTHORITY_BOOTSTRAP_V1;
use codex_hepta_agentd::HostAuthorityPublicBootstrapV1;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::RootFinalUseFrontierClient;
use codex_hepta_contracts::RootPeerIdentity;
use codex_hepta_contracts::SignedFinalUseGrant;
use std::io::Read;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

pub(super) fn read_bootstrap() -> Result<HostAuthorityPublicBootstrapV1, Box<dyn std::error::Error>>
{
    let mut length = [0; 4];
    std::io::stdin().read_exact(&mut length)?;
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=HOST_AUTHORITY_BOOTSTRAP_BOUND).contains(&length));
    let mut bytes = vec![0; length];
    std::io::stdin().read_exact(&mut bytes)?;
    let bundle: HostAuthorityPublicBootstrapV1 = serde_json::from_slice(&bytes)?;
    assert_eq!(bundle.schema_version, 1);
    assert_eq!(bundle.operation, HOST_AUTHORITY_BOOTSTRAP_V1);
    assert_eq!(bundle.root.uid, 0);
    assert_eq!(
        bundle.root.pid,
        std::env::var("HEPTA_SERVICE_PID")?.parse::<u32>()?
    );
    assert_eq!(bundle.consumer.uid, 60001);
    assert_eq!(bundle.consumer.pid, std::process::id());
    assert_eq!(bundle.consumer, bundle.checkpoint.peer_lifetime);
    assert_eq!(
        bundle.writer.registered_agent_id,
        bundle.registered_identity.agent_id
    );
    assert_eq!(
        bundle.writer.spawn_generation,
        bundle.registered_identity.spawn_generation
    );
    assert_eq!(
        bundle.checkpoint.owner_agent_id,
        bundle.writer.registered_agent_id
    );
    let runtime =
        PathBuf::from(std::env::var_os("HEPTA_SERVICE_RUNTIME").ok_or("missing runtime")?);
    assert_eq!(bundle.sockets.observation, runtime.join("observation.sock"));
    assert_eq!(bundle.sockets.issuer, runtime.join("issuer.sock"));
    assert_eq!(bundle.sockets.checkpoint, runtime.join("checkpoint.sock"));
    assert_eq!(
        bundle.sockets.device_frontier,
        runtime.join("device-frontier.sock")
    );
    assert_eq!(
        bundle.sockets.notes_frontier,
        runtime.join("notes-frontier.sock")
    );
    Ok(bundle)
}

pub(super) fn qualify(
    observation: UnixStream,
    device: UnixStream,
    notes: UnixStream,
    bundle: HostAuthorityPublicBootstrapV1,
    grants: [SignedFinalUseGrant; 2],
    binding: &FinalUseBinding,
) -> Result<(), Box<dyn std::error::Error>> {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let root_pid = bundle.root.pid;
        let boot = bundle.root.boot_id.clone();
        let start = bundle.root.process_start_ticks;
        let writer = &bundle.writer;
        let fd: i32 = std::env::var("HEPTA_SERVICE_ROOT_PIDFD")?.parse()?;
        assert_eq!(fd, 198);
        // SAFETY: the trusted root parent exclusively transferred this one
        // already held pidfd; no path-based descriptor is opened by the child.
        let root = unsafe { OwnedFd::from_raw_fd(fd) };
        let public: [u8; 32] = serde_json::from_str(&std::env::var("HEPTA_SERVICE_PUBLIC_KEY")?)?;
        assert_eq!(public, bundle.issuer_key.verifying_key);
        let signer = bundle.issuer_key.key_id.clone();
        assert_eq!(signer, std::env::var("HEPTA_SERVICE_SIGNER_ID")?);
        assert_eq!(bundle.consumers.device.owner_id, signer);
        assert_eq!(bundle.consumers.notes.owner_id, signer);
        assert!(grants.iter().all(|grant| grant.grant.signer_id == signer));
        let agent = writer.registered_agent_id.clone();
        let session = AgentdRootAuthoritySession::connect(
            observation,
            AgentdRootAuthorityPeer { pid: root_pid, boot_id: boot.clone(), process_start_ticks: start },
            root.try_clone()?, Duration::from_millis(500), Duration::from_secs(20),
            AgentdRootWriterTrust {
                issuer_id: signer.clone(), verifying_key: public,
                agent_id: writer.registered_agent_id.clone(), spawn_generation: writer.spawn_generation,
                owner_epoch: writer.owner_epoch, local_lease_id: writer.local_lease_id.clone(),
                local_lease_generation: writer.local_lease_generation, authority_lease: writer.authority_lease.clone(),
            },
        ).await?;
        let head = session.revocations()?;
        assert_eq!(head, bundle.revocations);
        let local = bundle.consumers.device.local_state_dir.parent().ok_or("missing local parent")?.to_path_buf();
        assert_eq!(bundle.consumers.notes.local_state_dir.parent(), Some(local.as_path()));
        let mut owners = Vec::new();
        let mut frontiers = Vec::new();
        for (slot, stream) in [(&bundle.consumers.device, device), (&bundle.consumers.notes, notes)] {
            let frontier = Arc::new(RootFinalUseFrontierClient::from_stream(
                stream, signer.clone(),
                RootPeerIdentity { pid: root_pid, boot_id: boot.clone(), process_start_ticks: start },
                root.try_clone()?, Duration::from_secs(5), Duration::from_secs(20),
            )?);
            assert_eq!(frontier.load(&signer)?, slot.frontier);
            let path = &slot.local_state_dir;
            std::fs::DirBuilder::new().mode(0o700).create(&path)?;
            let owner = FinalUseAuthority::open_state_dir_with_issuer_keys(
                &path, signer.clone(),
                vec![FinalUseIssuerTrustKey::from(bundle.issuer_key.clone())], head.clone(), session.clock(), frontier.clone(),
            )?;
            assert_eq!(frontier.load(&signer)?, owner.frontier()?);
            assert_eq!(frontier.load("peer-selected-owner"), Err(AuthorityTrustError::Invalid));
            owners.push(owner);
            frontiers.push(frontier);
        }
        session.activate_final_use_owners(owners.clone()).await?;
        session.verifier().verify(&session.authority(), &agent)?;
        let mut committed = Vec::new();
        for ((owner, frontier), grant) in owners.iter().zip(&frontiers).zip(grants) {
            let token = owner.claim(&grant, binding)?;
            owner.enter_verified_use(token, binding)?;
            assert!(matches!(owner.claim(&grant, binding), Err(FinalUseError::AlreadyClaimed)));
            let actual = owner.frontier()?;
            assert_eq!(frontier.load(&signer)?, actual);
            committed.push(actual);
        }
        assert_ne!(committed[0], committed[1]);
        session.verifier().verify(&session.authority(), &agent)?;
        std::fs::write(local.join("qualified-frontiers.json"), serde_json::to_vec(&committed)?)?;
        let clock = session.clock();
        drop(session);
        assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
        println!("{}", serde_json::json!({"qualification":"root_two_original_final_use_consumers","uid":60001,"canonical_signer":signer,"independent_original_frontiers":true,"actual_claim_and_enter":true,"nonce_replay_refused":true,"no_effect":true,"production_ready":false}));
        Ok(())
    })
}
