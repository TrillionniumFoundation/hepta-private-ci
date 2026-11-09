//! Explicit real-Root scoped V2 registration, retained writer and learning lane.
//! The scope and Experience receipt are synthetic checkpoint data. This does not
//! qualify training, independent evaluation, model publication or product adoption.

use crate::AgentdLearningCheckpointClientV1;
use crate::AgentdRootAuthorityPeer;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityBindIdentity;
use crate::HostAuthorityBootstrap;
use crate::HostAuthorityLearningBootstrapV1;
use crate::HostAuthorityLearningProfileV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::HostAuthoritySocketPaths;
use crate::HostAuthorityWriterRegistration;
use crate::HostIssuerRecordProfile;
use crate::LearningIterationCheckpointOwnerV1;
use crate::LearningIterationCheckpointRecordV1;
use crate::PreparedHostAuthoritySession;
use crate::learning_iteration_checkpoint::learning_test_support::fixture;
use crate::learning_iteration_checkpoint::learning_test_support::record_experience;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

#[path = "authority_host_learning_service_root_support.rs"]
mod support;

const CHILD_TEST: &str = "authority_host_learning_service_root_tests::root_learning_registered_service_dedicated_uid_child";
const STORE_OWNER: &str = "root-learning-checkpoint-v1";
const UPDATE_RULE: &[u8] = b"root-learning-service-cell-update-rule-v2";

