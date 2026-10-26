//! Actual original Supervisor and Root startup, without a parallel owner ledger.
use super::boot::Boot;
use super::ipc;
use super::paths;
use super::provision;
use super::supervisor;
use super::workload;
use codex_hepta_agentd::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

pub(super) struct Activation {
    pub(super) registry: FleetRegistry,
    pub(super) agent: AgentId,
    pub(super) supervisor: supervisor::NativeSupervisor,
    pub(super) config: HostAuthorityServiceConfig,
    pub(super) registration: HostAuthorityRegistration,
    pub(super) proof: HostSignedWriterAuthorizationV1,
    pub(super) prepared: PreparedHostAuthoritySession,
    pub(super) consumers: PathBuf,
    pub(super) manager_handoff: UnixDatagram,
    pub(super) recovery_handoff: UnixDatagram,
    pub(super) manager_requests: UnixListener,
    pub(super) recovery_requests: UnixListener,
    pub(super) workload: UnixListener,
    pub(super) recovery_observer: UnixListener,
    pub(super) heartbeat: workload::Heartbeat,
}

pub(super) fn path(role: &str, lane: &str) -> PathBuf {
    Path::new(paths::RUNTIME).join(format!("{role}-{lane}.sock"))
}

pub(super) fn fresh(boot: &Boot) -> Result<Activation, Box<dyn std::error::Error>> {
    paths::prepare_runtime()?;
    let manager_launch = ipc::listener(&path("manager", "launch"), 60001)?;
    let recovery_launch = ipc::listener(&path("recovery", "launch"), 60001)?;
    let manager_requests = ipc::listener(&path("manager", "requests"), 60001)?;
    let recovery_requests = ipc::listener(&path("recovery", "requests"), 60001)?;
    let recovery_observer = ipc::listener(Path::new(super::native_observer::SOCKET), 60001)?;
    let heartbeat = workload::Heartbeat::create()?;
    let workload = ipc::listener(Path::new(workload::SOCKET), 60002)?;
    // The peers can connect and drop privileges before storage initialization;
    // their actual original SpawnSpec is not sent until Supervisor.start.
    let mut selected = Vec::new();
    let mut handoffs = Vec::new();
    for (listener, pid) in [
        (&manager_launch, boot.pids[0]),
        (&recovery_launch, boot.pids[2]),
    ] {
        let stream = ipc::accept(listener, pid)?;
        let (root, child) = UnixDatagram::pair()?;
        selected.push((stream, supervisor::pin(pid)?, pid, child));
        handoffs.push(root);
    }
    paths::mount_fresh()?;
    let (registry, agent) = provision::fresh_registry()?;
    let initialized = provision::initialize_authority(boot, &agent)?;
    let supervisor = supervisor::start_original(registry.clone(), agent.clone(), selected)?;
    let (config, registration, proof) =
        provision::register_initial(boot, &registry, &agent, initialized)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let prepared = runtime.block_on(
        PreparedHostAuthoritySession::prepare_fresh_with_physical_material(
            Path::new(provision::CONFIG),
            Path::new(provision::REGISTRATION),
            supervisor::pin(boot.pids[0])?,
        ),
    )?;
    let (prepared, consumers) = prepared.handoff_fresh_agent_filesystem()?;
    let mut handoffs = handoffs.into_iter();
    Ok(Activation {
        registry,
        agent,
        supervisor,
        config,
        registration,
        proof,
        prepared,
        consumers,
        manager_handoff: handoffs.next().ok_or("manager handoff absent")?,
        recovery_handoff: handoffs.next().ok_or("recovery handoff absent")?,
        manager_requests,
        recovery_requests,
        workload,
        recovery_observer,
        heartbeat,
    })
}

pub(super) fn send_original(
    prepared: &PreparedHostAuthoritySession,
    consumers: &Path,
    handoff: UnixDatagram,
) -> Result<(), Box<dyn std::error::Error>> {
    let bootstrap = prepared.seal_bootstrap(consumers)?;
    let root = supervisor::pin(1)?;
    let writer = prepared.original_root_writer_descriptor()?;
    // This consumes the single exported OFD. Root does not retain a clone that
    // could keep the original owner's flock alive after the actual child exit.
    send_root_production_writer_handoff(
        handoff,
        &bootstrap,
        &root,
        writer,
        Duration::from_millis(500),
    )?;
    Ok(())
}

pub(super) fn wait_lanes(config: &HostAuthorityServiceConfig) -> std::io::Result<()> {
    use std::os::unix::fs::FileTypeExt;
    let end = std::time::Instant::now() + Duration::from_millis(config.timeout_ms);
    let device = config
        .sockets
        .device_frontier
        .as_ref()
        .ok_or_else(|| std::io::Error::other("device lane absent"))?;
    let notes = config
        .sockets
        .notes_frontier
        .as_ref()
        .ok_or_else(|| std::io::Error::other("notes lane absent"))?;
    loop {
        if [
            &config.sockets.observation,
            &config.sockets.issuer,
            &config.sockets.checkpoint,
            device,
            notes,
        ]
        .iter()
        .all(|path| std::fs::symlink_metadata(path).is_ok_and(|stat| stat.file_type().is_socket()))
        {
            return Ok(());
        }
        if std::time::Instant::now() >= end {
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                "original five lanes not bound",
            ));
        }
        std::thread::sleep(Duration::from_millis(2));
    }
}
