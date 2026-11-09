//! Explicit Root storage and descriptor qualification with synthetic scope
//! metadata. These tests do not supply a deployed writer, independent stage
//! owners, training results or an end-to-end production daemon acceptance.

use super::*;
use crate::AgentdLearningCheckpointClientV1;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationCheckpointErrorV1;
use crate::learning_iteration_checkpoint::learning_test_support::fixture;
use crate::learning_iteration_checkpoint::learning_test_support::record_experience;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::io::Read;
use std::io::Seek;
use std::os::fd::FromRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixDatagram;
use std::thread::JoinHandle;

fn root_state() -> anyhow::Result<tempfile::TempDir> {
    // SAFETY: geteuid only reads the actual test process's credential.
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "explicit actual Root test required"
    );
    let parent = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
        .ok_or_else(|| anyhow::anyhow!("explicit Root-owned qualification parent required"))?;
    let directory = tempfile::Builder::new()
        .prefix("learning-registration-")
        .tempdir_in(parent)?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    RootAuthorityDirectory::open(directory.path())?;
    Ok(directory)
}

#[derive(Debug, Eq, PartialEq)]
struct RetainedFile {
    device: u64,
    inode: u64,
    owner: u32,
    mode: u32,
    bytes: Vec<u8>,
}

fn retained_files(path: &Path) -> anyhow::Result<BTreeMap<PathBuf, RetainedFile>> {
    std::fs::read_dir(path)?
        .map(|entry| {
            let entry = entry?;
            let mut file = File::open(entry.path())?;
            let metadata = file.metadata()?;
            let mut bytes = Vec::new();
            file.read_to_end(&mut bytes)?;
            Ok((
                entry.path(),
                RetainedFile {
                    device: metadata.dev(),
                    inode: metadata.ino(),
                    owner: metadata.uid(),
                    mode: metadata.mode(),
                    bytes,
                },
            ))
        })
        .collect()
}

fn pidfd() -> anyhow::Result<OwnedFd> {
    // SAFETY: pidfd_open returns one new descriptor for this retained process.
    let number = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(number >= 0, "{}", io::Error::last_os_error());
    // SAFETY: the successful syscall transfers ownership of this one new FD.
    Ok(unsafe { OwnedFd::from_raw_fd(number as i32) })
}

fn root_peer() -> anyhow::Result<AgentdRootAuthorityPeer> {
    let stat = std::fs::read_to_string("/proc/self/stat")?;
    let ticks = stat
        .rsplit_once(") ")
        .and_then(|(_, rest)| rest.split_whitespace().nth(19))
        .ok_or_else(|| anyhow::anyhow!("actual Root process identity required"))?
        .parse()?;
    Ok(AgentdRootAuthorityPeer {
        pid: std::process::id(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .to_owned(),
        process_start_ticks: ticks,
    })
}

fn serve_registered_store(
    server: UnixStream,
    backend: LearningIterationCheckpointOwnerV1,
) -> anyhow::Result<JoinHandle<Result<(), HostIssuerTransportError>>> {
    let owner = pidfd()?;
    Ok(std::thread::spawn(move || {
        let mut channel = HostAuthorityPeerChannel::from_stream(
            server,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: 0,
                    pid: std::process::id(),
                },
                timeout: Duration::from_millis(500),
                lifetime: Duration::from_secs(10),
                request_bound: 16 * 1024,
                response_bound: 16 * 1024,
            },
            owner,
        )?;
        let mut next_request = 1;
        while channel
            .exchange(|bytes| backend.exchange_learning_checkpoint(bytes, &mut next_request))?
        {
        }
        Ok(())
    }))
}

