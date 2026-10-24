//! Two original consumers and one canonical signer; no external effect occurs.
use codex_hepta_authority_client::AgentdRootAuthorityPeer;
use codex_hepta_authority_client::AgentdRootAuthoritySession;
use codex_hepta_authority_client::AgentdRootWriterTrust;
use codex_hepta_authority_types::HOST_AUTHORITY_BOOTSTRAP_BOUND;
use codex_hepta_authority_types::HOST_AUTHORITY_BOOTSTRAP_V1;
use codex_hepta_authority_types::HostAuthorityPublicBootstrapV1;
use codex_hepta_authority_types::ProductionAuthorityLease;
use codex_hepta_authority_types::ProductionAuthorityVerifier;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::RootFinalUseFrontierClient;
use codex_hepta_contracts::RootPeerIdentity;
use codex_hepta_contracts::SignedFinalUseGrant;
use std::future::Future;
use std::io::Read;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::pin::Pin;
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

type QualificationError = Box<dyn std::error::Error + Send + Sync>;

struct RegisteredConsumers {
    agent: codex_hepta_contracts::AgentId,
    signer: String,
    local: PathBuf,
    owners: Vec<FinalUseAuthority>,
    frontiers: Vec<Arc<RootFinalUseFrontierClient>>,
}

pub(super) fn qualify(
    observation: UnixStream,
    device: UnixStream,
    notes: UnixStream,
    bundle: HostAuthorityPublicBootstrapV1,
    grants: [SignedFinalUseGrant; 2],
    binding: &FinalUseBinding,
) -> Result<(), Box<dyn std::error::Error>> {
    let runtime = tokio::runtime::LocalRuntime::new()?;
    // Erase the large qualification future before the runtime boundary, so
    // each runtime wrapper uses the same poll implementation.
    let qualification: Pin<Box<dyn Future<Output = Result<(), QualificationError>> + '_>> =
        Box::pin(qualify_with_live_feed(
            observation,
            device,
            notes,
            bundle,
            grants,
            binding,
        ));
    runtime
        .block_on(qualification)
        .map_err(|error| error as Box<dyn std::error::Error>)
}

