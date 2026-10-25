//! Real Linux children and original Registry/Supervisor transitions. These
//! tests do not give the children native roles or claim a G2 guest execution.

use super::*;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::time::Instant;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;
const CHILD_SOCKET: &str = "HEPTA_PRECREATED_TEST_SOCKET";
const CHILD_OUTPUT: &str = "HEPTA_PRECREATED_TEST_OUTPUT";
const CHILD_DESCRIPTOR: &str = "HEPTA_PRECREATED_TEST_DESCRIPTOR";

struct ChildGuard(Child);
impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn child_at(
    root: &Path,
    descriptor: bool,
) -> TestResult<(
    ChildGuard,
    UnixStream,
    OwnedFd,
    HostIssuerPeer,
    AgentCommand,
)> {
    let socket = root.join("precreated.sock");
    let listener = UnixListener::bind(&socket)?;
    listener.set_nonblocking(true)?;
    let command = AgentCommand::new(
        std::env::current_exe()?,
        vec![
            "--exact".into(),
            "unix::precreated::tests::precreated_child".into(),
            "--nocapture".into(),
        ],
    )?;
    let child = ChildGuard(
        Command::new(&command.program)
            .args(&command.args)
            .env(CHILD_SOCKET, &socket)
            .env(CHILD_OUTPUT, root.join("received.json"))
            .env(CHILD_DESCRIPTOR, if descriptor { "1" } else { "0" })
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?,
    );
    let pid = rustix::process::Pid::from_raw(child.0.id() as i32).ok_or("invalid child pid")?;
    // Retain Child and pin before accepting its connection; never reopen a
    // numeric PID learned from an incoming request.
    let pin = rustix::process::pidfd_open(pid, rustix::process::PidfdFlags::empty())?;
    let deadline = Instant::now() + Duration::from_secs(5);
    let stream = loop {
        match listener.accept() {
            Ok((stream, _)) => break stream,
            Err(error)
                if error.kind() == std::io::ErrorKind::WouldBlock && Instant::now() < deadline =>
            {
                std::thread::sleep(Duration::from_millis(2));
            }
            Err(error) => return Err(error.into()),
        }
    };
    let peer = HostIssuerPeer {
        uid: rustix::process::getuid().as_raw(),
        pid: child.0.id(),
    };
    Ok((child, stream, pin, peer, command))
}

#[test]
fn precreated_child() -> TestResult {
    let Some(socket) = std::env::var_os(CHILD_SOCKET) else {
        return Ok(());
    };
    let output = std::env::var_os(CHILD_OUTPUT).ok_or("missing output")?;
    // SAFETY: getppid takes no pointers and reads the actual parent.
    let parent =
        rustix::process::Pid::from_raw(unsafe { libc::getppid() }).ok_or("missing parent")?;
    let parent_pidfd = rustix::process::pidfd_open(parent, rustix::process::PidfdFlags::empty())?;
    let command = AgentCommand::new(
        std::env::current_exe()?,
        std::env::args_os().skip(1).collect(),
    )?;
    let peer = HostIssuerPeer {
        uid: rustix::process::getuid().as_raw(),
        pid: parent.as_raw_nonzero().get() as u32,
    };
    let spec = if std::env::var_os(CHILD_DESCRIPTOR).as_deref() == Some(std::ffi::OsStr::new("1")) {
        let (spec, descriptor) = receive_precreated_spawn_with_descriptor(
            UnixStream::connect(socket)?, parent_pidfd, peer, &command,
        )?;
        let startup = UnixDatagram::from(descriptor);
        assert_eq!(startup.send(b"original child received the actual pair")?, 39);
        spec
    } else {
        receive_precreated_spawn(UnixStream::connect(socket)?, parent_pidfd, peer, &command)?
    };
    let output = PathBuf::from(output);
    let temporary = output.with_extension("pending");
    std::fs::write(&temporary, serde_json::to_vec(&spec)?)?;
    std::fs::rename(temporary, output)?;
    std::thread::park_timeout(Duration::from_secs(10));
    Ok(())
}

