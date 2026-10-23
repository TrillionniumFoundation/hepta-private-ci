//! Explicit privileged qualification; no production writer or recovery cut.
use super::*;
use crate::AgentdFinalUseIssuerPeer;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::DeploymentGrantPolicy;
use crate::authority_host_config::*;
use crate::authority_host_runtime::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Verifier;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

const CLIENT: &str = "authority_host_service::tests::root::protected_service_client";
fn write_json(path: &Path, value: &impl Serialize) {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .unwrap();
    file.write_all(&serde_json::to_vec(value).unwrap()).unwrap();
    file.sync_all().unwrap();
    std::fs::File::open(path.parent().unwrap())
        .unwrap()
        .sync_all()
        .unwrap();
}
fn body() -> AuthBusObjectiveBody {
    AuthBusObjectiveBody {
        spawn_generation: 1,
        run_id: "root-service-qualification".into(),
        objective_revision: 1,
        source_envelope_json: "{}".into(),
        runtime_body_digest: "11".repeat(32),
        preference_state_digest: "22".repeat(32),
        model_tuple_digest: "33".repeat(32),
        prompt_registry_digest: "44".repeat(32),
        artifact_set_digest: "55".repeat(32),
        authority_epoch: 1,
    }
}
fn binding(subject: &str) -> FinalUseBinding {
    FinalUseBinding {
        subject_id: subject.into(),
        destination_id: "qualification.no-effect".into(),
        scope_sha256: [2; 32],
        request_sha256: [1; 32],
        payload_sha256: [3; 32],
    }
}
fn exchange(
    stream: &mut UnixStream,
    request: &serde_json::Value,
    bound: usize,
) -> serde_json::Value {
    let bytes = serde_json::to_vec(request).unwrap();
    stream
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    stream.write_all(&bytes).unwrap();
    let mut length = [0; 4];
    stream.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=bound).contains(&length));
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}
fn connect(path: &Path) -> UnixStream {
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        match UnixStream::connect(path) {
            Ok(stream) => {
                stream
                    .set_read_timeout(Some(Duration::from_secs(10)))
                    .unwrap();
                stream
                    .set_write_timeout(Some(Duration::from_secs(10)))
                    .unwrap();
                return stream;
            }
            Err(_) => {
                assert!(Instant::now() < deadline, "root service listener deadline");
                std::thread::sleep(Duration::from_millis(5));
            }
        }
    }
}