async fn qualify_with_live_feed(
    observation: UnixStream,
    device: UnixStream,
    notes: UnixStream,
    bundle: HostAuthorityPublicBootstrapV1,
    grants: [SignedFinalUseGrant; 2],
    binding: &FinalUseBinding,
) -> Result<(), QualificationError> {
    let bundle = Box::new(bundle);
    let root_pid = bundle.root.pid;
    let boot = bundle.root.boot_id.clone();
    let start = bundle.root.process_start_ticks;
    let writer = &bundle.writer;
    let fd: i32 = std::env::var("HEPTA_SERVICE_ROOT_PIDFD")?.parse()?;
    assert_eq!(fd, 198);
    // SAFETY: the trusted root parent exclusively transferred this one
    // already held pidfd; no path-based descriptor is opened by the child.
    let root = unsafe { OwnedFd::from_raw_fd(fd) };
    let public: [u8; 32] =
        serde_json::from_slice(std::env::var("HEPTA_SERVICE_PUBLIC_KEY")?.as_bytes())?;
    assert_eq!(public, bundle.issuer_key.verifying_key);
    let signer = bundle.issuer_key.key_id.clone();
    assert_eq!(signer, std::env::var("HEPTA_SERVICE_SIGNER_ID")?);
    assert_eq!(bundle.consumers.device.owner_id, signer);
    assert_eq!(bundle.consumers.notes.owner_id, signer);
    assert!(grants.iter().all(|grant| grant.grant.signer_id == signer));
    let agent = writer.registered_agent_id.clone();
    let session = AgentdRootAuthoritySession::connect(
        observation,
        AgentdRootAuthorityPeer {
            pid: root_pid,
            boot_id: boot.clone(),
            process_start_ticks: start,
        },
        root.try_clone()?,
        Duration::from_millis(500),
        Duration::from_secs(20),
        AgentdRootWriterTrust {
            issuer_id: signer.clone(),
            verifying_key: public,
            agent_id: writer.registered_agent_id.clone(),
            spawn_generation: writer.spawn_generation,
            owner_epoch: writer.owner_epoch,
            local_lease_id: writer.local_lease_id.clone(),
            local_lease_generation: writer.local_lease_generation,
            authority_lease: writer.authority_lease.clone(),
        },
    )
    .await?;
    let head = session.revocations()?;
    assert_eq!(head, bundle.revocations);
    let clock = session.clock();
    let owner_clock = Arc::clone(&clock);
    // Blocking frontier/file operations must not starve the original
    // background observation feed on the current-thread reactor.
    let consumers = tokio::task::spawn_blocking(move || {
        open_registered_consumers(
            *bundle,
            [device, notes],
            root,
            head,
            owner_clock,
            signer,
            agent,
        )
    })
    .await??;
    session
        .activate_final_use_owners(consumers.owners.clone())
        .await?;
    let verifier = session.verifier();
    let authority = session.authority();
    let binding = binding.clone();
    let signer = tokio::task::spawn_blocking(move || {
        claim_and_enter(consumers, grants, binding, verifier, authority)
    })
    .await??;
    drop(session);
    assert_eq!(clock.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    println!(
        "{}",
        serde_json::json!({"qualification":"root_two_original_final_use_consumers","uid":60001,"canonical_signer":signer,"independent_original_frontiers":true,"actual_claim_and_enter":true,"nonce_replay_refused":true,"no_effect":true,"production_ready":false})
    );
    Ok(())
}

#[inline(never)]
fn open_registered_consumers(
    bundle: HostAuthorityPublicBootstrapV1,
    streams: [UnixStream; 2],
    root: OwnedFd,
    head: FinalUseRevocations,
    clock: Arc<dyn AuthorityClock>,
    signer: String,
    agent: codex_hepta_contracts::AgentId,
) -> Result<RegisteredConsumers, QualificationError> {
    let root_pid = bundle.root.pid;
    let boot = bundle.root.boot_id.clone();
    let start = bundle.root.process_start_ticks;
    let local = bundle
        .consumers
        .device
        .local_state_dir
        .parent()
        .ok_or("missing local parent")?
        .to_path_buf();
    assert_eq!(
        bundle.consumers.notes.local_state_dir.parent(),
        Some(local.as_path())
    );
    let mut owners = Vec::new();
    let mut frontiers = Vec::new();
    for (slot, stream) in [&bundle.consumers.device, &bundle.consumers.notes]
        .into_iter()
        .zip(streams)
    {
        let frontier = Arc::new(RootFinalUseFrontierClient::from_stream(
            stream,
            signer.clone(),
            RootPeerIdentity {
                pid: root_pid,
                boot_id: boot.clone(),
                process_start_ticks: start,
            },
            root.try_clone()?,
            Duration::from_secs(5),
            Duration::from_secs(20),
        )?);
        assert_eq!(frontier.load(&signer)?, slot.frontier);
        let path = &slot.local_state_dir;
        std::fs::DirBuilder::new().mode(0o700).create(path)?;
        let owner = FinalUseAuthority::open_state_dir_with_issuer_keys(
            path,
            signer.clone(),
            vec![FinalUseIssuerTrustKey::from(bundle.issuer_key.clone())],
            head.clone(),
            Arc::clone(&clock),
            frontier.clone(),
        )?;
        assert_eq!(frontier.load(&signer)?, owner.frontier()?);
        assert_eq!(
            frontier.load("peer-selected-owner"),
            Err(AuthorityTrustError::Invalid)
        );
        owners.push(owner);
        frontiers.push(frontier);
    }
    Ok(RegisteredConsumers {
        agent,
        signer,
        local,
        owners,
        frontiers,
    })
}

#[inline(never)]
fn claim_and_enter(
    consumers: RegisteredConsumers,
    grants: [SignedFinalUseGrant; 2],
    binding: FinalUseBinding,
    verifier: Arc<dyn ProductionAuthorityVerifier>,
    authority: ProductionAuthorityLease,
) -> Result<String, QualificationError> {
    let RegisteredConsumers {
        agent,
        signer,
        local,
        owners,
        frontiers,
    } = consumers;
    verifier.verify(&authority, &agent)?;
    let mut committed = Vec::new();
    for ((owner, frontier), grant) in owners.iter().zip(&frontiers).zip(grants) {
        let token = owner.claim(&grant, &binding)?;
        owner.enter_verified_use(token, &binding)?;
        assert!(matches!(
            owner.claim(&grant, &binding),
            Err(FinalUseError::AlreadyClaimed)
        ));
        let actual = owner.frontier()?;
        assert_eq!(frontier.load(&signer)?, actual);
        committed.push(actual);
    }
    assert_ne!(committed[0], committed[1]);
    verifier.verify(&authority, &agent)?;
    std::fs::write(
        local.join("qualified-frontiers.json"),
        serde_json::to_vec(&committed)?,
    )?;
    Ok(signer)
}
