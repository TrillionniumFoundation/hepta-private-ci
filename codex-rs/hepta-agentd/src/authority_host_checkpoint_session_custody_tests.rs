//! Controlled same-UID original Root composition and real registered File.
//! The synthetic Current peer uses the original transition functions; it is
//! not a deployed Root, material owner, model, human grant or effect receipt.

use super::*;
use crate::AgentdConfig;
use crate::AgentdRootProductionInputs;
use crate::HostAuthorityFiveLanePathsV1;
use crate::HostAuthorityPublicBootstrapV1;
use crate::HostAuthorityPublicConsumerV1;
use crate::HostAuthorityPublicConsumersV1;
use crate::HostAuthorityPublicIssuerKeyV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityWriterRegistration;
use crate::root_authority_session::tests::connected_with_unix_time;
use crate::root_authority_session::tests::observation_worker;
use crate::root_authority_session::tests::original_config;
use crate::root_authority_session::tests::owner;
use crate::root_writer_proof::tests::fixture;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProductionDispatchFuture;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionTargetOutcome;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::sync::atomic::AtomicUsize;
use std::time::Duration;

struct NoEffect(AtomicUsize);
impl ProductionOutboxTarget for NoEffect {
    fn dispatch<'a>(&'a self, _: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            ProductionTargetOutcome::Rejected {
                reason: "custody fixture permits no effect".into(),
            }
        })
    }
}
impl FinalUseProductionOutboxTarget for NoEffect {
    fn destination_id(&self) -> &str {
        "root-session-custody-fixture"
    }
}

fn takes_same_lock(file: &File) -> Result<bool, Box<dyn Error>> {
    match file.try_lock() {
        Ok(()) => {
            file.unlock()?;
            Ok(true)
        }
        Err(std::fs::TryLockError::WouldBlock) => Ok(false),
        Err(std::fs::TryLockError::Error(error)) => Err(error.into()),
    }
}

