use super::common::*;
use codex_hepta_agentd::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_fleet::*;
use codex_hepta_memory::*;
use codex_hepta_paths::HeptaFleetRoot;
use std::fs::File;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

fn mount(source: &str, target: &str, fs: Option<&str>, flags: libc::c_ulong) -> Result<()> {
    let source = std::ffi::CString::new(source)?;
    let target = std::ffi::CString::new(target)?;
    let fs = fs.map(std::ffi::CString::new).transpose()?;
    anyhow::ensure!(
        unsafe {
            libc::mount(
                source.as_ptr(),
                target.as_ptr(),
                fs.as_ref().map_or(std::ptr::null(), |fs| fs.as_ptr()),
                flags,
                std::ptr::null(),
            )
        } == 0,
        "mount: {}",
        std::io::Error::last_os_error()
    );
    Ok(())
}

pub fn run(boot: Boot) -> Result<()> {
    anyhow::ensure!(unsafe { libc::geteuid() } == 0, "Root role credentials");
    for (target, fs) in [("/dev", "devtmpfs"), ("/proc", "proc"), ("/sys", "sysfs")] {
        std::fs::create_dir_all(target)?;
        mount("none", target, Some(fs), 0)?;
    }
    std::fs::create_dir_all("/sys/fs/cgroup")?;
    mount("none", "/sys/fs/cgroup", Some("cgroup2"), 0)?;
    for path in ["/mnt/hepta-store", ROOT, RUN] {
        std::fs::create_dir_all(path)?;
    }
    mount(
        "/dev/vda",
        "/mnt/hepta-store",
        Some("ext2"),
        libc::MS_NOSUID | libc::MS_NODEV | libc::MS_NOEXEC,
    )?;
    let source = Path::new("/mnt/hepta-store/native-root");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(source)
        .or_else(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                Ok(())
            } else {
                Err(error)
            }
        })?;
    std::fs::set_permissions(ROOT, std::fs::Permissions::from_mode(0o700))?;
    mount(
        source
            .to_str()
            .ok_or_else(|| anyhow::anyhow!("source encoding"))?,
        ROOT,
        None,
        libc::MS_BIND,
    )?;
    chown(Path::new(RUN), 0, 60002)?;
    std::fs::set_permissions(RUN, std::fs::Permissions::from_mode(0o2710))?;
    let mode = super::history::requested_case()?;
    if Path::new(STATE).exists() {
        anyhow::ensure!(
            mode == super::history::Case::CrashAfterApplied,
            "existing owner only permits explicit historical qualification"
        );
        return super::history::historical_root(boot);
    }
    super::history::publish_case(mode)?;
    for parent in [
        "/mnt/hepta-store/agent-owner",
        "/mnt/hepta-store/consumer-local",
    ] {
        if !Path::new(parent).exists() {
            std::fs::DirBuilder::new().mode(0o700).create(parent)?;
            chown(Path::new(parent), 60002, 60002)?;
        }
    }
    // Fresh-only qualification: a reboot never substitutes a local rehash for
    // the old Root Current. Recovery is a separately admitted Root transition.
    anyhow::ensure!(
        !Path::new(STATE).exists() && !Path::new(DATA).exists(),
        "existing native owner requires explicit retained-Current recovery"
    );
    std::fs::DirBuilder::new().mode(0o700).create(DATA)?;
    std::fs::DirBuilder::new().mode(0o700).create(LOCAL)?;
    for purpose in ["device", "notes"] {
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(Path::new(LOCAL).join(purpose))?;
    }
    std::fs::create_dir(Path::new(DATA).join("workspace"))?;
    let owner = AgentId::parse(OWNER)?;
    let fleet = HeptaFleetRoot::parse(Path::new(DATA).join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    registry.register(AgentManifest::new(
        owner.clone(),
        WorkspaceBinding::new(Path::new(DATA).join("workspace"), &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(&owner, 0, AgentLifecycle::Starting)?;
    let layout = fleet.layout().agent(&owner);
    println!("HEPTA_NATIVE_GENESIS_BEGIN original_sqlite=true");
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    let cut = runtime.block_on(async {
        let store = CognitiveStore::open(&layout).await?;
        let result = store.recovery_anchor().await;
        store.close().await;
        result
    })?;
    drop(runtime);
    println!("HEPTA_NATIVE_GENESIS_COMPLETE original_sqlite=true");
    handoff_fresh(Path::new(DATA))?;
    handoff_fresh(Path::new(LOCAL))?;
    let owner_pidfd = pidfd(boot.agent_pid)?;
    let deadline = Instant::now() + Duration::from_secs(60);
    loop {
        let status = std::fs::read_to_string(format!("/proc/{}/status", boot.agent_pid))?;
        if status.contains("Uid:\t60002\t60002\t60002\t60002") && status.contains("NoNewPrivs:\t1")
        {
            break;
        }
        anyhow::ensure!(
            Instant::now() < deadline,
            "Agentd credential startup timeout"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
        .trim()
        .to_owned();
    let requested = Hos2InstallBudgetV1 {
        schema_version: 1,
        delivery: Hos2DeliveryId::new(
            boot.bytes[96..112].try_into()?,
            boot.bytes[128..144].try_into()?,
            1,
        )
        .map_err(anyhow::Error::msg)?,
        manage_slot: 2,
        manage_generation: 1,
        expected_revision: 1,
        period_ns: HOS2_CPU_PERIOD_NS,
        cap_ns: 25_000_000,
    };
    let payload = requested.to_json().map_err(anyhow::Error::msg)?;
    let metadata = std::fs::metadata(ROOT)?;
    let bind = serde_json::json!({"mountpoint":ROOT,"source_path":source,"device":metadata.dev(),"inode":metadata.ino()});
    let admin = Path::new(ROOT).join("g2-admin");
    std::fs::DirBuilder::new().mode(0o700).create(&admin)?;
    let bootstrap_path = admin.join("initialize.json");
    write_json(
        &bootstrap_path,
        &serde_json::json!({
            "schema_version":1,"required_bind":bind,"signer_id":"native-root-qualification-v1",
            "policies":[DeploymentGrantPolicy { subject_id:OWNER.into(),destination_id:HOS2_DESTINATION_V1.into(),scope_sha256:*requested.scope_digest().as_array(),lifetime_ms:30000 }],
            "lease_id":"native-root-qualification-v1","lease_binding":AuthorityLeaseBinding {
                principal_id:OWNER.into(),operation_class:"runtime.agentd.production_operation".into(),destination_id:HOS2_DESTINATION_V1.into(),
                scope_sha256:*requested.scope_digest().as_array(),payload_sha256:*codex_hepta_types::Digest32::of_bytes(payload.as_bytes()).as_array()
            },"lease_lifetime_ms":240000
        }),
        0o600,
    )?;
    let initialized = initialize_host_authority(Path::new(STATE), &bootstrap_path)?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_millis() as u64;
    let writer = HostAuthorityWriterRegistration {
        registered_agent_id: owner.clone(),
        spawn_generation: 1,
        owner_epoch: 1,
        local_lease_id: "native-original-writer".into(),
        local_lease_generation: 1,
        authority_lease: codex_hepta_contracts::authority_lease::AuthorityLease {
            schema_version: 1,
            lease_id: "native-original-writer".into(),
            authority_epoch: 1,
            revision: 1,
            binding: AuthorityLeaseBinding {
                principal_id: OWNER.into(),
                operation_class: "runtime.agentd.production_writer".into(),
                destination_id: "native.qualification.cognitive-owner".into(),
                scope_sha256: [6; 32],
                payload_sha256: [7; 32],
            },
            issued_at_unix_ms: now,
            expires_at_unix_ms: now + 240000,
        },
    };
    let config = serde_json::json!({
        "schema_version":1,"state_dir":STATE,"required_bind":bind,"signer_id":initialized.signer_id,
        "expected_verifying_key":initialized.verifying_key,"lease_id":initialized.lease_id,"lease_revision":initialized.lease_revision,
        "writer":writer,"checkpoint_state_dir":Path::new(STATE).join("checkpoint"),
        "consumers": {"device":{"state_dir":Path::new(STATE).join("device-frontier"),"owner_id":initialized.signer_id},
            "notes":{"state_dir":Path::new(STATE).join("notes-frontier"),"owner_id":initialized.signer_id}},
        "sockets":{"observation":Path::new(RUN).join("observation.sock"),"issuer":Path::new(RUN).join("issuer.sock"),
            "checkpoint":Path::new(RUN).join("checkpoint.sock"),"device_frontier":Path::new(RUN).join("device.sock"),"notes_frontier":Path::new(RUN).join("notes.sock")},
        "peer_uid":60002,"peer_gid":60002,"timeout_ms":10000,"lifetime_ms":240000
    });
    let registration = serde_json::json!({"schema_version":1,"peer_pid":boot.agent_pid,"boot_id":boot_id,
        "process_start_ticks":ticks(boot.agent_pid)?,"checkpoint_owner_agent_id":owner,"publisher_epoch":1,
        "registered_identity":{"agent_id":owner,"spawn_generation":1,"fleet_root":Path::new(DATA).join("fleet"),
            "workspace":Path::new(DATA).join("workspace"),"resources":ResourceBudget::local_default()}});
    let config_path = admin.join("service.json");
    let registration_path = admin.join("registered.json");
    write_json(&config_path, &config, 0o600)?;
    write_json(&registration_path, &registration, 0o600)?;
    register_host_writer_authorization(&config_path)?;
    initialize_host_authority_owners(&config_path, &registration_path, cut)?;
    let bundle = capture_host_authority_bootstrap(
        &config_path,
        &registration_path,
        HostAuthorityLocalConsumers {
            device: Path::new(LOCAL).join("device"),
            notes: Path::new(LOCAL).join("notes"),
        },
    )?;
    let handoff = Path::new(RUN).join(".bootstrap");
    write_json(&handoff, &bundle, 0o440)?;
    chown(&handoff, 0, 60002)?;
    std::fs::rename(handoff, Path::new(RUN).join("bootstrap.json"))?;
    File::open(RUN)?.sync_all()?;
    println!("HEPTA_NATIVE_ROOT_SERVICE_BEGIN peer_uid=60002 production_ready=false");
    let crash_monitor = (mode == super::history::Case::CrashAfterApplied).then(|| {
        let bytes = boot.bytes.clone();
        let pid = boot.agent_pid;
        std::thread::spawn(move || {
            if let Err(error) = super::history::monitor_crash(bytes, pid) {
                eprintln!("HEPTA_NATIVE_FAILURE crash_monitor={error:#}");
            }
        })
    });
    let result = serve_host_authority_session(&config_path, &registration_path, owner_pidfd);
    println!("HEPTA_NATIVE_ROOT_SERVICE_END result={result:?}");
    if let Some(monitor) = crash_monitor {
        let _ = monitor.join();
        return Err(anyhow::anyhow!(
            "crash qualification did not end at actual VM kill"
        ));
    }
    let mut status = 0;
    anyhow::ensure!(
        unsafe { libc::waitpid(boot.agent_pid as i32, &mut status, 0) } == boot.agent_pid as i32
            && libc::WIFEXITED(status)
            && libc::WEXITSTATUS(status) == 0,
        "original Agentd child did not finish cleanly"
    );
    let report_path = Path::new(DATA).join("report.json");
    let report: serde_json::Value = read_json(&report_path, 60002)?;
    anyhow::ensure!(
        report["terminal"] == "committed" && report["native_retired_through"] == 1,
        "native owner report failed"
    );
    use codex_hepta_contracts::AuthorityFrontierStore;
    let head = codex_hepta_contracts::HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
        codex_hepta_contracts::RootAuthorityDirectory::open(&Path::new(STATE).join("checkpoint"))?,
        "root-cognitive-checkpoint-v1".into(),
    )?
    .load("root-cognitive-checkpoint-v1")?;
    anyhow::ensure!(
        head.phase == CognitiveCheckpointPhase::Current
            && serde_json::to_value(head.last_current)? == report["current_cut"],
        "independent Root Current differs"
    );
    println!("HEPTA_NATIVE_COMPLETE {report}");
    File::open(ROOT)?.sync_all()?;
    unsafe {
        libc::reboot(libc::RB_POWER_OFF);
    }
    Err(anyhow::anyhow!("poweroff returned"))
}
