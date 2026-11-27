//! Bind already kernel-created roles through the original Supervisor objects.
//! This module never forks, execs, fabricates a generation, or creates a grant.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_supervisor::PrecreatedChild;
use codex_hepta_supervisor::PrecreatedProcessDriver;
use codex_hepta_supervisor::SpawnSpec;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use std::io;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

pub(super) type NativeSupervisor = Supervisor<PrecreatedProcessDriver>;

pub(super) fn actual_command() -> Result<AgentCommand, Box<dyn std::error::Error>> {
    let executable = std::fs::read_link("/proc/self/exe")?;
    let arguments = std::env::args_os().skip(1).collect();
    Ok(AgentCommand::new(executable, arguments)?)
}

pub(super) fn start_original(
    registry: FleetRegistry,
    agent: AgentId,
    selected: Vec<(UnixStream, OwnedFd, u32, UnixDatagram)>,
) -> Result<NativeSupervisor, Box<dyn std::error::Error>> {
    let command = actual_command()?;
    let mut children = Vec::new();
    for (stream, pidfd, pid, handoff) in selected {
        // The kernel created these exact children. They opened their own native
        // control while Root, then dropped to the original dedicated UID before
        // their future Supervisor generation was selected.
        let child = PrecreatedChild::from_stream(
            stream,
            pidfd,
            HostIssuerPeer { uid: 60001, pid },
            command.clone(),
        )?
        .with_startup_descriptor(handoff.into())?;
        children.push(child);
    }
    let driver = PrecreatedProcessDriver::new(agent.clone(), children)?;
    let (mut supervisor, _) = Supervisor::recover(
        registry,
        driver,
        SupervisorConfig::local_default(),
        Instant::now(),
    )?;
    supervisor.start(&agent, command, Instant::now())?;
    Ok(supervisor)
}

pub(super) fn receive_original(
    stream: UnixStream,
) -> Result<(SpawnSpec, UnixDatagram), Box<dyn std::error::Error>> {
    super::ipc::wait_selected(&stream)?;
    let command = actual_command()?;
    let (spec, descriptor) = codex_hepta_supervisor::receive_precreated_spawn_with_descriptor(
        stream,
        pin(/*pid*/ 1)?,
        HostIssuerPeer { uid: 0, pid: 1 },
        &command,
    )?;
    Ok((spec, UnixDatagram::from(descriptor)))
}

pub(super) fn connect_parent(path: &Path) -> io::Result<UnixStream> {
    let end = Instant::now() + Duration::from_secs(2);
    loop {
        match UnixStream::connect(path) {
            Ok(stream) => return Ok(stream),
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::NotFound | io::ErrorKind::ConnectionRefused
                ) && Instant::now() < end =>
            {
                std::thread::sleep(Duration::from_millis(2));
            }
            Err(error) => return Err(error),
        }
    }
}

pub(super) fn pin(pid: u32) -> io::Result<OwnedFd> {
    if pid == 0 || pid > i32::MAX as u32 {
        return Err(io::Error::other("actual native PID out of range"));
    }
    // SAFETY: pidfd_open receives an in-range actual kernel-selected PID and
    // zero flags. It grants no process role or authority; original consumers
    // independently verify peer credentials, fdinfo, birth and liveness.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if raw < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful pidfd_open returned a fresh uniquely owned descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(raw as i32) })
}