#[test]
#[ignore = "explicit actual Root registered learning CAS qualification"]
fn root_learning_registration_reopens_without_replacing_original_history() -> anyhow::Result<()> {
    let root = root_state()?;
    let (_fixture, _identity, mut coordinator) = fixture()?;
    let initial = coordinator.snapshot().clone();
    let path = root.path().join("learning-checkpoint");
    assert!(
        learning_store(
            root.path(),
            &initial,
            StoreMode::Reopen,
            /*scope*/ None
        )
        .is_err()
    );
    assert!(
        !path.exists(),
        "open-only recovery must not register a missing owner"
    );
    let owner = learning_store(
        root.path(),
        &initial,
        StoreMode::Register,
        /*scope*/ None,
    )?;
    assert_eq!(owner.restore(&initial.request)?, None);
    assert_eq!(
        owner.checkpoint(Digest32::ZERO, &initial)?,
        initial.head_digest
    );
    record_experience(&mut coordinator)?;
    let progress = coordinator.snapshot().clone();
    assert_eq!(
        owner.checkpoint(initial.head_digest, &progress)?,
        progress.head_digest
    );
    drop(owner);

    let before = retained_files(&path)?;
    assert!(
        learning_store(
            root.path(),
            &initial,
            StoreMode::Register,
            /*scope*/ None
        )
        .is_err()
    );
    let mut changed = initial.request.clone();
    changed.operation_id = StableId::new("different-unregistered-learning-operation")?;
    let changed = LearningIterationCoordinatorV1::new(changed, initial.owners.clone())?;
    assert!(
        learning_store(
            root.path(),
            changed.snapshot(),
            StoreMode::Reopen,
            /*scope*/ None
        )
        .is_err()
    );
    assert_eq!(retained_files(&path)?, before);

    let reopened = learning_store(
        root.path(),
        &initial,
        StoreMode::Reopen,
        /*scope*/ None,
    )?;
    assert_eq!(reopened.restore(&initial.request)?, Some(progress.clone()));
    assert_eq!(
        reopened.checkpoint(initial.head_digest, &progress)?,
        progress.head_digest
    );
    assert_eq!(
        retained_files(&path)?,
        before,
        "exact reconciliation must not replace storage"
    );
    Ok(())
}

