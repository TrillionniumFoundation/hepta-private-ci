//! Actual sockets and a live unrelated child exercise the real driver boundary.

use std::io;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::Duration;

use crate::ProcessIdentity;
use codex_hepta_agent_protocol::HealthSnapshot;
use pretty_assertions::assert_eq;

use super::socket_fixture_io::FixtureIo;
use super::socket_fixture_io::FrameEnd;
use super::socket_fixture_io::context;
use super::*;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn short_socket_tempdir() -> io::Result<tempfile::TempDir> {
    tempfile::Builder::new()
        .prefix("hsup-peer-")
        .tempdir_in("/tmp")
}

struct OwnedChild(Child);

impl OwnedChild {
    fn new() -> io::Result<Self> {
        Command::new("/bin/sleep").arg("30").spawn().map(Self)
    }
}

impl Drop for OwnedChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

struct ForgedServer {
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<io::Result<(usize, usize)>>>,
}

impl ForgedServer {
    fn new(path: &Path, response: serde_json::Value) -> io::Result<Self> {
        let listener = UnixListener::bind(path).map_err(|error| {
            io::Error::new(
                error.kind(),
                format!("bind forged peer listener {}: {error}", path.display()),
            )
        })?;
        listener
            .set_nonblocking(/*nonblocking*/ true)
            .map_err(|error| context("set forged listener nonblocking", error))?;
        let stop = Arc::new(AtomicBool::new(false));
        let worker_stop = Arc::clone(&stop);
        let worker = std::thread::spawn(move || {
            let mut connections = 0;
            let mut request_bytes = 0;
            loop {
                let (stream, _) = match listener.accept() {
                    Ok(connection) => connection,
                    Err(error)
                        if matches!(
                            error.kind(),
                            io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                        ) =>
                    {
                        if worker_stop.load(Ordering::Acquire) {
                            return Ok((connections, request_bytes));
                        }
                        std::thread::sleep(Duration::from_millis(1));
                        continue;
                    }
                    Err(error) => return Err(context("accept forged peer", error)),
                };
                connections += 1;
                let mut stream = FixtureIo::new(stream, Duration::from_millis(200))?;
                let request = stream.read_frame(FrameEnd::Newline)?;
                request_bytes += request.len();
                if request.is_empty() {
                    continue;
                }
                let request: serde_json::Value = serde_json::from_slice(&request)?;
                let mut reply = response.clone();
                reply["request_id"] = request["request_id"].clone();
                let mut reply = serde_json::to_vec(&reply)?;
                reply.push(b'\n');
                stream.write_frame(&reply)?;
            }
        });
        Ok(Self {
            stop,
            worker: Some(worker),
        })
    }

    fn finish(mut self) -> TestResult<(usize, usize)> {
        self.stop.store(true, Ordering::Release);
        let worker = self.worker.take().expect("server worker");
        Ok(worker
            .join()
            .map_err(|_| io::Error::other("forged server panicked"))??)
    }
}

impl Drop for ForgedServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn agent_identity(temp: &tempfile::TempDir, pid: u32) -> TestResult<AgentHealthProbeIdentity> {
    Ok(AgentHealthProbeIdentity {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        spawn_generation: 7,
        process_id: pid,
        workspace: temp.path().join("workspace"),
        home_root: temp.path().join("home"),
        run_root: temp.path().join("run"),
        control_socket: temp.path().join("control.sock"),
    })
}

#[test]
fn kernel_peer_identity_accepts_the_actual_socket_pair_process() -> TestResult {
    let (first, second) = UnixStream::pair()?;
    peer_identity::ensure_process_peer(&first, std::process::id())?;
    peer_identity::ensure_process_peer(&second, std::process::id())?;
    Ok(())
}

