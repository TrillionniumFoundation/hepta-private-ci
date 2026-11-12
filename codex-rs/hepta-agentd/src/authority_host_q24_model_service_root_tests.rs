//! Real Root reservation, custody handoff, live writer CAS and open-only recovery.
//! Scope/material are synthetic control vectors. No Training, Evaluation,
//! Model Proposal, independent consumer or ordinary completion is claimed.

use crate::AgentdRootAuthorityPeer;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityBindIdentity;
use crate::HostAuthorityBootstrap;
use crate::HostAuthorityLearningProfileV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::HostAuthoritySocketPaths;
use crate::HostAuthorityWriterRegistration;
use crate::HostIssuerRecordProfile;
use crate::PreparedHostAuthoritySession;
use crate::learning_iteration_checkpoint::learning_test_support::fixture;
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

const CHILD_TEST: &str = "authority_host_q24_model_service_root_tests::root_q24_model_factory_service_dedicated_uid_child";
const FACTORY_OWNER: &str = "root-q24-model-proposal-factory-v1";
const UPDATE_RULE: &[u8] = b"root-q24-factory-service-cell-update-rule-v2";
const MATERIAL: &[u8] = b"synthetic-registry-control-not-a-model-proposal";

#[test]
#[ignore = "explicit actual Root, two protected bind domains and dedicated UID"]
fn root_q24_factory_registers_transfers_binds_and_recovers_original_custody() -> anyhow::Result<()>
{
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
        .prefix("q24-factory-service-")
        .tempdir_in(parent)?;
    std::fs::set_permissions(protected.path(), std::fs::Permissions::from_mode(0o700))?;
    let (_scope_files, identity, coordinator) = fixture()?;
    let mut request = coordinator.snapshot().request.clone();
    request.envelope.expiry_unix_seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs()
        + 300;
    let coordinator =
        LearningIterationCoordinatorV1::new(request, coordinator.snapshot().owners.clone())?;
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
            signer_id: "root-q24-factory-service-qualification".into(),
            policies: vec![DeploymentGrantPolicy {
                subject_id: identity.agent_id.to_string(),
                destination_id: destination.into(),
                scope_sha256: [2; 32],
                lifetime_ms: 30_000,
            }],
            lease_id: "root-q24-factory-service-qualification".into(),
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
    assert_eq!(profile.frozen_scope(&initial)?, Some(scope));
    let profile_file = protected.path().join("learning-profile.json");
    support::write_json(&profile_file, &profile)?;
    let (offer, receive) = UnixDatagram::pair()?;
    let mut child = support::ChildOwner::spawn(receive, &state)?;
    let child_pin = support::pidfd(child.pid()?)?;
    let credential_deadline = Instant::now() + Duration::from_secs(2);
    while crate::authority_host_runtime::verify_process_credentials(child.pid()?, 60001, 60001)
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
        peer_pid: child.pid()?,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: support::start_ticks(child.pid()?)?,
        registered_identity,
        checkpoint_owner_agent_id: identity.agent_id,
        publisher_epoch: 1,
    };
    let registration_file = protected.path().join("spawn.json");
    support::write_json(&registration_file, &registration)?;

    crate::register_host_learning_checkpoint(
        &config_file,
        &registration_file,
        &profile_file,
        &child_pin,
    )?;
    let witness_parent = PathBuf::from(
        std::env::var_os("HEPTA_Q24_FACTORY_WITNESS_BIND")
            .ok_or_else(|| anyhow::anyhow!("explicit separate protected witness bind required"))?,
    );
    let witness_source = PathBuf::from(
        std::env::var_os("HEPTA_Q24_FACTORY_WITNESS_SOURCE")
            .ok_or_else(|| anyhow::anyhow!("original witness bind source required"))?,
    );
    let witness_metadata = std::fs::metadata(&witness_parent)?;
    let witness_directory = tempfile::Builder::new()
        .prefix("factory-witness-")
        .tempdir_in(&witness_parent)?;
    std::fs::set_permissions(
        witness_directory.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let reservation = crate::HostAuthorityQ24ModelFactoryReservationV1 {
        schema_version: 1,
        witness_bind: HostAuthorityBindIdentity {
            mountpoint: witness_parent,
            source_path: witness_source,
            device: witness_metadata.dev(),
            inode: witness_metadata.ino(),
        },
        witness_directory: witness_directory.path().to_owned(),
        local_policy_digest: Digest32::of_bytes(b"synthetic-precommitted-root-policy").to_string(),
    };
    let reservation_file = protected.path().join("factory-reservation.json");
    support::write_json(&reservation_file, &reservation)?;
    assert!(
        PreparedHostAuthoritySession::open(
            &config_file,
            &registration_file,
            child_pin.try_clone()?
        )?
        .with_registered_learning(&profile_file)?
        .with_registered_q24_model_factory(&reservation_file)
        .is_err()
    );
    assert!(!state.join("q24-model-proposal-factory-v1").exists());
    let factory_profile = crate::register_host_q24_model_factory(
        &config_file,
        &registration_file,
        &profile_file,
        &reservation_file,
        &child_pin,
    )?;
    let registry = state.join("q24-model-proposal-factory-v1");
    let before = support::protected_files(&registry)?;
    assert!(
        crate::register_host_q24_model_factory(
            &config_file,
            &registration_file,
            &profile_file,
            &reservation_file,
            &child_pin
        )
        .is_err()
    );
    assert_eq!(support::protected_files(&registry)?, before);
    let mut prepared = PreparedHostAuthoritySession::open(
        &config_file,
        &registration_file,
        child_pin.try_clone()?,
    )?
    .with_registered_learning(&profile_file)?
    .with_registered_q24_model_factory(&reservation_file)?;
    let model_offer = prepared.take_q24_model_factory_offer()?;
    assert!(prepared.take_q24_model_factory_offer().is_err());
    let root_pin = support::pidfd(std::process::id())?;
    let service_result = prepared.serve_with_ready(|| {
        crate::send_root_q24_model_factory_handoff(
            offer,
            model_offer,
            &root_pin,
            Duration::from_millis(500),
        )
        .map_err(io::Error::other)
    });
    if let Err(error) = service_result {
        let _ = child.release();
        let outcome = child.finish();
        anyhow::bail!("original factory service failed: {error}; dedicated child: {outcome:?}");
    }
    let stored: HostAuthorityFrontierStore<
        crate::authority_host_service::q24_model::FactoryRecord,
    > = HostAuthorityFrontierStore::open(
        RootAuthorityDirectory::open(&registry)?,
        FACTORY_OWNER.into(),
    )?;
    use codex_hepta_contracts::AuthorityFrontierStore;
    let bound = stored.load(FACTORY_OWNER)?;
    assert_eq!(
        bound.profile,
        crate::authority_host_service::q24_model::ReservedFactoryProfile::LegacyV1(factory_profile)
    );
    assert_eq!(
        (bound.epoch, bound.material),
        (2, Some(Digest32::of_bytes(MATERIAL).to_string()))
    );
    drop(stored);
    let bound_files = support::protected_files(&registry)?;
    let witness_path = witness_directory
        .path()
        .join("q24-model-proposal-factory-v1.witness");
    let witness_bytes = std::fs::read(&witness_path)?;
    let mut reopened = PreparedHostAuthoritySession::open(
        &config_file,
        &registration_file,
        child_pin.try_clone()?,
    )?
    .with_registered_learning(&profile_file)?
    .with_registered_q24_model_factory(&reservation_file)?;
    let reopened_offer = reopened.take_q24_model_factory_offer()?;
    assert_eq!(
        reopened_offer.journal.metadata()?.len(),
        0,
        "registry binding is not a Model proposal"
    );
    assert_eq!(support::protected_files(&registry)?, bound_files);
    assert_eq!(std::fs::read(&witness_path)?, witness_bytes);
    drop((reopened_offer, reopened));
    std::fs::remove_file(&witness_path)?;
    assert!(
        PreparedHostAuthoritySession::open(
            &config_file,
            &registration_file,
            child_pin.try_clone()?
        )?
        .with_registered_learning(&profile_file)?
        .with_registered_q24_model_factory(&reservation_file)
        .is_err()
    );
    assert!(
        !witness_path.exists(),
        "missing original witness must never be recreated"
    );
    assert_eq!(support::protected_files(&registry)?, bound_files);
    child.release()?;
    let output = child.finish()?;
    assert!(
        output.contains("ROOT_Q24_FACTORY_SERVICE actual_consumer_uid=60001"),
        "{output}"
    );
    println!("{output}");
    Ok(())
}