// This fixture exercises the original JSON client with a real same-UID peer.
// Durable publication provenance is outside this File-lifetime unit scope.
fn serve_checkpoint(
    mut stream: UnixStream,
    mut head: CognitiveCheckpointHead,
) -> Result<(), Box<dyn Error + Send + Sync>> {
    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
    let registration = HostCognitiveCheckpointRegistration {
        owner_agent_id: head.owner_agent_id.clone(),
        publisher_epoch: head.publisher_epoch,
        writer_binding: head.writer_binding.clone(),
        peer_lifetime: head.peer_lifetime.clone(),
    };
    loop {
        let mut prefix = [0; 4];
        if let Err(error) = stream.read_exact(&mut prefix) {
            return if matches!(
                error.kind(),
                std::io::ErrorKind::UnexpectedEof | std::io::ErrorKind::ConnectionReset
            ) {
                Ok(())
            } else {
                Err(error.into())
            };
        }
        let count = u32::from_be_bytes(prefix) as usize;
        assert!(count > 0 && count <= COGNITIVE_CHECKPOINT_FRAME_LIMIT);
        let mut bytes = vec![0; count];
        stream.read_exact(&mut bytes)?;
        let request: CognitiveCheckpointRequest = serde_json::from_slice(&bytes)?;
        eprintln!(
            "custody checkpoint peer command={:?} bytes={}",
            request.command,
            bytes.len()
        );
        assert_eq!(request.operation, "runtime.cognitive.checkpoint.v1");
        if request.command != CognitiveCheckpointCommand::ReadHead {
            assert_eq!(request.command, CognitiveCheckpointCommand::BeginWrites);
            let token = token_for(&head)?;
            assert_eq!(request.expected, Some(token.clone()));
            let (_, sequence) =
                request_sequence(&request.request_id).ok_or("invalid fixture request ID")?;
            head = advance(
                &registration,
                &head,
                &request,
                Sha256Digest::for_bytes(&bytes),
                token,
                sequence,
            )
            .map_err(|error| format!("original transition refused: {error:?}"))?;
        }
        let response = CognitiveCheckpointResponse {
            schema_version: 1,
            request_id: request.request_id,
            status: CognitiveCheckpointStatus::Ack,
            reason: None,
            token: Some(token_for(&head)?),
            head: Some(head.clone()),
        };
        let bytes = serde_json::to_vec(&response)?;
        stream.write_all(&u32::try_from(bytes.len())?.to_be_bytes())?;
        stream.write_all(&bytes)?;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn escaped_original_root_session_and_live_verifier_retain_same_registered_file()
-> Result<(), Box<dyn Error>> {
    eprintln!(
        "root-session-custody-elf {}",
        std::env::current_exe()?.display()
    );
    let directory = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let path = directory.path().canonicalize()?;
    let (mut trust, mut proof) = fixture();
    // This case opens a genuinely fresh original store. Its first local lease
    // must use generation 1; the process remains registered generation 3.
    trust.local_lease_generation = 1;
    proof.claims.local_lease_generation = 1;
    let unix_base_ms = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?;
    // Original 29,999ms signed fixture interval; only its origin moves to the
    // actual wall clock required by the original production writer validator.
    proof.claims.authority_lease.issued_at_unix_ms = unix_base_ms - 1_000;
    proof.claims.authority_lease.expires_at_unix_ms = unix_base_ms + 28_999;
    proof.claims.authority_lease_sha256 =
        Sha256Digest::for_bytes(&serde_json::to_vec(&proof.claims.authority_lease)?);
    trust.authority_lease = proof.claims.authority_lease.clone();
    proof.signature_hex = SigningKey::from_bytes(&[47; 32])
        .sign(&proof.claims.signing_bytes()?)
        .to_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    let mut config = original_config(&path, &trust)?;
    let identity = config.identity().clone();
    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(identity.layout.writer_lock())?;
    let before = contender.metadata()?;
    assert!(!takes_same_lock(&contender)?);
    let (session, _, root_peer, key) =
        connected_with_unix_time(trust.clone(), proof.clone(), unix_base_ms).await;
    let worker = observation_worker(&session);
    let (device, _, device_dir) = owner(&session, key);
    let (notes, _, notes_dir) = owner(&session, key);
    session
        .activate_final_use_owners(vec![device.clone(), notes.clone()])
        .await?;
    let authority = session.authority();
    session.verifier().verify(&authority, &identity.agent_id)?;
    let fresh = CognitiveStore::open(&identity.layout).await?;
    let cut = fresh.recovery_anchor().await?;
    fresh.close().await;
    // SAFETY: geteuid only samples this fixture process credential.
    let peer_lifetime = CognitiveCheckpointPeerLifetime {
        uid: unsafe { libc::geteuid() },
        pid: std::process::id(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: std::fs::read_to_string("/proc/self/stat")?
            .rsplit_once(") ")
            .ok_or("missing actual fixture stat delimiter")?
            .1
            .split_whitespace()
            .nth(19)
            .ok_or("missing actual fixture birth")?
            .parse()?,
    };
    let head = CognitiveCheckpointHead {
        schema_version: 1,
        owner_agent_id: identity.agent_id.clone(),
        publisher_epoch: 1,
        counter: 1,
        last_mutation_sequence: 0,
        writer_binding: CognitiveCheckpointWriterBinding {
            lease_id: trust.local_lease_id.clone(),
            generation: trust.local_lease_generation,
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            authority_grant_digest: authority.grant_digest.clone(),
            fencing_token_digest: authority.fencing_token_digest()?,
            expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
        },
        peer_lifetime: peer_lifetime.clone(),
        phase: CognitiveCheckpointPhase::Current,
        last_current: cut,
        proposal: None,
        last_request: None,
    };
    let (transport, checkpoint_peer) =
        crate::cognitive_checkpoint_unix::tests::fixture(Duration::from_millis(300));
    let peer_head = head.clone();
    let checkpoint_worker = std::thread::spawn(move || {
        let result = serve_checkpoint(checkpoint_peer, peer_head);
        eprintln!("custody checkpoint peer retired: {result:?}");
        result
    });
    let checkpoint = transport.into_protected_inputs(head.clone()).await?;
    let (issuer_client, mut issuer_peer) = UnixStream::pair()?;
    let grants = Arc::new(crate::AgentdUnixFinalUseGrantProvider::from_stream(
        issuer_client,
        crate::AgentdFinalUseIssuerPeer {
            uid: peer_lifetime.uid,
            pid: peer_lifetime.pid,
        },
        Duration::from_millis(300),
    )?);
    let frontier =
        codex_hepta_contracts::FinalUseFrontier::for_initial_head(&session.revocations()?)?;
    let consumer = |dir: &std::path::Path| HostAuthorityPublicConsumerV1 {
        local_state_dir: dir.to_owned(),
        owner_id: "root-issuer".into(),
        frontier,
    };
    let lane = path.join("unused-controlled-bootstrap-path");
    let bootstrap = HostAuthorityPublicBootstrapV1 {
        schema_version: 1,
        operation: crate::HOST_AUTHORITY_BOOTSTRAP_V1.into(),
        root: peer_lifetime.clone(),
        consumer: peer_lifetime,
        registered_identity: HostAuthorityRegisteredIdentity {
            agent_id: identity.agent_id.clone(),
            spawn_generation: identity.spawn_generation,
            fleet_root: identity.fleet_root.clone(),
            workspace: identity.workspace.clone(),
            resources: identity.resources.clone(),
        },
        issuer_key: HostAuthorityPublicIssuerKeyV1 {
            key_id: "synthetic-fixture".into(),
            verifying_key: key,
            not_before_authority_epoch: 2,
            not_after_authority_epoch: 2,
        },
        revocations: session.revocations()?,
        writer: HostAuthorityWriterRegistration {
            registered_agent_id: trust.agent_id,
            spawn_generation: trust.spawn_generation,
            owner_epoch: trust.owner_epoch,
            local_lease_id: trust.local_lease_id,
            local_lease_generation: trust.local_lease_generation,
            authority_lease: trust.authority_lease,
        },
        writer_proof: proof,
        checkpoint: head,
        consumers: HostAuthorityPublicConsumersV1 {
            device: consumer(device_dir.path()),
            notes: consumer(notes_dir.path()),
        },
        sockets: HostAuthorityFiveLanePathsV1 {
            observation: lane.clone(),
            issuer: lane.clone(),
            checkpoint: lane.clone(),
            device_frontier: lane.clone(),
            notes_frontier: lane,
        },
    };
    let target = Arc::new(NoEffect(AtomicUsize::new(0)));
    let attachment = crate::attach_root_production_operation_host(
        &mut config,
        AgentdRootProductionInputs {
            session,
            checkpoint,
            device,
            notes,
            grants,
            bootstrap,
        },
        target.clone(),
        None,
        Duration::from_millis(20),
    )
    .await?;
    config
        .production_writer_host()
        .ok_or("original host missing")?
        .writer()
        .verify_current_authority()
        .await?;
    // This is the existing public escape, not a test-only File setter.
    let retained_session = attachment.root_session.clone();
    let clock = retained_session.clock();
    let verifier = retained_session.verifier();
    drop(config);
    drop(attachment);
    let clock_live = clock.now_unix_ms().is_ok();
    let verifier_live = verifier.verify(&authority, &identity.agent_id).is_ok();
    let owner_lock_reacquired = takes_same_lock(&contender)?;
    let load_replacement = || {
        AgentdConfig::load(
            identity.fleet_root.clone(),
            identity.agent_id.clone(),
            identity.spawn_generation,
            identity.home_root.clone(),
            identity.run_root.clone(),
            identity.home_root.clone(),
            identity.workspace.clone(),
        )
    };
    let replacement = load_replacement();
    let replacement_loaded = replacement.is_ok();
    // Recheck WHILE the actual replacement Config still holds its original
    // File, so a stale pre-lock sample cannot masquerade as live coexistence.
    let replacement_clock_live = clock.now_unix_ms().is_ok();
    let replacement_verifier_live = verifier.verify(&authority, &identity.agent_id).is_ok();
    let replacement_lock_held = !takes_same_lock(&contender)?;
    eprintln!(
        "root-session-custody-overlap replacement_loaded={replacement_loaded} replacement_lock_held={replacement_lock_held} replacement_clock_live={replacement_clock_live} replacement_verifier_live={replacement_verifier_live}"
    );
    drop(replacement);
    assert!(replacement_lock_held);
    assert!(replacement_clock_live && replacement_verifier_live);
    assert!(
        clock_live && verifier_live,
        "original active Session is required to establish the overlap"
    );
    drop(retained_session);
    assert!(clock.now_unix_ms().is_err());
    assert!(verifier.verify(&authority, &identity.agent_id).is_err());
    tokio::time::timeout(Duration::from_secs(1), async {
        while !worker.is_finished() {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    tokio::task::spawn_blocking(move || root_peer.join())
        .await?
        .map_err(|_| "Root fixture peer panicked")?;
    // Retained read-only clones are fenced, and cannot prolong File custody
    // after the actual Session/worker has retired. They remain alive here.
    let fenced_clones_lock_reacquired = takes_same_lock(&contender)?;
    assert!(clock.now_unix_ms().is_err());
    assert!(verifier.verify(&authority, &identity.agent_id).is_err());
    let retired_replacement = load_replacement()?;
    assert!(!takes_same_lock(&contender)?);
    drop(retired_replacement);
    eprintln!(
        "root-session-readonly-retirement fenced_clones_retained=true actual_replacement_loaded=true replacement_retired=true"
    );
    drop(clock);
    drop(verifier);
    tokio::task::spawn_blocking(move || checkpoint_worker.join())
        .await?
        .map_err(|_| "checkpoint fixture peer panicked")?
        .map_err(|error| error.to_string())?;
    issuer_peer.set_nonblocking(true)?;
    assert_eq!(issuer_peer.read(&mut [0])?, 0);
    assert_eq!(target.0.load(Ordering::SeqCst), 0);
    let final_lock_reacquired = takes_same_lock(&contender)?;
    assert_eq!(
        (contender.metadata()?.dev(), contender.metadata()?.ino()),
        (before.dev(), before.ino())
    );
    eprintln!(
        "root-session-custody clock_live={clock_live} verifier_live={verifier_live} owner_lock_reacquired={owner_lock_reacquired} replacement_loaded={replacement_loaded} fenced_clones_lock_reacquired={fenced_clones_lock_reacquired} final_lock_reacquired={final_lock_reacquired} dev={} ino={} effects=0",
        before.dev(),
        before.ino()
    );
    assert!(!owner_lock_reacquired);
    assert!(!replacement_loaded);
    assert!(fenced_clones_lock_reacquired);
    assert!(final_lock_reacquired);
    Ok(())
}