#[test]
fn kernel_peer_identity_rejects_a_different_live_process_and_invalid_pid() -> TestResult {
    let child = OwnedChild::new()?;
    let (stream, _peer) = UnixStream::pair()?;
    assert_eq!(
        peer_identity::ensure_process_peer(&stream, child.0.id())
            .expect_err("different peer")
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    for pid in [0, u32::MAX] {
        assert_eq!(
            peer_identity::ensure_process_peer(&stream, pid)
                .expect_err("invalid PID")
                .kind(),
            io::ErrorKind::InvalidInput
        );
    }
    Ok(())
}

#[test]
fn forged_agentd_health_cannot_adopt_or_signal_an_unrelated_child() -> TestResult {
    let temp = short_socket_tempdir()?;
    let mut child = OwnedChild::new()?;
    let identity = agent_identity(&temp, child.0.id())?;
    let response = AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 0,
        agent_id: identity.agent_id.clone(),
        spawn_generation: identity.spawn_generation,
        current_generation: identity.spawn_generation,
        payload: AgentdPayload::Health(HealthSnapshot {
            promotion_ready: true,
            ready: false,
            fenced: false,
            lifecycle: AgentLifecycle::Starting,
            process_id: child.0.id(),
            workspace: identity.workspace.clone(),
            home_root: identity.home_root.clone(),
            run_root: identity.run_root.clone(),
        }),
    };
    let server = ForgedServer::new(&identity.control_socket, serde_json::to_value(response)?)?;
    let mut driver = UnixProcessDriver::new(1)?;
    let observed = driver.adopt(&AdoptSpec {
        agent_id: identity.agent_id,
        registry_generation: identity.spawn_generation,
        spawn_generation: identity.spawn_generation,
        workspace: identity.workspace,
        home_root: identity.home_root,
        run_root: identity.run_root,
        control_socket: identity.control_socket,
        identity: ProcessIdentity::new(u64::from(child.0.id()), "unrelated-agent-child")?,
    })?;
    assert!(matches!(observed, Adoption::Rejected));
    assert_eq!(
        server.finish()?,
        (usize::try_from(ADOPTION_PROBE_ATTEMPTS)?, 0)
    );
    assert!(child.0.try_wait()?.is_none());
    Ok(())
}

#[test]
fn forged_matrix_health_cannot_adopt_or_signal_an_unrelated_child() -> TestResult {
    let temp = short_socket_tempdir()?;
    let mut child = OwnedChild::new()?;
    let spec = MatrixAdoptSpec {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        agent_generation: 7,
        binding_revision: 11,
        binding_digest: Sha256Digest::for_bytes(b"binding"),
        release_id: codex_hepta_fleet::ReleaseId::parse("matrix-v1")?,
        process_incarnation: "matrix-incarnation".to_string(),
        plane_epoch: 13,
        control_socket: temp.path().join("matrix.sock"),
        identity: ProcessIdentity::new(u64::from(child.0.id()), "unrelated-matrix-child")?,
    };
    let response = MatrixdResponse {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id: 0,
        agent_id: spec.agent_id.clone(),
        release_id: spec.release_id.to_string(),
        binding_revision: spec.binding_revision,
        binding_digest: spec.binding_digest.clone(),
        attached_agent_generation: spec.agent_generation,
        process_incarnation: spec.process_incarnation.clone(),
        plane_epoch: spec.plane_epoch,
        payload: MatrixdPayload::Health(MatrixdHealth {
            lifecycle: MatrixdLifecycle::Ready,
            process_id: child.0.id(),
            agentd_connected: true,
            matrix_sync_connected: true,
            fenced: false,
        }),
    };
    let server = ForgedServer::new(&spec.control_socket, serde_json::to_value(response)?)?;
    let mut driver = UnixProcessDriver::new(1)?;
    assert!(matches!(driver.adopt_matrixd(&spec)?, Adoption::Rejected));
    assert_eq!(
        server.finish()?,
        (usize::try_from(ADOPTION_PROBE_ATTEMPTS)?, 0)
    );
    assert!(child.0.try_wait()?.is_none());
    Ok(())
}

#[test]
fn drain_never_sends_a_frame_to_a_socket_owned_by_another_process() -> TestResult {
    let temp = short_socket_tempdir()?;
    let mut child = OwnedChild::new()?;
    let identity = agent_identity(&temp, child.0.id())?;
    let response = AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 0,
        agent_id: identity.agent_id.clone(),
        spawn_generation: identity.spawn_generation,
        current_generation: identity.spawn_generation + 2,
        payload: AgentdPayload::Drain(codex_hepta_agent_protocol::DrainSnapshot {
            admission_closed: true,
            running_turns: 0,
            drained: true,
            lifecycle: AgentLifecycle::Draining,
            fenced: false,
        }),
    };
    let server = ForgedServer::new(&identity.control_socket, serde_json::to_value(response)?)?;
    let result = query_agent_drain_once(&identity, 1);
    assert!(
        result
            .expect_err("foreign drain peer")
            .to_string()
            .contains("control socket peer")
    );
    assert_eq!(server.finish()?, (1, 0));
    assert!(child.0.try_wait()?.is_none());
    Ok(())
}