#[test]
#[ignore = "only the actual Root parent supplies the dedicated factory child"]
fn root_q24_model_factory_service_dedicated_uid_child() -> anyhow::Result<()> {
    use crate::authority_host_service::q24_model::Command;
    use crate::authority_host_service::q24_model::Q24ModelFactoryBootstrap;
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), 60001, 60001)?;
    let number: i32 = std::env::var("HEPTA_LEARNING_SERVICE_CHILD_FD")?.parse()?;
    let original_root: u32 = std::env::var("HEPTA_LEARNING_SERVICE_ROOT_PID")?.parse()?;
    anyhow::ensure!(number >= 3 && original_root != std::process::id());
    // SAFETY: this dedicated child entry receives only its original inherited socket.
    unsafe { libc::alarm(10) };
    let state = std::env::var_os("HEPTA_LEARNING_SERVICE_STATE")
        .ok_or_else(|| anyhow::anyhow!("original state required"))?;
    assert_eq!(
        std::fs::read_dir(state).unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    // SAFETY: the trusted parent transfers ownership of this inherited descriptor.
    let socket = unsafe { UnixDatagram::from_raw_fd(number) };
    let mut handoff =
        crate::receive_root_q24_model_factory_handoff(socket, Duration::from_secs(5))?;
    assert_eq!(handoff.root_pid, original_root);
    let mut bytes = Vec::new();
    handoff.bootstrap.rewind()?;
    handoff.bootstrap.read_to_end(&mut bytes)?;
    let bundle: Q24ModelFactoryBootstrap = serde_json::from_slice(&bytes)?;
    assert_eq!(
        (
            bundle.root.uid,
            bundle.root.pid,
            bundle.consumer.uid,
            bundle.consumer.pid
        ),
        (0, original_root, 60001, std::process::id())
    );
    bundle
        .profile
        .require_files(&handoff.journal, &handoff.witness)?;
    let peer = AgentdRootAuthorityPeer {
        pid: bundle.root.pid,
        boot_id: bundle.root.boot_id.clone(),
        process_start_ticks: bundle.root.process_start_ticks,
    };
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?
        .block_on(async {
            let transport = crate::root_observation_stream::RootObservationStream::from_stream(
                UnixStream::connect(&bundle.socket_path)?,
                peer,
                handoff.root_pidfd,
                Duration::from_millis(500),
                Duration::from_secs(5),
            )?;
            let initial = exchange(
                &transport,
                &bundle.profile,
                /*request_id*/ 1,
                Command::Observe,
            )
            .await?;
            assert_eq!(
                (
                    initial.lease.epoch,
                    initial.lease.material,
                    initial.newly_bound
                ),
                (1, None, false)
            );
            let initial = exchange(
                &transport,
                &bundle.profile,
                /*request_id*/ 2,
                Command::Observe,
            )
            .await?;
            let bound = exchange(
                &transport,
                &bundle.profile,
                /*request_id*/ 3,
                Command::Bind {
                    expected: initial.lease,
                    material: Digest32::of_bytes(MATERIAL).to_string(),
                },
            )
            .await?;
            assert!(bound.newly_bound);
            let again = exchange(
                &transport,
                &bundle.profile,
                /*request_id*/ 4,
                Command::Bind {
                    expected: bound.lease.clone(),
                    material: Digest32::of_bytes(MATERIAL).to_string(),
                },
            )
            .await?;
            assert_eq!(again.lease, bound.lease);
            assert!(!again.newly_bound, "replayed bind must be recover-only");
            let confirmed = exchange(
                &transport,
                &bundle.profile,
                /*request_id*/ 5,
                Command::Confirm {
                    expected: bound.lease.clone(),
                },
            )
            .await?;
            assert_eq!(confirmed.lease, bound.lease);
            assert_eq!(
                handoff.journal.metadata()?.len(),
                0,
                "no Model owner or Proposal was created"
            );
            Ok::<_, anyhow::Error>(())
        })?;
    let runtime = bundle
        .socket_path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("original socket parent"))?;
    let mut observation = UnixStream::connect(runtime.join("observation.sock"))?;
    let issuer = UnixStream::connect(runtime.join("issuer.sock"))?;
    let checkpoint = UnixStream::connect(runtime.join("checkpoint.sock"))?;
    support::observation(&mut observation)?;
    drop((observation, issuer, checkpoint));
    println!(
        "ROOT_Q24_FACTORY_SERVICE actual_consumer_uid=60001 actual_consumer_pid={} original_root_pid={original_root} registered_writer=true registry_epoch=2 model_owner_created=false ordinary_chain=false",
        std::process::id()
    );
    let mut released = [0];
    std::io::stdin().read_exact(&mut released)?;
    assert_eq!(released, [1]);
    Ok(())
}

async fn exchange(
    transport: &crate::root_observation_stream::RootObservationStream,
    profile: &crate::authority_host_service::q24_model::LiveFactoryProfile,
    request_id: u64,
    command: crate::authority_host_service::q24_model::Command,
) -> anyhow::Result<crate::authority_host_service::q24_model::Reply> {
    use crate::authority_host_service::q24_model::PURPOSE;
    use crate::authority_host_service::q24_model::Request;
    use crate::authority_host_service::q24_model::Response;
    let response: Response = transport
        .read(&Request {
            schema: 1,
            operation: PURPOSE.into(),
            request_id,
            binding: profile.binding().into(),
            command,
        })
        .await?;
    assert_eq!(
        (
            response.schema,
            response.operation.as_str(),
            response.request_id,
            response.binding.as_str()
        ),
        (1, PURPOSE, request_id, profile.binding())
    );
    Ok(response.reply)
}