#[test]
#[ignore = "controlled UID60001 client entry, launched by explicit root qualification"]
fn protected_service_client() {
    // SAFETY: geteuid has no borrowed memory or pointer arguments.
    assert_eq!(unsafe { libc::geteuid() }, 60001);
    let status = std::fs::read_to_string("/proc/self/status").unwrap();
    assert!(status.lines().any(|line| line == "NoNewPrivs:\t1"));
    assert!(status.lines().any(|line| {
        line.strip_prefix("Groups:")
            .is_some_and(|groups| groups.trim().is_empty())
    }));
    let state = std::env::var_os("HEPTA_SERVICE_STATE").unwrap();
    assert_eq!(
        std::fs::read_dir(state).unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    if std::env::var_os("HEPTA_SERVICE_START_STDIN").is_some() {
        let mut start = [0];
        std::io::stdin().read_exact(&mut start).unwrap();
        assert_eq!(start, [1]);
    }
    let runtime = std::path::PathBuf::from(std::env::var_os("HEPTA_SERVICE_RUNTIME").unwrap());
    let mut observe = connect(&runtime.join("observation.sock"));
    let issuer = connect(&runtime.join("issuer.sock"));
    let mut checkpoint = connect(&runtime.join("checkpoint.sock"));
    if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_FEED").is_some() {
        std::thread::sleep(Duration::from_secs(3));
        let request = serde_json::to_vec(
            &serde_json::json!({"schema_version":1,"operation":"runtime.authority.observation.v1"}),
        )
        .unwrap();
        observe
            .write_all(&(request.len() as u32).to_be_bytes())
            .unwrap();
        observe.write_all(&request).unwrap();
        let mut first = [0];
        assert_eq!(
            observe.read(&mut first).unwrap(),
            0,
            "expired lease must not emit a feed prefix"
        );
        let registered: HostAuthorityRegisteredIdentity =
            serde_json::from_str(&std::env::var("HEPTA_SERVICE_IDENTITY").unwrap()).unwrap();
        let provider = AgentdUnixFinalUseGrantProvider::from_stream(
            issuer,
            AgentdFinalUseIssuerPeer {
                uid: 0,
                pid: std::env::var("HEPTA_SERVICE_PID").unwrap().parse().unwrap(),
            },
            Duration::from_secs(10),
        )
        .unwrap();
        assert!(matches!(
            provider.request_grant(&binding(registered.agent_id.as_str())),
            Err(crate::AgentdFinalUseIssuerError::Denied)
        ));
        return;
    }
    let before = Instant::now();
    let observation = exchange(
        &mut observe,
        &serde_json::json!({"schema_version":1,"operation":"runtime.authority.observation.v1"}),
        16 * 1024,
    );
    assert!(
        before.elapsed() <= Duration::from_millis(500),
        "feed freshness from before read"
    );
    assert_eq!(observation["authority_epoch"], 1);
    assert_eq!(observation["spawn_generation"], 1);
    assert!(
        observation["observed_unix_ms"].as_u64().unwrap()
            <= observation["clock"]["ceiling_unix_ms"].as_u64().unwrap()
    );
    let registered: HostAuthorityRegisteredIdentity =
        serde_json::from_str(&std::env::var("HEPTA_SERVICE_IDENTITY").unwrap()).unwrap();
    let public: [u8; 32] =
        serde_json::from_str(&std::env::var("HEPTA_SERVICE_PUBLIC_KEY").unwrap()).unwrap();
    let key = ed25519_dalek::VerifyingKey::from_bytes(&public).unwrap();
    let mut unregistered_objective = issuer.try_clone().unwrap();
    let provider = AgentdUnixFinalUseGrantProvider::from_stream(
        issuer,
        AgentdFinalUseIssuerPeer {
            uid: 0,
            pid: std::env::var("HEPTA_SERVICE_PID").unwrap().parse().unwrap(),
        },
        Duration::from_secs(10),
    )
    .unwrap();
    let binding = binding(registered.agent_id.as_str());
    assert!(matches!(
        provider.request_grant(&FinalUseBinding {
            scope_sha256: [9; 32],
            ..binding.clone()
        }),
        Err(crate::AgentdFinalUseIssuerError::Denied)
    ));
    let grant = provider.request_grant(&binding).unwrap();
    assert!(grant.grant.grant_id.ends_with(":1"));
    key.verify(
        &grant.grant.signing_bytes().unwrap(),
        &ed25519_dalek::Signature::from_slice(&grant.signature).unwrap(),
    )
    .unwrap();
    let request = serde_json::to_vec(&serde_json::json!({"schema_version":1,"operation":"runtime.authbus.objective.sign.v1","body":body()})).unwrap();
    unregistered_objective
        .write_all(&(request.len() as u32).to_be_bytes())
        .unwrap();
    unregistered_objective.write_all(&request).unwrap();
    let mut first = [0];
    assert_eq!(
        unregistered_objective.read(&mut first).unwrap(),
        0,
        "unregistered writer must not sign an Objective"
    );
    // An absent independently registered head must never return a cut/ACK.
    let bytes=serde_json::to_vec(&serde_json::json!({"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1","request_id":"00000000000000010000000000000001","command":"read_head","expected":null,"proposal":null})).unwrap();
    checkpoint
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    checkpoint.write_all(&bytes).unwrap();
    let mut bytes = Vec::new();
    checkpoint.read_to_end(&mut bytes).unwrap();
    assert!(bytes.is_empty());
}