#[tokio::test]
#[ignore = "explicit actual Root sealed learning handoff and registered CAS qualification"]
async fn root_learning_sealed_pin_and_dedicated_uds_recover_original_checkpoint()
-> anyhow::Result<()> {
    let root = root_state()?;
    let (_fixture, identity, mut coordinator) = fixture()?;
    let initial = coordinator.snapshot().clone();
    let owner = learning_store(
        root.path(),
        &initial,
        StoreMode::Register,
        /*scope*/ None,
    )?;
    let profile = HostAuthorityLearningProfileV1::new(
        &identity,
        [7; 32],
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let actual = root_peer()?;
    let lifetime = CognitiveCheckpointPeerLifetime {
        uid: 0,
        pid: actual.pid,
        boot_id: actual.boot_id.clone(),
        process_start_ticks: actual.process_start_ticks,
    };
    // Same-Root-process storage/transport scope; no claim of a deployed
    // non-Root consumer or original five-lane service registration is made.
    let bundle = HostAuthorityLearningBootstrapV1 {
        schema_version: 1,
        operation: crate::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1.into(),
        root: lifetime.clone(),
        consumer: lifetime,
        registered_identity: crate::HostAuthorityRegisteredIdentity {
            agent_id: identity.agent_id.clone(),
            spawn_generation: identity.spawn_generation,
            fleet_root: identity.fleet_root.clone(),
            workspace: identity.workspace.clone(),
            resources: identity.resources.clone(),
        },
        writer_proof_digest: Digest32::from_array([7; 32]).to_string(),
        initial_snapshot: profile.encoded_initial().to_owned(),
        update_scope: None,
        socket_path: root.path().join("learning-checkpoint-v1.sock"),
    };
    let encoded = serde_json::to_vec(&bundle)?;
    let sealed = crate::authority_host_bootstrap_seal::seal_bytes(&encoded)?;
    let (offer, receive) = UnixDatagram::pair()?;
    crate::send_root_learning_handoff(offer, &sealed, &pidfd()?, Duration::from_secs(1))?;
    let mut delivered = crate::receive_root_learning_handoff(receive, Duration::from_secs(1))?;
    assert_eq!(delivered.root_pid, actual.pid);
    delivered.bootstrap.rewind()?;
    let mut observed = Vec::new();
    delivered.bootstrap.read_to_end(&mut observed)?;
    assert_eq!(observed, encoded);
    let restored: HostAuthorityLearningBootstrapV1 = serde_json::from_slice(&observed)?;
    assert_eq!(restored.decode_initial()?, initial);

    let (stream, server) = UnixStream::pair()?;
    let worker = serve_registered_store(server, owner)?;
    let client = AgentdLearningCheckpointClientV1::from_root_stream(
        stream,
        actual,
        delivered.root_pidfd,
        initial.clone(),
        Duration::from_millis(500),
        Duration::from_secs(10),
    )?;
    assert_eq!(client.restore(&initial.request).await?, None);
    let mut foreign = initial.request.clone();
    foreign.source_run_id = StableId::new("another-source-run")?;
    assert_eq!(
        client.restore(&foreign).await,
        Err(LearningIterationCheckpointErrorV1::WrongScope)
    );
    assert_eq!(
        client.checkpoint(Digest32::ZERO, &initial).await?,
        initial.head_digest
    );
    record_experience(&mut coordinator)?;
    let progress = coordinator.snapshot().clone();
    assert_eq!(
        client.checkpoint(initial.head_digest, &progress).await?,
        progress.head_digest
    );
    assert_eq!(
        client.restore(&initial.request).await?,
        Some(progress.clone())
    );
    drop(client);
    worker
        .join()
        .map_err(|_| anyhow::anyhow!("Root checkpoint worker failed"))??;
    let reopened = learning_store(
        root.path(),
        &initial,
        StoreMode::Reopen,
        /*scope*/ None,
    )?;
    assert_eq!(reopened.restore(&initial.request)?, Some(progress));
    Ok(())
}

#[tokio::test]
#[ignore = "explicit actual Root scoped learning CAS and UDS qualification"]
async fn root_scoped_learning_reopens_exact_scope_and_refuses_legacy_client() -> anyhow::Result<()>
{
    let root = root_state()?;
    let (_fixture, _identity, mut coordinator) = fixture()?;
    let initial = coordinator.snapshot().clone();
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        codex_hepta_learning_artifacts::LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"frozen-rule"),
    )?;
    let owner = learning_store(
        root.path(),
        &initial,
        StoreMode::Register,
        Some(scope.clone()),
    )?;
    assert_eq!(owner.frozen_scope_binding(), Some(scope.binding()));
    let path = root.path().join("learning-checkpoint");
    let before = retained_files(&path)?;
    let (stream, server) = UnixStream::pair()?;
    let worker = serve_registered_store(server, owner)?;
    let legacy = AgentdLearningCheckpointClientV1::from_root_stream(
        stream,
        root_peer()?,
        pidfd()?,
        initial.clone(),
        Duration::from_millis(500),
        Duration::from_secs(10),
    )?;
    assert!(legacy.restore(&initial.request).await.is_err());
    drop(legacy);
    assert!(
        worker
            .join()
            .map_err(|_| anyhow::anyhow!("Root checkpoint worker failed"))?
            .is_err()
    );
    assert_eq!(retained_files(&path)?, before);
    assert!(
        learning_store(
            root.path(),
            &initial,
            StoreMode::Reopen,
            /*scope*/ None
        )
        .is_err()
    );
    let organ = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        codex_hepta_learning_artifacts::LearningUpdateScopeV2::Organ,
        Digest32::of_bytes(b"frozen-rule"),
    )?;
    assert!(learning_store(root.path(), &initial, StoreMode::Reopen, Some(organ)).is_err());
    assert_eq!(retained_files(&path)?, before);

    let owner = learning_store(
        root.path(),
        &initial,
        StoreMode::Reopen,
        Some(scope.clone()),
    )?;
    let (stream, server) = UnixStream::pair()?;
    let worker = serve_registered_store(server, owner)?;
    let client = AgentdLearningCheckpointClientV1::from_root_stream_scoped_v2(
        stream,
        root_peer()?,
        pidfd()?,
        initial.clone(),
        Duration::from_millis(500),
        Duration::from_secs(10),
        scope.clone(),
    )?;
    assert_eq!(client.frozen_scope_binding(), Some(scope.binding()));
    assert_eq!(client.restore(&initial.request).await?, None);
    assert_eq!(
        client.checkpoint(Digest32::ZERO, &initial).await?,
        initial.head_digest
    );
    record_experience(&mut coordinator)?;
    let progress = coordinator.snapshot().clone();
    assert_eq!(
        client.checkpoint(initial.head_digest, &progress).await?,
        progress.head_digest
    );
    assert_eq!(
        client.restore(&initial.request).await?,
        Some(progress.clone())
    );
    drop(client);
    worker
        .join()
        .map_err(|_| anyhow::anyhow!("Root checkpoint worker failed"))??;
    let reopened = learning_store(root.path(), &initial, StoreMode::Reopen, Some(scope))?;
    assert_eq!(reopened.restore(&initial.request)?, Some(progress));
    Ok(())
}