#[test]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
fn root_learning_public_registration_serves_retained_writer_and_recovers_history()
-> anyhow::Result<()> {
    // SAFETY: these calls only read the actual process credentials.
    assert_eq!(unsafe { libc::getuid() }, 0);
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = PathBuf::from(
        std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT")
            .ok_or_else(|| anyhow::anyhow!("explicit protected bind parent required"))?,
    );
    let source = PathBuf::from(
        std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE")
            .ok_or_else(|| anyhow::anyhow!("explicit original bind source required"))?,
    );
    let metadata = std::fs::metadata(&parent)?;
    let required_bind = HostAuthorityBindIdentity {
        mountpoint: parent.clone(),
        source_path: source,
        device: metadata.dev(),
        inode: metadata.ino(),
    };
    let protected = tempfile::Builder::new()
        .prefix("learning-service-")
        .tempdir_in(parent)?;
    std::fs::set_permissions(protected.path(), std::fs::Permissions::from_mode(0o700))?;
    let (_scope_files, identity, mut coordinator) = fixture()?;
    let initial = coordinator.snapshot().clone();
    let update_rule = Digest32::of_bytes(UPDATE_RULE);
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        update_rule,
    )?;
    let registered_identity = HostAuthorityRegisteredIdentity {
        agent_id: identity.agent_id.clone(),
        spawn_generation: identity.spawn_generation,
        fleet_root: identity.fleet_root.clone(),
        workspace: identity.workspace.clone(),
        resources: identity.resources.clone(),
    };
    let bootstrap_file = protected.path().join("bootstrap.json");
    let state = protected.path().join("authority");
    let destination = "qualification.learning.no-effect";
    support::write_json(
        &bootstrap_file,
        &HostAuthorityBootstrap {
            schema_version: 1,
            required_bind: required_bind.clone(),
            signer_id: "root-learning-service-qualification".into(),
            policies: vec![DeploymentGrantPolicy {
                subject_id: identity.agent_id.to_string(),
                destination_id: destination.into(),
                scope_sha256: [2; 32],
                lifetime_ms: 30_000,
            }],
            lease_id: "root-learning-service-qualification".into(),
            lease_binding: AuthorityLeaseBinding {
                principal_id: identity.agent_id.to_string(),
                operation_class: "runtime.agentd.production_operation".into(),
                destination_id: destination.into(),
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            lease_lifetime_ms: 60_000,
        },
    )?;
    let initialized = crate::initialize_host_authority(&state, &bootstrap_file)?;
    assert!(!initialized.production_ready);
    let runtime = tempfile::Builder::new().prefix("hlq-").tempdir_in("/run")?;
    let runtime_c = std::ffi::CString::new(runtime.path().as_os_str().as_encoded_bytes())?;
    // SAFETY: the test owns this newly created directory and changes only its group.
    anyhow::ensure!(
        unsafe { libc::chown(runtime_c.as_ptr(), 0, 60001) } == 0,
        "{}",
        io::Error::last_os_error()
    );
    std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o2710))?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis() as u64;
    let config = HostAuthorityServiceConfig {
        schema_version: 1,
        issuer_record_profile: HostIssuerRecordProfile::Standard,
        state_dir: state.clone(),
        required_bind,
        signer_id: initialized.signer_id,
        expected_verifying_key: initialized.verifying_key,
        lease_id: initialized.lease_id,
        lease_revision: initialized.lease_revision,
        writer: Some(HostAuthorityWriterRegistration {
            registered_agent_id: identity.agent_id.clone(),
            spawn_generation: identity.spawn_generation,
            owner_epoch: 1,
            local_lease_id: "learning-original-local-writer".into(),
            local_lease_generation: 1,
            authority_lease: AuthorityLease {
                schema_version: 1,
                lease_id: "learning-original-root-writer".into(),
                revision: 1,
                authority_epoch: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: identity.agent_id.to_string(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: "qualification.learning.no-effect.cognitive-owner".into(),
                    scope_sha256: [6; 32],
                    payload_sha256: [7; 32],
                },
                issued_at_unix_ms: now,
                expires_at_unix_ms: now + 60_000,
            },
        }),
        checkpoint_state_dir: None,
        consumers: None,
        sockets: HostAuthoritySocketPaths {
            observation: runtime.path().join("observation.sock"),
            issuer: runtime.path().join("issuer.sock"),
            checkpoint: runtime.path().join("checkpoint.sock"),
            device_frontier: None,
            notes_frontier: None,
        },
        peer_uid: 60001,
        peer_gid: 60001,
        timeout_ms: 500,
        lifetime_ms: 5_000,
    };
    let config_file = protected.path().join("service.json");
    support::write_json(&config_file, &config)?;
    let writer_proof = crate::register_host_writer_authorization(&config_file)?;
    let proof: Digest32 = writer_proof.sha256()?.as_str().parse()?;
    let profile = HostAuthorityLearningProfileV1::new_scoped_v2(
        &identity,
        *proof.as_array(),
        initial.request.clone(),
        initial.owners.clone(),
        LearningUpdateScopeV2::Cell,
        update_rule,
    )?;
    assert_eq!(profile.frozen_scope(&initial)?, Some(scope.clone()));
    let profile_file = protected.path().join("learning-profile.json");
    support::write_json(&profile_file, &profile)?;
    let (offer, receive) = UnixDatagram::pair()?;
    let mut child = support::ChildOwner::spawn(receive, &state)?;
    let child_pin = support::pidfd(child.pid())?;
    let credential_deadline = Instant::now() + Duration::from_secs(2);
    while crate::authority_host_runtime::verify_process_credentials(child.pid(), 60001, 60001)
        .is_err()
    {
        anyhow::ensure!(
            Instant::now() < credential_deadline,
            "dedicated child credentials deadline"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    let registration = HostAuthorityRegistration {
        schema_version: 1,
        peer_pid: child.pid(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: support::start_ticks(child.pid())?,
        registered_identity,
        checkpoint_owner_agent_id: identity.agent_id,
        publisher_epoch: 1,
    };
    let registration_file = protected.path().join("spawn.json");
    support::write_json(&registration_file, &registration)?;
    // Runtime cannot initialize a missing learning registration.
    assert!(
        PreparedHostAuthoritySession::open(
            &config_file,
            &registration_file,
            child_pin.try_clone()?
        )?
        .with_registered_learning(&profile_file)
        .is_err()
    );
    assert!(!state.join("learning-checkpoint").exists());
    let registered = crate::register_host_learning_checkpoint(
        &config_file,
        &registration_file,
        &profile_file,
        &child_pin,
    )?;
    assert_eq!(
        (
            registered.schema_version,
            registered.initial_head,
            registered.writer_proof_digest,
            registered.frozen_scope_binding,
            registered.production_ready
        ),
        (
            2,
            initial.head_digest.to_string(),
            proof.to_string(),
            Some(scope.binding().to_string()),
            false
        )
    );
    assert!(
        crate::register_host_learning_checkpoint(
            &config_file,
            &registration_file,
            &profile_file,
            &child_pin,
        )
        .is_err()
    );
    let prepared = PreparedHostAuthoritySession::open(
        &config_file,
        &registration_file,
        child_pin.try_clone()?,
    )?
    .with_registered_learning(&profile_file)?;
    let sealed = prepared.seal_learning_bootstrap()?;
    // The prepared service retains its original exclusive Registry owner.
    assert!(
        PreparedHostAuthoritySession::open(
            &config_file,
            &registration_file,
            child_pin.try_clone()?,
        )
        .is_err()
    );
    let root_pin = support::pidfd(std::process::id())?;
    let learning_path = runtime.path().join("learning-checkpoint-v1.sock");
    let paths = [
        &config.sockets.observation,
        &config.sockets.issuer,
        &config.sockets.checkpoint,
        &learning_path,
    ];
    let service_result = prepared.serve_with_ready(|| {
        for path in paths {
            let entry = std::fs::symlink_metadata(path)?;
            if !entry.file_type().is_socket()
                || entry.uid() != 0
                || entry.gid() != 60001
                || entry.mode() & 0o777 != 0o660
            {
                return Err(io::Error::other(
                    "original ready barrier socket custody mismatch",
                ));
            }
        }
        crate::send_root_learning_handoff(offer, &sealed, &root_pin, Duration::from_millis(500))
            .map_err(io::Error::other)
    });
    if let Err(error) = service_result {
        let _ = child.release();
        let outcome = child.finish();
        anyhow::bail!("original Root service failed: {error}; dedicated child: {outcome:?}");
    }
    for path in paths {
        assert!(
            !path.exists(),
            "original session must remove its socket: {path:?}"
        );
    }
    record_experience(&mut coordinator)?;
    let before = support::protected_files(&state.join("learning-checkpoint"))?;
    let store = HostAuthorityFrontierStore::<LearningIterationCheckpointRecordV1>::open(
        RootAuthorityDirectory::open(&state.join("learning-checkpoint"))?,
        STORE_OWNER.into(),
    )?;
    let owner = LearningIterationCheckpointOwnerV1::from_registered_scoped_v2(
        store,
        STORE_OWNER.into(),
        initial.request.clone(),
        initial.owners.clone(),
        scope.clone(),
    )?;
    assert_eq!(owner.frozen_scope_binding(), Some(scope.binding()));
    assert_eq!(
        owner.restore(&initial.request)?,
        Some(coordinator.snapshot().clone())
    );
    drop(owner);
    assert_eq!(
        support::protected_files(&state.join("learning-checkpoint"))?,
        before
    );
    child.release()?;
    let output = child.finish()?;
    assert!(
        output.contains("ROOT_LEARNING_REGISTERED_SERVICE actual_consumer_uid=60001"),
        "{output}"
    );
    println!("{output}");
    Ok(())
}

#[test]
#[ignore = "only the actual Root parent supplies this dedicated-UID child handoff"]
fn root_learning_registered_service_dedicated_uid_child() -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), 60001, 60001)?;
    let number: i32 = std::env::var("HEPTA_LEARNING_SERVICE_CHILD_FD")?.parse()?;
    let original_root: u32 = std::env::var("HEPTA_LEARNING_SERVICE_ROOT_PID")?.parse()?;
    anyhow::ensure!(number >= 3 && original_root != std::process::id());
    // SAFETY: this is the single dedicated child entry, never the parent test process.
    // SIGALRM bounds its total runtime, including a failed parent release, to ten seconds.
    unsafe { libc::alarm(10) };
    let state = std::env::var_os("HEPTA_LEARNING_SERVICE_STATE")
        .ok_or_else(|| anyhow::anyhow!("protected state observation required"))?;
    assert_eq!(
        std::fs::read_dir(state).unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    // SAFETY: trusted exec passes exclusive ownership of this one inherited socket.
    let socket = unsafe { UnixDatagram::from_raw_fd(number) };
    let mut handoff = crate::receive_root_learning_handoff(socket, Duration::from_secs(5))?;
    assert_eq!(handoff.root_pid, original_root);
    for descriptor in [
        handoff.bootstrap.as_raw_fd(),
        handoff.root_pidfd.as_raw_fd(),
    ] {
        // SAFETY: F_GETFD only observes this child's retained received descriptor.
        assert_ne!(
            unsafe { libc::fcntl(descriptor, libc::F_GETFD) } & libc::FD_CLOEXEC,
            0
        );
    }
    let mut bytes = Vec::new();
    handoff.bootstrap.rewind()?;
    handoff.bootstrap.read_to_end(&mut bytes)?;
    let bundle: HostAuthorityLearningBootstrapV1 = serde_json::from_slice(&bytes)?;
    assert_eq!(
        (
            bundle.schema_version,
            bundle.operation.as_str(),
            bundle.root.uid,
            bundle.root.pid,
            bundle.consumer.uid,
            bundle.consumer.pid
        ),
        (
            2,
            crate::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2,
            0,
            original_root,
            60001,
            std::process::id()
        )
    );
    let initial = bundle.decode_initial()?;
    let scope = bundle
        .frozen_scope(&initial)?
        .ok_or_else(|| anyhow::anyhow!("sealed V2 bootstrap must retain its frozen Cell scope"))?;
    assert_eq!(
        scope,
        FrozenLearningScopeV2::freeze(
            &initial.request,
            &initial.owners,
            LearningUpdateScopeV2::Cell,
            Digest32::of_bytes(UPDATE_RULE),
        )?
    );
    let scope_binding = scope.binding();
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
    let peer = AgentdRootAuthorityPeer {
        pid: bundle.root.pid,
        boot_id: bundle.root.boot_id,
        process_start_ticks: bundle.root.process_start_ticks,
    };
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?
        .block_on(async {
            let client = AgentdLearningCheckpointClientV1::from_root_stream_scoped_v2(
                UnixStream::connect(&bundle.socket_path)?,
                peer,
                handoff.root_pidfd,
                initial.clone(),
                Duration::from_millis(500),
                Duration::from_secs(5),
                scope,
            )?;
            assert_eq!(client.frozen_scope_binding(), Some(scope_binding));
            assert_eq!(client.restore(&initial.request).await?, None);
            assert_eq!(
                client.checkpoint(Digest32::ZERO, &initial).await?,
                initial.head_digest
            );
            record_experience(&mut coordinator)?;
            let next = coordinator.snapshot().clone();
            assert_eq!(
                client.checkpoint(initial.head_digest, &next).await?,
                next.head_digest
            );
            assert_eq!(client.restore(&initial.request).await?, Some(next.clone()));
            assert_eq!(
                client.checkpoint(initial.head_digest, &next).await?,
                next.head_digest
            );
            assert_eq!(client.restore(&initial.request).await?, Some(next));
            Ok::<(), anyhow::Error>(())
        })?;
    // The learning worker is independent. Connect all original lanes afterward,
    // then read an actual observation through their unchanged all-lane accept barrier.
    let runtime = bundle
        .socket_path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("socket parent"))?;
    let mut observation = UnixStream::connect(runtime.join("observation.sock"))?;
    let issuer = UnixStream::connect(runtime.join("issuer.sock"))?;
    let checkpoint = UnixStream::connect(runtime.join("checkpoint.sock"))?;
    let observed = support::observation(&mut observation)?;
    assert_eq!(
        (
            observed["registered_agent_id"].as_str(),
            observed["spawn_generation"].as_u64()
        ),
        (
            Some(bundle.registered_identity.agent_id.as_str()),
            Some(bundle.registered_identity.spawn_generation)
        )
    );
    drop((observation, issuer, checkpoint));
    println!(
        "ROOT_LEARNING_REGISTERED_SERVICE actual_consumer_uid=60001 actual_consumer_pid={} original_root_pid={original_root} schema=2 scope=cell frozen_scope_binding={scope_binding} registered_writer=true dedicated_listener=true restored_receipts=1 exact_retry=true",
        std::process::id()
    );
    // Keep the exact captured process alive until the original service has
    // closed every lane and Root has completed its read-only durable recovery.
    let mut released = [0];
    std::io::stdin().read_exact(&mut released)?;
    assert_eq!(released, [1]);
    Ok(())
}
