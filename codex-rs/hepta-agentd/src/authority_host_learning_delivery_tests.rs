//! Actual product main, five original lanes and explicit unconfigured refusal.
//! The fresh registration is test-only, never a production provisioning path.
use super::*;
use crate::authority_host_config::HostAuthorityConsumerConfig;
use crate::authority_host_config::HostAuthorityConsumersConfig;
use crate::authority_host_config::HostAuthorityServiceConfig;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use sha2::Digest;
use std::io::Read;

#[test]
#[ignore = "requires test-only bind, actual Root and same-source codex-hepta-agentd binary"]
fn original_product_startup_delivers_checkpoint_then_refuses_incomplete_profile()
-> anyhow::Result<()> {
    let fixture = fixture::Fixture::create()?;
    // The real product main performs its credential transition before Tokio.
    // A libtest child cannot substitute for that single-thread preflight.
    let original = codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?;
    let binary = fixture.binary.with_file_name("codex-hepta-agentd");
    let original_sha256 = binary_sha256(&original)?;
    let original_bytes = std::fs::metadata(&original)?.len();
    let copied = std::fs::copy(&original, &binary)?;
    assert_eq!(copied, original_bytes);
    let original_after_sha256 = binary_sha256(&original)?;
    let copied_sha256 = binary_sha256(&binary)?;
    assert_eq!(original_after_sha256, original_sha256);
    assert_eq!(copied_sha256, original_sha256);
    assert_eq!(std::fs::metadata(&original)?.len(), original_bytes);
    std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o555))?;
    eprintln!(
        "LCP_PRODUCT_BINARY_PROVENANCE {}",
        serde_json::json!({
            "original_path": original,
            "copied_path": binary,
            "bytes": copied,
            "original_before_sha256": original_sha256,
            "original_after_sha256": original_after_sha256,
            "copied_sha256": copied_sha256,
        }),
    );
    let identity = fixture.identity.identity()?;
    let mut config: HostAuthorityServiceConfig =
        crate::authority_host_config::read_root_json(&fixture.config_path)?;
    config.checkpoint_state_dir = Some(config.state_dir.join("checkpoint"));
    config.consumers = Some(HostAuthorityConsumersConfig {
        device: HostAuthorityConsumerConfig {
            state_dir: config.state_dir.join("device-consumer"),
            owner_id: config.signer_id.clone(),
        },
        notes: HostAuthorityConsumerConfig {
            state_dir: config.state_dir.join("notes-consumer"),
            owner_id: config.signer_id.clone(),
        },
    });
    config.sockets.device_frontier = Some(fixture.lanes.join("device.sock"));
    config.sockets.notes_frontier = Some(fixture.lanes.join("notes.sock"));
    let config_path = fixture.config_path.with_file_name("product-service.json");
    fixture::write_json(&config_path, &config)?;
    let paths = [
        config.sockets.observation.clone(),
        config.sockets.issuer.clone(),
        config.sockets.checkpoint.clone(),
        config.sockets.device_frontier.clone().unwrap(),
        config.sockets.notes_frontier.clone().unwrap(),
    ];
    let endpoint = fixture.lanes.join("delivery.sock");
    let owner = fixture.owner()?;
    let (original_sender, original_receiver) = UnixDatagram::pair()?;
    let (learning_sender, learning_receiver) = UnixDatagram::pair()?;
    let control = crate::bind_root_agentd_socket(
        &identity.control_socket,
        /*uid*/ 60001,
        /*gid*/ 60001,
    )?;
    let app_server = crate::bind_root_agentd_socket(
        &identity.app_server_socket,
        /*uid*/ 60001,
        /*gid*/ 60001,
    )?;
    let sealed_payload = crate::authority_host_bootstrap_seal::seal_bytes(include_bytes!(
        "../tests/fixtures/android-bound-text-v1.json"
    ))?;
    // The original product parser requires a separate read-only description,
    // even though the producer's memfd already has immutable content seals.
    let payload = File::open(format!("/proc/self/fd/{}", sealed_payload.as_raw_fd()))?;
    crate::authority_host_bootstrap_seal::validate_sealed(
        &payload,
        sealed_payload.metadata()?.len(),
    )?;
    drop(sealed_payload);
    let numbers = [
        original_receiver.as_raw_fd(),
        learning_receiver.as_raw_fd(),
        control.as_raw_fd(),
        app_server.as_raw_fd(),
        payload.as_raw_fd(),
    ];
    let error_path = fixture.config_path.with_file_name("product-stderr.log");
    let errors = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&error_path)?;
    let mut clock = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: clock_gettime fills this live, correctly sized timespec.
    assert_eq!(
        unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut clock) },
        0
    );
    let deadline_ns = u64::try_from(clock.tv_sec)? * 1_000_000_000
        + u64::try_from(clock.tv_nsec)?
        + 30_000_000_000;
    let mut command = Command::new(&binary);
    command
        .env_clear()
        .current_dir(&identity.workspace)
        .env("HOME", &identity.home_root)
        .env("CODEX_HOME", &identity.home_root)
        .env(crate::HEPTA_AGENT_ID_ENV, identity.agent_id.as_str())
        .env(
            crate::HEPTA_AGENT_GENERATION_ENV,
            identity.spawn_generation.to_string(),
        )
        .env(crate::HEPTA_AGENT_HOME_ENV, &identity.home_root)
        .env(crate::HEPTA_AGENT_RUN_ROOT_ENV, &identity.run_root)
        .env(
            codex_hepta_paths::HEPTA_FLEET_ROOT_ENV,
            &identity.fleet_root,
        )
        .args(["--root-production-profile", "android"])
        .args([
            "--root-production-uid",
            "60001",
            "--root-production-gid",
            "60001",
        ])
        .args(["--root-production-lifetime-ms", "30000"])
        .arg("--root-production-handoff-fd")
        .arg(numbers[0].to_string())
        .arg("--root-learning-checkpoint-handoff-fd")
        .arg(numbers[1].to_string())
        .arg("--root-production-control-fd")
        .arg(numbers[2].to_string())
        .arg("--root-production-app-server-fd")
        .arg(numbers[3].to_string())
        .arg("--android-original-payload-fd")
        .arg(numbers[4].to_string())
        .arg("--android-original-deadline-ns")
        .arg(deadline_ns.to_string())
        // The explicit unconfigured-profile guard must precede any MCP work;
        // these selectors never create a provider or grant an effect capability.
        .args(["--android-runtime-server", "fixture-unconsumed"])
        .args(["--android-runtime-environment", "fixture-unconsumed"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(errors);
    // SAFETY: only the explicitly held fixture descriptors cross exec. The
    // product parser takes each once and reinstates CLOEXEC before its workers.
    unsafe {
        command.pre_exec(move || {
            for number in numbers {
                if libc::fcntl(number, libc::F_SETFD, 0) != 0 {
                    return Err(io::Error::last_os_error());
                }
            }
            Ok(())
        });
    }
    let mut child = command.spawn()?;
    drop((
        original_receiver,
        learning_receiver,
        control,
        app_server,
        payload,
    ));
    let consumer = pidfd(child.id());
    let root = pidfd(std::process::id());
    // Always reap the actual product after setup/serve returns. Its unchanged
    // startup deadline remains the bound if preparation fails before release.
    let served = (|| -> anyhow::Result<io::Result<()>> {
        let end = Instant::now() + Duration::from_secs(10);
        while crate::authority_host_runtime::verify_process_credentials(child.id(), 60001, 60001)
            .is_err()
        {
            anyhow::ensure!(Instant::now() < end && child.try_wait()?.is_none());
            std::thread::sleep(Duration::from_millis(5));
        }
        let registration = HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: child.id(),
            boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                .trim()
                .into(),
            process_start_ticks: process_start(child.id())?,
            registered_identity: fixture.identity.clone(),
            checkpoint_owner_agent_id: fixture.identity.agent_id.clone(),
            publisher_epoch: 1,
        };
        let registration_path = fixture
            .config_path
            .with_file_name("product-registration.json");
        fixture::write_json(&registration_path, &registration)?;
        // Release initialization handles before the sole original runtime open.
        drop(fixture.service);
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let session = runtime.block_on(
            crate::PreparedHostAuthoritySession::prepare_fresh_from_registered(
                &config_path,
                &registration_path,
                consumer,
            ),
        )?;
        let (session, local) = session.handoff_fresh_agent_filesystem()?;
        let bootstrap = session.seal_bootstrap(&local)?;
        Ok(session.serve_with_registered_learning_checkpoint(
            owner,
            endpoint.clone(),
            learning_sender,
            root.try_clone()?,
            || {
                assert!(paths.iter().all(|path| path.exists()) && endpoint.exists());
                crate::send_root_production_handoff(
                    original_sender,
                    &bootstrap,
                    &root,
                    Duration::from_secs(5),
                )
                .map_err(io::Error::other)
            },
        ))
    })();
    let status = child.wait()?;
    let stderr = std::fs::read_to_string(&error_path)?;
    eprintln!(
        "actual product pid={} status={status} stderr={stderr}",
        child.id()
    );
    let served = served?;
    eprintln!("original Root scope after explicit product refusal: {served:?}");
    assert!(!status.success());
    // This exact run error is reachable only after all five original lanes,
    // writer authentication, same-Root learning admission and fresh restore.
    assert!(stderr.contains(
        "learning checkpoint delivered but no complete production learning profile is configured"
    ), "actual product refused elsewhere: {stderr}");
    assert!(paths.iter().all(|path| !path.exists()) && !endpoint.exists());
    // Root retains the separate control-path custody; the refused product never
    // listened, and dropping its descriptors does not unlink someone else's node.
    assert!(UnixStream::connect(&identity.control_socket).is_err());
    assert!(UnixStream::connect(&identity.app_server_socket).is_err());
    std::fs::remove_file(&identity.control_socket)?;
    std::fs::remove_file(&identity.app_server_socket)?;
    let initial = data::snapshots()?.remove(0);
    let reopened = LearningIterationCheckpointOwnerV1::from_registered(
        HostAuthorityFrontierStore::open(fixture.directory.clone(), data::OWNER.into())?,
        data::OWNER.into(),
        initial.request.clone(),
        initial.owners,
    )?;
    assert_eq!(reopened.restore(&initial.request)?, None);
    Ok(())
}

fn binary_sha256(path: &std::path::Path) -> io::Result<String> {
    let mut file = std::fs::File::open(path)?;
    let mut hash = sha2::Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hash.finalize()))
}