#[test]
#[ignore = "explicit root/data-bind canonical three-lane service qualification"]
fn root_data_service_three_lanes_use_original_wire_key_and_dedicated_peer() {
    // SAFETY: geteuid has no borrowed memory or pointer arguments.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::path::PathBuf::from(
        std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT").unwrap(),
    );
    let source = std::path::PathBuf::from(
        std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE").unwrap(),
    );
    let fixture = tempfile::Builder::new()
        .prefix("root-service-qualification-")
        .tempdir_in(&parent)
        .unwrap();
    std::fs::set_permissions(fixture.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = fixture.path();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).unwrap();
    let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    registry
        .register(
            AgentManifest::new(
                owner.clone(),
                WorkspaceBinding::new(workspace.clone(), &fleet).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    registry
        .compare_and_transition(&owner, 0, AgentLifecycle::Starting)
        .unwrap();
    let identity = HostAuthorityRegisteredIdentity {
        agent_id: owner.clone(),
        spawn_generation: 1,
        fleet_root: root.join("fleet"),
        workspace,
        resources: ResourceBudget::local_default(),
    };
    // The original owner creates and coherently captures a genuinely fresh
    // store before any protected clock/lease starts. No suspect DB is imported.
    let checkpoint_cut = std::env::var_os("HEPTA_SERVICE_CHECKPOINT").map(|_| {
        assert!(std::env::var_os("HEPTA_SERVICE_WRITER_PROOF").is_some());
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(async {
                let store =
                    codex_hepta_memory::CognitiveStore::open(&identity.identity().unwrap().layout)
                        .await
                        .unwrap();
                let cut = store.recovery_anchor().await.unwrap();
                store.close().await;
                cut
            })
    });
    let metadata = std::fs::metadata(&parent).unwrap();
    let required_bind = HostAuthorityBindIdentity {
        mountpoint: parent,
        source_path: source,
        device: metadata.dev(),
        inode: metadata.ino(),
    };
    let b = binding(owner.as_str());
    let bootstrap = root.join("bootstrap.json");
    write_json(
        &bootstrap,
        &serde_json::json!({"schema_version":1,"required_bind":required_bind,"signer_id":"root-service-qualification","policies":[DeploymentGrantPolicy {subject_id:owner.to_string(),destination_id:b.destination_id.clone(),scope_sha256:b.scope_sha256,lifetime_ms:30000},DeploymentGrantPolicy {subject_id:owner.to_string(),destination_id:DeploymentFinalUseIssuer::OBJECTIVE_DESTINATION.into(),scope_sha256:*crate::objective_runtime::objective_scope(&identity.identity().unwrap()).as_array(),lifetime_ms:300000}],"lease_id":"root-service-qualification","lease_binding":AuthorityLeaseBinding {principal_id:b.subject_id,operation_class:"runtime.agentd.production_operation".into(),destination_id:b.destination_id,scope_sha256:b.scope_sha256,payload_sha256:b.payload_sha256},"lease_lifetime_ms":if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_FEED").is_some() || std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_OBJECTIVE").is_some() || std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_CHECKPOINT").is_some() {2000} else {60000}}),
    );
    let state = root.join("authority");
    let initialized = initialize_host_authority(&state, &bootstrap).unwrap();
    assert!(!initialized.production_ready);
    assert!(initialize_host_authority(&state, &bootstrap).is_err());
    let runtime = tempfile::Builder::new()
        .prefix("hepta-root-service-qualification-")
        .tempdir_in("/run")
        .unwrap();
    // SAFETY: a NUL-free fixture path is passed to chown; it is root-created.
    let runtime_c = std::ffi::CString::new(runtime.path().as_os_str().as_encoded_bytes()).unwrap();
    assert_eq!(unsafe { libc::chown(runtime_c.as_ptr(), 0, 60001) }, 0);
    std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o2710)).unwrap();
    let mut child = Command::new("/usr/bin/setpriv")
        .args([
            "--reuid=60001",
            "--regid=60001",
            "--clear-groups",
            "--no-new-privs",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--bounding-set=-all",
        ])
        .arg(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_CLIENT_BIN")
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|| std::env::current_exe().unwrap()),
        )
        .args(
            if std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_CLIENT_BIN").is_some() {
                Vec::new()
            } else {
                vec!["--exact", CLIENT, "--ignored", "--nocapture"]
            },
        )
        .stdin(std::process::Stdio::piped())
        .env("HEPTA_SERVICE_START_STDIN", "1")
        .env("HEPTA_SERVICE_STATE", &state)
        .env("HEPTA_SERVICE_RUNTIME", runtime.path())
        .env(
            "HEPTA_SERVICE_IDENTITY",
            serde_json::to_string(&identity).unwrap(),
        )
        .env(
            "HEPTA_SERVICE_PUBLIC_KEY",
            serde_json::to_string(&initialized.verifying_key).unwrap(),
        )
        .env("HEPTA_SERVICE_PID", std::process::id().to_string())
        .spawn()
        .unwrap();
    // Retain the child and pin its real instance before any connection exists.
    // SAFETY: pidfd_open takes a live retained Child PID and no memory pointers.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, child.id(), 0) };
    assert!(raw >= 0);
    // SAFETY: successful pidfd_open returns one fresh owned descriptor.
    let pidfd = unsafe { std::os::fd::OwnedFd::from_raw_fd(raw as i32) };
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let status = std::fs::read_to_string(format!("/proc/{}/status", child.id())).unwrap();
        if status.contains("Uid:\t60001\t60001\t60001\t60001") && status.contains("NoNewPrivs:\t1")
        {
            break;
        }
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(5));
    }
    let stat = std::fs::read_to_string(format!("/proc/{}/stat", child.id())).unwrap();
    let ticks = stat
        .rsplit_once(") ")
        .unwrap()
        .1
        .split_whitespace()
        .nth(19)
        .unwrap()
        .parse()
        .unwrap();
    let registration = HostAuthorityRegistration {
        schema_version: 1,
        peer_pid: child.id(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
            .unwrap()
            .trim()
            .into(),
        process_start_ticks: ticks,
        registered_identity: identity,
        checkpoint_owner_agent_id: owner,
        publisher_epoch: 1,
    };
    let mut config = HostAuthorityServiceConfig {
        schema_version: 1,
        checkpoint_state_dir: None,
        state_dir: state,
        required_bind,
        signer_id: initialized.signer_id,
        expected_verifying_key: initialized.verifying_key,
        lease_id: initialized.lease_id,
        lease_revision: 1,
        writer: if std::env::var_os("HEPTA_SERVICE_WRITER_PROOF").is_some() {
            assert!(std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_CLIENT_BIN").is_some());
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_millis() as u64;
            Some(crate::HostAuthorityWriterRegistration {
                registered_agent_id: registration.registered_identity.agent_id.clone(),
                spawn_generation: registration.registered_identity.spawn_generation,
                owner_epoch: 1,
                local_lease_id: "original-local-writer-qualification".into(),
                local_lease_generation: 1,
                authority_lease: codex_hepta_contracts::authority_lease::AuthorityLease {
                    schema_version: 1,
                    lease_id: "root-writer-qualification".into(),
                    revision: 1,
                    authority_epoch: 1,
                    binding: AuthorityLeaseBinding {
                        principal_id: registration.registered_identity.agent_id.to_string(),
                        operation_class: "runtime.agentd.production_writer".into(),
                        destination_id: "qualification.no-effect.cognitive-owner".into(),
                        scope_sha256: [6; 32],
                        payload_sha256: [7; 32],
                    },
                    issued_at_unix_ms: now,
                    expires_at_unix_ms: now
                        + if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_FEED").is_some()
                            || std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_OBJECTIVE").is_some()
                            || std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_CHECKPOINT").is_some()
                        {
                            2000
                        } else {
                            60000
                        },
                },
            })
        } else {
            None
        },
        sockets: HostAuthoritySocketPaths {
            observation: runtime.path().join("observation.sock"),
            issuer: runtime.path().join("issuer.sock"),
            checkpoint: runtime.path().join("checkpoint.sock"),
        },
        peer_uid: 60001,
        peer_gid: 60001,
        timeout_ms: 10000,
        lifetime_ms: 20000,
    };
    let config_path = root.join("service.json");
    let registration_path = root.join("registered-spawn.json");
    write_json(&config_path, &config);
    write_json(&registration_path, &registration);
    if config.writer.is_some() {
        // Open-only runtime must reject before the explicit Root registration.
        assert!(
            serve_host_authority_session(
                &config_path,
                &registration_path,
                pidfd.try_clone().unwrap()
            )
            .is_err()
        );
    }
    let mut wrong_key = config.clone();
    wrong_key.expected_verifying_key[0] ^= 1;
    let wrong_key_path = root.join("wrong-key.json");
    write_json(&wrong_key_path, &wrong_key);
    assert!(
        serve_host_authority_session(
            &wrong_key_path,
            &registration_path,
            pidfd.try_clone().unwrap()
        )
        .unwrap_err()
        .to_string()
        .contains("public key pin")
    );
    let mut missing_state = config.clone();
    missing_state.state_dir = root.join("absent-state");
    let missing_state_path = root.join("missing-state.json");
    write_json(&missing_state_path, &missing_state);
    assert!(
        serve_host_authority_session(
            &missing_state_path,
            &registration_path,
            pidfd.try_clone().unwrap()
        )
        .is_err()
    );
    assert!(!missing_state.state_dir.exists());
    let mut unmounted = config.clone();
    let metadata = std::fs::metadata(root).unwrap();
    unmounted.required_bind = HostAuthorityBindIdentity {
        mountpoint: root.to_path_buf(),
        source_path: root.to_path_buf(),
        device: metadata.dev(),
        inode: metadata.ino(),
    };
    let unmounted_path = root.join("unmounted.json");
    write_json(&unmounted_path, &unmounted);
    assert!(
        serve_host_authority_session(
            &unmounted_path,
            &registration_path,
            pidfd.try_clone().unwrap()
        )
        .unwrap_err()
        .to_string()
        .contains("not mounted")
    );
    // Form the actual fresh no-effect writer authorization after setup-only
    // negative checks. Its lifetime is not spent constructing the fixture.
    let config_path = if let Some(writer) = &mut config.writer {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        writer.authority_lease.issued_at_unix_ms = now;
        writer.authority_lease.expires_at_unix_ms = now
            + if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_FEED").is_some()
                || std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_OBJECTIVE").is_some()
                || std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_CHECKPOINT").is_some()
            {
                2000
            } else {
                60000
            };
        let active = root.join("service-active.json");
        write_json(&active, &config);
        active
    } else {
        config_path
    };
    if config.writer.is_some() {
        let first = register_host_writer_authorization(&config_path).unwrap();
        assert_eq!(first.claims.sequence, 1);
        if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_FEED").is_none()
            && std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_OBJECTIVE").is_none()
            && std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_CHECKPOINT").is_none()
        {
            assert_eq!(
                register_host_writer_authorization(&config_path).unwrap(),
                first
            );
        }
    }
    let config_path = if let Some(cut) = checkpoint_cut {
        let (clock, leases, issuer) = open_registered_issuer(&config).unwrap();
        let service = HostAuthorityService::from_registered_owner(
            issuer.clone(),
            clock.clone(),
            registration.registered_identity.identity().unwrap(),
        )
        .unwrap()
        .with_registered_writer(config.writer.clone().unwrap(), leases.verifier())
        .unwrap();
        let peer = codex_hepta_memory::CognitiveCheckpointPeerLifetime {
            uid: 60001,
            pid: registration.peer_pid,
            boot_id: registration.boot_id.clone(),
            process_start_ticks: registration.process_start_ticks,
        };
        let registered = service
            .writer
            .as_ref()
            .unwrap()
            .checkpoint_registration(&issuer, registration.publisher_epoch, peer)
            .unwrap();
        let directory = config.state_dir.join("checkpoint");
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&directory)
            .unwrap();
        let backend = crate::HostCognitiveCheckpoint::initialize_fresh(
            RootAuthorityDirectory::open(&directory).unwrap(),
            registered.clone(),
            cut,
            clock,
        )
        .unwrap();
        drop(backend);
        config.checkpoint_state_dir = Some(directory);
        let path = root.join("service-checkpoint.json");
        write_json(&path, &config);
        // A whole-writer binding from a different original authority/token
        // cannot open this protected head, even for the same publisher/peer.
        let mut wrong = registered;
        wrong.writer_binding.fencing_token_digest =
            codex_hepta_contracts::Sha256Digest::for_bytes(b"wrong-token");
        assert!(
            crate::HostCognitiveCheckpoint::open(
                RootAuthorityDirectory::open(config.checkpoint_state_dir.as_ref().unwrap())
                    .unwrap(),
                wrong,
                service.clock,
            )
            .is_err()
        );
        path
    } else {
        config_path
    };
    child.stdin.take().unwrap().write_all(&[1]).unwrap();
    let result = serve_host_authority_session(&config_path, &registration_path, pidfd);
    let status = child.wait().unwrap();
    assert!(
        status.success(),
        "dedicated original-wire client failed: {status}; service={result:?}"
    );
    // An absent head or the final closed-DTO negative closes its lane without ACK.
    assert!(result.is_err());
    if let Some(directory) = &config.checkpoint_state_dir {
        let head = codex_hepta_contracts::HostAuthorityFrontierStore::<
            codex_hepta_memory::CognitiveCheckpointHead,
        >::open(
            RootAuthorityDirectory::open(directory).unwrap(),
            "root-cognitive-checkpoint-v1".into(),
        )
        .unwrap()
        .load("root-cognitive-checkpoint-v1")
        .unwrap();
        let expected = if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_CHECKPOINT").is_some() {
            (codex_hepta_memory::CognitiveCheckpointPhase::Current, 0)
        } else {
            (codex_hepta_memory::CognitiveCheckpointPhase::Fenced, 2)
        };
        assert_eq!((head.phase, head.counter), expected);
    }
    let retained = crate::DeploymentFrontierStore::<serde_json::Value>::open_protected(
        &config.state_dir.join("issuer"),
    )
    .unwrap();
    let mut sequence = if config.writer.is_some() { 1 } else { 0 };
    if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_FEED").is_none()
        && std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_OBJECTIVE").is_none()
        && std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_CHECKPOINT").is_none()
    {
        sequence += if config.writer.is_some() { 2 } else { 1 };
    }
    assert_eq!(
        retained.load("local-final-use-issuer").unwrap()["sequence"],
        sequence
    );
}