#[test]
fn original_supervisor_hands_off_its_real_starting_generation_and_reaps_by_pidfd() -> TestResult {
    original_supervisor_case(false)
}

#[test]
fn original_supervisor_transfers_actual_pair_after_its_real_starting_ack() -> TestResult {
    original_supervisor_case(true)
}

fn original_supervisor_case(descriptor: bool) -> TestResult {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let registered = registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    let (_child, stream, pin, peer, command) = child_at(&root, descriptor)?;
    let bound = PrecreatedChild::from_stream(stream, pin, peer, command.clone())?;
    let (startup, offered) = UnixDatagram::pair()?;
    let bound = if descriptor { bound.with_startup_descriptor(offered.into())? } else { bound };
    let driver = PrecreatedProcessDriver::new(agent.clone(), vec![bound])?;
    let (mut supervisor, _) = crate::Supervisor::recover(
        registry.clone(),
        driver,
        crate::SupervisorConfig::local_default(),
        Instant::now(),
    )?;
    supervisor.start(&agent, command.clone(), Instant::now())?;
    if descriptor {
        startup.set_read_timeout(Some(Duration::from_secs(3)))?;
        let mut bytes = [0_u8; 128];
        let count = startup.recv(&mut bytes)?;
        assert_eq!(&bytes[..count], b"original child received the actual pair");
    }
    let state = registry
        .load()?
        .agents
        .remove(&agent)
        .ok_or("missing agent")?;
    assert_eq!(state.lifecycle.lifecycle, AgentLifecycle::Starting);
    assert!(state.lifecycle.generation > registered.lifecycle.generation);
    let deadline = Instant::now() + Duration::from_secs(3);
    let output = root.join("received.json");
    while !output.exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(2));
    }
    let received: SpawnSpec = serde_json::from_slice(&std::fs::read(output)?)?;
    assert_eq!(
        received,
        SpawnSpec {
            agent_id: agent.clone(),
            generation: state.lifecycle.generation,
            fleet_root: fleet.as_path().to_path_buf(),
            workspace,
            home_root: registered.layout.home_root().to_path_buf(),
            run_root: registered.layout.run_root().to_path_buf(),
            control_socket: registered.layout.agentd_control_socket().to_path_buf(),
            logs_root: registered.layout.logs_root().to_path_buf(),
            command: command.clone(),
        }
    );
    let snapshot = supervisor.snapshot(&agent).ok_or("missing runtime")?;
    assert_eq!(snapshot.process_system_id, Some(u64::from(peer.pid)));
    assert_eq!(snapshot.spawn_generation, Some(state.lifecycle.generation));
    assert!(
        !snapshot.healthy,
        "handoff must not manufacture Agentd health"
    );
    supervisor.kill(&agent)?;
    let deadline = Instant::now() + Duration::from_secs(3);
    while supervisor.snapshot(&agent).ok_or("missing runtime")?.active && Instant::now() < deadline
    {
        supervisor.tick(Instant::now());
        std::thread::sleep(Duration::from_millis(2));
    }
    assert!(!supervisor.snapshot(&agent).ok_or("missing runtime")?.active);
    assert!(crate::lease::read_lease(registered.layout.run_root())?.is_none());
    // The original Registry can attempt another Starting transition, but this
    // driver cannot fork a substitute or reuse an already consumed role.
    assert!(supervisor.start(&agent, command, Instant::now()).is_err());
    assert!(!supervisor.snapshot(&agent).ok_or("missing runtime")?.active);
    Ok(())
}

#[test]
fn precreated_binding_rejects_a_foreign_pidfd_and_a_changed_executable_command() -> TestResult {
    for foreign_fd in [true, false] {
        let temp = tempfile::tempdir()?;
        let (_child, stream, pin, peer, mut command) = child_at(temp.path(), false)?;
        let pin = if foreign_fd {
            rustix::process::pidfd_open(
                rustix::process::getpid(),
                rustix::process::PidfdFlags::empty(),
            )?
        } else {
            command.args.push("unexecuted-extra-argument".into());
            pin
        };
        assert!(PrecreatedChild::from_stream(stream, pin, peer, command).is_err());
    }
    Ok(())
}
