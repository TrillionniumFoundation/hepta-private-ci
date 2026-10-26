//! One actual PID-1 administrator and single serializer for original owner work.
use super::activation;
use super::boot::Boot;
use super::boundary;
use super::cycle;
use super::evidence;
use super::evidence::Evidence;
use super::ipc;
use super::paths;
use super::provision;
use codex_hepta_agentd::HostAuthorityServiceConfig;
use codex_hepta_agentd::HostSignedWriterAuthorizationV1;
use codex_hepta_agentd::PreparedHostAuthoritySession;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_fleet::FleetRegistry;
use serde_json::Value;
use std::fs::File;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::sync::Arc;

pub(super) fn run(boot: Boot, control: File) -> Result<(), Box<dyn std::error::Error>> {
    boot.authenticate_root(&control)?;
    let mut evidence = Evidence::read()?;
    let activation = activation::fresh(&boot)?;
    let activation::Activation {
        registry,
        agent,
        mut supervisor,
        config,
        registration,
        proof,
        prepared,
        consumers,
        manager_handoff,
        recovery_handoff,
        manager_requests,
        recovery_requests,
        workload,
        recovery_observer,
        heartbeat,
    } = activation;
    let mut observer = ipc::channel(&recovery_observer, boot.pids[2], 60001)?;
    let prepared = Arc::new(prepared);
    let serving = Arc::clone(&prepared);
    let service = std::thread::spawn(move || serving.serve_retained());
    activation::wait_lanes(&config)?;
    activation::send_original(&prepared, &consumers, manager_handoff)?;
    let mut manager = ipc::channel(&manager_requests, boot.pids[0], 60001)?;
    let (initial, material) = cycle::current(&mut manager, &prepared)?;
    // Root independently observes all actual credentials after both owner roles
    // have dropped them; no role/UID/capability evidence comes from argv.
    evidence.emit("roles", evidence::roles(&boot)?)?;
    emit_state(
        &mut evidence,
        &initial,
        &material,
        registry.load_agent(&agent)?.layout.cognitive_root(),
    )?;
    let mut workload = ipc::channel(&workload, boot.pids[1], 60002)?;
    let mut observed: Value = serde_json::from_slice(&workload.request(b"observe-isolation-v1")?)?;
    let (manage, history) = boundary::statuses(&boot, &control)?;
    let object = observed
        .as_object_mut()
        .ok_or("workload isolation response was not an object")?;
    object.insert("root_manage_status".into(), manage.into());
    object.insert("root_history_status".into(), history.into());
    evidence.emit("boundary", observed)?;
    owner_ready(
        &mut evidence,
        &mut manager,
        &prepared,
        "manager",
        boot.pids[0],
        &registry,
        &agent,
        &config,
        &proof,
    )?;
    if evidence.scenario() == "steady-state-v1" {
        let mut last = Value::Null;
        for (name, cap) in [("lower", 25_000_000), ("pause", 0), ("resume", 50_000_000)] {
            let (_, _, current) = cycle::operate(
                &mut evidence,
                &mut manager,
                &prepared,
                &heartbeat,
                boot.pids[0],
                name,
                cap,
                /*retire*/ true,
            )?;
            last = current;
        }
        evidence.emit(
            "complete",
            serde_json::json!({"root_pid":std::process::id(),"operation_count":3,
            "final_owner_pid":boot.pids[0],"final_current_token":last["token"]}),
        )?;
    } else {
        super::recovery::run(
            &boot,
            &mut evidence,
            manager,
            prepared,
            service,
            &registry,
            &agent,
            &mut supervisor,
            &config,
            &registration,
            &proof,
            recovery_handoff,
            &recovery_requests,
            &mut observer,
            &consumers,
            &heartbeat,
        )?;
    }
    // Only successful actual operations reach original kernel poweroff, whose
    // original debug-exit device emits raw QEMU 33. Returning from PID 1, a
    // timeout, syscall error or panic cannot produce this completion record.
    poweroff()
}

pub(super) fn owner_ready(
    evidence: &mut Evidence,
    channel: &mut HostAuthorityPeerChannel,
    root: &PreparedHostAuthoritySession,
    role: &str,
    pid: u32,
    registry: &FleetRegistry,
    agent: &AgentId,
    config: &HostAuthorityServiceConfig,
    proof: &HostSignedWriterAuthorizationV1,
) -> Result<Value, Box<dyn std::error::Error>> {
    let (owner, physical) = cycle::current(channel, root)?;
    let record = registry.load_agent(agent)?;
    let lock = std::fs::symlink_metadata(record.layout.writer_lock())?;
    evidence.emit(
        "owner_ready",
        serde_json::json!({"role":role,"pid":pid,"agent_id":agent,
        "spawn_generation":record.lifecycle.generation,
        "issuer_key_sha256":codex_hepta_contracts::Sha256Digest::for_bytes(&config.expected_verifying_key),
        "writer_proof_sha256":proof.sha256()?,
        "current":physical.current(),"material_sha256":physical.material_sha256(),
        "device_frontier":owner["device_frontier"],"notes_frontier":owner["notes_frontier"],
        "owner_lock_device":lock.dev(),"owner_lock_inode":lock.ino()}),
    )?;
    Ok(serde_json::to_value(physical.current())?)
}

fn emit_state(
    evidence: &mut Evidence,
    owner: &Value,
    material: &codex_hepta_agentd::HostPhysicalCurrentObservation,
    registered_root: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    let path = Path::new(
        owner["database_path"]
            .as_str()
            .ok_or("original database observation absent")?,
    );
    if path.parent() != Some(registered_root) || path.canonicalize()? != path {
        return Err("database observation is outside its original registered location".into());
    }
    let database = std::fs::symlink_metadata(path)?;
    let retained = std::fs::symlink_metadata(
        Path::new(provision::AUTHORITY)
            .join("cognitive-material-v1")
            .join(format!(
                "image-{}.sqlite3",
                material.material_sha256().as_str()
            )),
    )?;
    let mount = std::fs::metadata(paths::STATE)?;
    let mounts = evidence::bounded_text("/proc/mounts", 32768)?;
    if !mounts.lines().any(|line| {
        line.split_whitespace()
            .take(3)
            .eq(["/dev/vda", "/state", "ext2"])
    }) || !database.is_file()
        || !retained.is_file()
        || retained.uid() != 0
        || retained.mode() & 0o7777 != 0o600
        || retained.len() != material.material_bytes()
    {
        return Err("actual original store/material mount geometry is absent".into());
    }
    evidence.emit(
        "state",
        serde_json::json!({"source":"/dev/vda","target":"/state","filesystem":"ext2",
        "mount_device":mount.dev(),"store_device":database.dev(),"store_inode":database.ino(),
        "root_material_device":retained.dev(),"root_material_inode":retained.ino()}),
    )?;
    Ok(())
}

fn poweroff() -> Result<(), Box<dyn std::error::Error>> {
    use std::io::Write;
    std::io::stdout().flush()?;
    // SAFETY: this is the original privileged Linux reboot ABI with poweroff;
    // all evidence has been emitted before the actual kernel completion.
    unsafe {
        libc::syscall(libc::SYS_sync);
    }
    let result = unsafe {
        libc::syscall(
            libc::SYS_reboot,
            0xfee1dead_u32,
            0x28121969_u32,
            0x4321fedc_u32,
            0,
        )
    };
    Err(io::Error::other(format!(
        "original poweroff unexpectedly returned {result}: {}",
        io::Error::last_os_error()
    ))
    .into())
}
