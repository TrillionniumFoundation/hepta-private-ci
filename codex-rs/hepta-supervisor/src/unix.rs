use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc::Receiver;
use std::sync::mpsc::SyncSender;
use std::sync::mpsc::TryRecvError;
use std::time::Duration;

use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdRequest;
use codex_hepta_agent_protocol::AgentdResponse;
use codex_hepta_agent_protocol::MAX_CONTROL_FRAME_BYTES;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_matrix_protocol::MATRIXD_CONTROL_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MAX_MATRIXD_CONTROL_FRAME_BYTES;
use codex_hepta_matrix_protocol::MatrixdHealth;
use codex_hepta_matrix_protocol::MatrixdLifecycle;
use codex_hepta_matrix_protocol::MatrixdMethod;
use codex_hepta_matrix_protocol::MatrixdPayload;
use codex_hepta_matrix_protocol::MatrixdRequest;
use codex_hepta_matrix_protocol::MatrixdResponse;

use crate::AdoptSpec;
use crate::Adoption;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessExit;
use crate::ProcessIdentity;
use crate::ProcessLog;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::ProcessStream;
use crate::SpawnSpec;
use crate::driver::SpawnedProcess;

const LOG_CHUNK_BYTES: usize = 4_096;
const HEALTH_PROBE_INTERVAL: Duration = Duration::from_millis(50);
const HEALTH_PROBE_IO_TIMEOUT: Duration = Duration::from_millis(200);
const ADOPTION_PROBE_ATTEMPTS: u64 = 3;

/// Unix child wrapper with non-blocking polling and bounded per-child log channels.
pub struct UnixProcessDriver {
    log_channel_capacity: usize,
}

impl UnixProcessDriver {
    pub fn new(log_channel_capacity: usize) -> Result<Self, ProcessDriverError> {
        if !(1..=16_384).contains(&log_channel_capacity) {
            return Err(ProcessDriverError::new(
                "Unix child log channel capacity must be between 1 and 16384",
            ));
        }
        Ok(Self {
            log_channel_capacity,
        })
    }
}

pub struct UnixManagedProcess {
    handle: UnixProcessHandle,
    logs: Receiver<ProcessLog>,
    health_probe: HealthProbe,
}

enum UnixProcessHandle {
    Child(Child),
    Adopted { process_id: u32 },
}

impl UnixProcessHandle {
    fn process_id(&self) -> u32 {
        match self {
            Self::Child(child) => child.id(),
            Self::Adopted { process_id } => *process_id,
        }
    }
}

impl ManagedProcess for UnixManagedProcess {
    fn poll(&mut self, max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let mut logs = Vec::with_capacity(max_logs);
        for _ in 0..max_logs {
            match self.logs.try_recv() {
                Ok(log) => logs.push(log),
                Err(TryRecvError::Empty | TryRecvError::Disconnected) => break,
            }
        }
        let state = match &mut self.handle {
            UnixProcessHandle::Child(child) => match child.try_wait()? {
                Some(status) => {
                    self.health_probe.shutdown();
                    ProcessState::Exited(ProcessExit {
                        success: status.success(),
                        code: status.code(),
                    })
                }
                None => ProcessState::Running {
                    healthy: self.health_probe.ready(),
                    drained: false,
                },
            },
            UnixProcessHandle::Adopted { process_id } => {
                if let Some(exit) = poll_adopted_process(*process_id)? {
                    self.health_probe.shutdown();
                    ProcessState::Exited(exit)
                } else {
                    ProcessState::Running {
                        healthy: self.health_probe.ready(),
                        drained: false,
                    }
                }
            }
        };
        Ok(ProcessObservation { state, logs })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        send_signal(self.handle.process_id(), libc::SIGTERM)
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        send_signal(self.handle.process_id(), libc::SIGTERM)
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        send_signal(self.handle.process_id(), libc::SIGKILL)
    }
}

impl ProcessDriver for UnixProcessDriver {
    type Process = UnixManagedProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let mut command = Command::new(&spec.command.program);
        command
            .args(&spec.command.args)
            .current_dir(&spec.workspace)
            .env("CODEX_HOME", &spec.home_root)
            .env("CODEX_SQLITE_HOME", &spec.home_root)
            .env("HEPTA_AGENT_ID", spec.agent_id.to_string())
            .env("HEPTA_AGENT_GENERATION", spec.generation.to_string())
            .env("HEPTA_FLEET_ROOT", &spec.fleet_root)
            .env("HEPTA_AGENT_HOME", &spec.home_root)
            .env("HEPTA_AGENT_RUN_ROOT", &spec.run_root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut child = command.spawn()?;
        let health_probe = match HealthProbe::spawn(HealthProbeIdentity::Agentd(
            AgentHealthProbeIdentity::from_spawn(spec, child.id()),
        )) {
            Ok(probe) => probe,
            Err(error) => {
                let _ = child.kill();
                return Err(error);
            }
        };
        let Some(stdout) = child.stdout.take() else {
            let _ = child.kill();
            return Err(ProcessDriverError::new("child stdout pipe is missing"));
        };
        let Some(stderr) = child.stderr.take() else {
            let _ = child.kill();
            return Err(ProcessDriverError::new("child stderr pipe is missing"));
        };
        let (sender, logs) = std::sync::mpsc::sync_channel(self.log_channel_capacity);
        spawn_log_reader(stdout, ProcessStream::Stdout, sender.clone());
        spawn_log_reader(stderr, ProcessStream::Stderr, sender);
        let identity = ProcessIdentity::new(
            u64::from(child.id()),
            format!("unix-pid-{}-generation-{}", child.id(), spec.generation),
        )
        .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        Ok(SpawnedProcess {
            identity,
            process: UnixManagedProcess {
                handle: UnixProcessHandle::Child(child),
                logs,
                health_probe,
            },
        })
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        if !process_exists(spec.identity.system_id())? {
            return Ok(Adoption::Missing);
        }
        let process_id = u32::try_from(spec.identity.system_id())
            .map_err(|_| ProcessDriverError::new("stored child PID does not fit u32"))?;
        let health_identity =
            HealthProbeIdentity::Agentd(AgentHealthProbeIdentity::from_adopt(spec, process_id));
        if prove_adoption_identity(&health_identity) {
            let health_probe = HealthProbe::spawn(health_identity)?;
            let (_sender, logs) = std::sync::mpsc::sync_channel(1);
            return Ok(Adoption::Adopted(UnixManagedProcess {
                handle: UnixProcessHandle::Adopted { process_id },
                logs,
                health_probe,
            }));
        }

        // A stale lease PID may already belong to an unrelated process. Failed
        // exact UDS identity proof never grants signal authority over that PID;
        // recovery quarantines the lease and reports Rejected instead.
        Ok(Adoption::Rejected)
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let mut command = Command::new(&spec.command.program);
        command
            .args(&spec.command.args)
            .current_dir(&spec.workspace)
            .env("HEPTA_FLEET_ROOT", &spec.fleet_root)
            .env("HEPTA_AGENT_ID", spec.agent_id.to_string())
            .env("HEPTA_AGENT_GENERATION", spec.agent_generation.to_string())
            .env(
                "HEPTA_MATRIX_BINDING_REVISION",
                spec.binding_revision.to_string(),
            )
            .env("HEPTA_MATRIX_RELEASE_ID", spec.release_id.as_str())
            .env("HEPTA_MATRIX_BINDING_DIGEST", spec.binding_digest.as_str())
            .env(
                "HEPTA_MATRIX_PROCESS_INCARNATION",
                &spec.process_incarnation,
            )
            .env("HEPTA_MATRIX_PLANE_EPOCH", spec.plane_epoch.to_string())
            .env("HEPTA_MATRIXD_CONTROL_SOCKET", &spec.control_socket)
            .env("HEPTA_AGENTD_CONTROL_SOCKET", &spec.agentd_control_socket)
            .env("HEPTA_MATRIX_ROOT", &spec.matrix_root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut child = command.spawn()?;
        let health_probe = match HealthProbe::spawn(HealthProbeIdentity::Matrixd(
            MatrixHealthProbeIdentity::from_spawn(spec, child.id()),
        )) {
            Ok(probe) => probe,
            Err(error) => {
                let _ = child.kill();
                return Err(error);
            }
        };
        let Some(stdout) = child.stdout.take() else {
            let _ = child.kill();
            return Err(ProcessDriverError::new(
                "matrixd child stdout pipe is missing",
            ));
        };
        let Some(stderr) = child.stderr.take() else {
            let _ = child.kill();
            return Err(ProcessDriverError::new(
                "matrixd child stderr pipe is missing",
            ));
        };
        let (sender, logs) = std::sync::mpsc::sync_channel(self.log_channel_capacity);
        spawn_log_reader(stdout, ProcessStream::Stdout, sender.clone());
        spawn_log_reader(stderr, ProcessStream::Stderr, sender);
        let identity = ProcessIdentity::new(
            u64::from(child.id()),
            format!(
                "unix-matrix-pid-{}-agent-generation-{}",
                child.id(),
                spec.agent_generation
            ),
        )
        .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        Ok(SpawnedProcess {
            identity,
            process: UnixManagedProcess {
                handle: UnixProcessHandle::Child(child),
                logs,
                health_probe,
            },
        })
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        if !process_exists(spec.identity.system_id())? {
            return Ok(Adoption::Missing);
        }
        let process_id = u32::try_from(spec.identity.system_id())
            .map_err(|_| ProcessDriverError::new("stored matrixd PID does not fit u32"))?;
        let health_identity =
            HealthProbeIdentity::Matrixd(MatrixHealthProbeIdentity::from_adopt(spec, process_id));
        if prove_adoption_identity(&health_identity) {
            let health_probe = HealthProbe::spawn(health_identity)?;
            let (_sender, logs) = std::sync::mpsc::sync_channel(1);
            return Ok(Adoption::Adopted(UnixManagedProcess {
                handle: UnixProcessHandle::Adopted { process_id },
                logs,
                health_probe,
            }));
        }

        // See agentd adoption above: no exact handshake means no authority to
        // signal a possibly reused PID.
        Ok(Adoption::Rejected)
    }
}

struct HealthProbe {
    ready: Arc<AtomicBool>,
    shutdown: Arc<AtomicBool>,
}

impl HealthProbe {
    fn spawn(identity: HealthProbeIdentity) -> Result<Self, ProcessDriverError> {
        let ready = Arc::new(AtomicBool::new(false));
        let shutdown = Arc::new(AtomicBool::new(false));
        let worker_ready = Arc::clone(&ready);
        let worker_shutdown = Arc::clone(&shutdown);
        std::thread::Builder::new()
            .name(format!("hepta-health-{}", identity.agent_id()))
            .spawn(move || run_health_probe(identity, worker_ready, worker_shutdown))
            .map_err(ProcessDriverError::from)?;
        Ok(Self { ready, shutdown })
    }

    fn ready(&self) -> bool {
        self.ready.load(Ordering::Acquire)
    }

    fn shutdown(&self) {
        self.shutdown.store(true, Ordering::Release);
        self.ready.store(false, Ordering::Release);
    }
}

impl Drop for HealthProbe {
    fn drop(&mut self) {
        self.shutdown();
    }
}

enum HealthProbeIdentity {
    Agentd(AgentHealthProbeIdentity),
    Matrixd(MatrixHealthProbeIdentity),
}

impl HealthProbeIdentity {
    fn agent_id(&self) -> &AgentId {
        match self {
            Self::Agentd(identity) => &identity.agent_id,
            Self::Matrixd(identity) => &identity.agent_id,
        }
    }
}

struct AgentHealthProbeIdentity {
    agent_id: AgentId,
    spawn_generation: u64,
    process_id: u32,
    workspace: PathBuf,
    home_root: PathBuf,
    run_root: PathBuf,
    control_socket: PathBuf,
}

impl AgentHealthProbeIdentity {
    fn from_spawn(spec: &SpawnSpec, process_id: u32) -> Self {
        Self {
            agent_id: spec.agent_id.clone(),
            spawn_generation: spec.generation,
            process_id,
            workspace: spec.workspace.clone(),
            home_root: spec.home_root.clone(),
            run_root: spec.run_root.clone(),
            control_socket: spec.control_socket.clone(),
        }
    }

    fn from_adopt(spec: &AdoptSpec, process_id: u32) -> Self {
        Self {
            agent_id: spec.agent_id.clone(),
            spawn_generation: spec.spawn_generation,
            process_id,
            workspace: spec.workspace.clone(),
            home_root: spec.home_root.clone(),
            run_root: spec.run_root.clone(),
            control_socket: spec.control_socket.clone(),
        }
    }
}

struct MatrixHealthProbeIdentity {
    agent_id: AgentId,
    agent_generation: u64,
    binding_revision: u64,
    binding_digest: Sha256Digest,
    release_id: String,
    process_incarnation: String,
    plane_epoch: u64,
    process_id: u32,
    control_socket: PathBuf,
}

impl MatrixHealthProbeIdentity {
    fn from_spawn(spec: &MatrixSpawnSpec, process_id: u32) -> Self {
        Self {
            agent_id: spec.agent_id.clone(),
            agent_generation: spec.agent_generation,
            binding_revision: spec.binding_revision,
            binding_digest: spec.binding_digest.clone(),
            release_id: spec.release_id.as_str().to_string(),
            process_incarnation: spec.process_incarnation.clone(),
            plane_epoch: spec.plane_epoch,
            process_id,
            control_socket: spec.control_socket.clone(),
        }
    }

    fn from_adopt(spec: &MatrixAdoptSpec, process_id: u32) -> Self {
        Self {
            agent_id: spec.agent_id.clone(),
            agent_generation: spec.agent_generation,
            binding_revision: spec.binding_revision,
            binding_digest: spec.binding_digest.clone(),
            release_id: spec.release_id.as_str().to_string(),
            process_incarnation: spec.process_incarnation.clone(),
            plane_epoch: spec.plane_epoch,
            process_id,
            control_socket: spec.control_socket.clone(),
        }
    }
}

fn run_health_probe(
    identity: HealthProbeIdentity,
    ready: Arc<AtomicBool>,
    shutdown: Arc<AtomicBool>,
) {
    let mut request_id = 1_u64;
    while !shutdown.load(Ordering::Acquire) {
        ready.store(
            probe_health_once(&identity, request_id).unwrap_or(false),
            Ordering::Release,
        );
        request_id = request_id.wrapping_add(1).max(1);
        std::thread::sleep(HEALTH_PROBE_INTERVAL);
    }
    ready.store(false, Ordering::Release);
}

fn probe_health_once(
    identity: &HealthProbeIdentity,
    request_id: u64,
) -> Result<bool, ProcessDriverError> {
    Ok(query_health_once(identity, request_id)?.ready)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct HealthProbeObservation {
    exact_identity: bool,
    ready: bool,
}

fn prove_adoption_identity(identity: &HealthProbeIdentity) -> bool {
    for request_id in 1..=ADOPTION_PROBE_ATTEMPTS {
        if query_health_once(identity, request_id)
            .is_ok_and(|observation| observation.exact_identity)
        {
            return true;
        }
        if request_id != ADOPTION_PROBE_ATTEMPTS {
            std::thread::sleep(HEALTH_PROBE_INTERVAL);
        }
    }
    false
}

fn query_health_once(
    identity: &HealthProbeIdentity,
    request_id: u64,
) -> Result<HealthProbeObservation, ProcessDriverError> {
    match identity {
        HealthProbeIdentity::Agentd(identity) => query_agent_health_once(identity, request_id),
        HealthProbeIdentity::Matrixd(identity) => query_matrix_health_once(identity, request_id),
    }
}

fn query_agent_health_once(
    identity: &AgentHealthProbeIdentity,
    request_id: u64,
) -> Result<HealthProbeObservation, ProcessDriverError> {
    let request = AgentdRequest::health(request_id, identity.spawn_generation);
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES {
        return Ok(HealthProbeObservation {
            exact_identity: false,
            ready: false,
        });
    }

    let mut stream = std::os::unix::net::UnixStream::connect(&identity.control_socket)?;
    stream.set_read_timeout(Some(HEALTH_PROBE_IO_TIMEOUT))?;
    stream.set_write_timeout(Some(HEALTH_PROBE_IO_TIMEOUT))?;
    stream.write_all(&bytes)?;
    stream.shutdown(Shutdown::Write)?;

    let mut reader = BufReader::new(stream).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut response_bytes = Vec::new();
    let count = reader.read_until(b'\n', &mut response_bytes)?;
    if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !response_bytes.ends_with(b"\n") {
        return Ok(HealthProbeObservation {
            exact_identity: false,
            ready: false,
        });
    }
    let response: AgentdResponse = serde_json::from_slice(&response_bytes)?;
    let exact_envelope = response.schema_version == AGENTD_CONTROL_SCHEMA_VERSION
        && response.request_id == request_id
        && response.agent_id == identity.agent_id
        && response.spawn_generation == identity.spawn_generation;
    let AgentdPayload::Health(health) = response.payload else {
        return Ok(HealthProbeObservation {
            exact_identity: false,
            ready: false,
        });
    };
    let generation_matches = match health.lifecycle {
        AgentLifecycle::Starting => response.current_generation == identity.spawn_generation,
        AgentLifecycle::Running => identity
            .spawn_generation
            .checked_add(1)
            .is_some_and(|generation| response.current_generation == generation),
        AgentLifecycle::Draining => identity
            .spawn_generation
            .checked_add(2)
            .is_some_and(|generation| response.current_generation == generation),
        AgentLifecycle::Stopped | AgentLifecycle::Failed => false,
    };
    let readiness_matches = match health.lifecycle {
        AgentLifecycle::Starting => health.promotion_ready && !health.ready,
        AgentLifecycle::Running => health.promotion_ready && health.ready,
        AgentLifecycle::Draining | AgentLifecycle::Stopped | AgentLifecycle::Failed => false,
    };
    let exact_identity = exact_envelope
        && generation_matches
        && !health.fenced
        && health.process_id == identity.process_id
        && health.workspace == identity.workspace
        && health.home_root == identity.home_root
        && health.run_root == identity.run_root;
    Ok(HealthProbeObservation {
        exact_identity,
        ready: exact_identity && readiness_matches,
    })
}

fn query_matrix_health_once(
    identity: &MatrixHealthProbeIdentity,
    request_id: u64,
) -> Result<HealthProbeObservation, ProcessDriverError> {
    let request = MatrixdRequest {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id,
        agent_id: identity.agent_id.clone(),
        fence: None,
        method: MatrixdMethod::Health,
    };
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_MATRIXD_CONTROL_FRAME_BYTES {
        return Ok(HealthProbeObservation {
            exact_identity: false,
            ready: false,
        });
    }

    let mut stream = std::os::unix::net::UnixStream::connect(&identity.control_socket)?;
    stream.set_read_timeout(Some(HEALTH_PROBE_IO_TIMEOUT))?;
    stream.set_write_timeout(Some(HEALTH_PROBE_IO_TIMEOUT))?;
    stream.write_all(&bytes)?;
    stream.shutdown(Shutdown::Write)?;

    let mut reader = BufReader::new(stream).take(MAX_MATRIXD_CONTROL_FRAME_BYTES + 1);
    let mut response_bytes = Vec::new();
    let count = reader.read_until(b'\n', &mut response_bytes)?;
    if count == 0
        || count as u64 > MAX_MATRIXD_CONTROL_FRAME_BYTES
        || !response_bytes.ends_with(b"\n")
    {
        return Ok(HealthProbeObservation {
            exact_identity: false,
            ready: false,
        });
    }
    let response: MatrixdResponse = serde_json::from_slice(&response_bytes)?;
    if response.validate().is_err() {
        return Ok(HealthProbeObservation {
            exact_identity: false,
            ready: false,
        });
    }
    let exact_envelope = response.schema_version == MATRIXD_CONTROL_SCHEMA_VERSION
        && response.request_id == request_id
        && response.agent_id == identity.agent_id
        && response.release_id == identity.release_id
        && response.binding_revision == identity.binding_revision
        && response.binding_digest == identity.binding_digest
        && response.attached_agent_generation == identity.agent_generation
        && response.process_incarnation == identity.process_incarnation
        && response.plane_epoch == identity.plane_epoch;
    let MatrixdPayload::Health(MatrixdHealth {
        lifecycle,
        process_id,
        agentd_connected,
        matrix_sync_connected,
        fenced,
    }) = response.payload
    else {
        return Ok(HealthProbeObservation {
            exact_identity: false,
            ready: false,
        });
    };
    let exact_identity = exact_envelope && process_id == identity.process_id && !fenced;
    let ready = exact_identity
        && lifecycle == MatrixdLifecycle::Ready
        && agentd_connected
        && matrix_sync_connected;
    Ok(HealthProbeObservation {
        exact_identity,
        ready,
    })
}

fn spawn_log_reader(
    mut reader: impl Read + Send + 'static,
    stream: ProcessStream,
    sender: SyncSender<ProcessLog>,
) {
    std::thread::spawn(move || {
        let mut buffer = [0_u8; LOG_CHUNK_BYTES];
        loop {
            let count = match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(count) => count,
            };
            let _ = sender.try_send(ProcessLog {
                stream,
                bytes: buffer[..count].to_vec(),
            });
        }
    });
}

fn send_signal(pid: u32, signal: i32) -> Result<(), ProcessDriverError> {
    let pid = i32::try_from(pid)
        .map_err(|_| ProcessDriverError::new("child PID does not fit Unix pid_t"))?;
    // SAFETY: `pid` comes from std::process::Child and `signal` is a fixed libc signal constant.
    if unsafe { libc::kill(pid, signal) } == -1 {
        Err(std::io::Error::last_os_error().into())
    } else {
        Ok(())
    }
}

fn process_exists(system_id: u64) -> Result<bool, ProcessDriverError> {
    let pid = i32::try_from(system_id)
        .map_err(|_| ProcessDriverError::new("stored child PID does not fit Unix pid_t"))?;
    // SAFETY: signal 0 performs an existence/permission check without delivering a signal.
    if unsafe { libc::kill(pid, 0) } == 0 {
        return Ok(true);
    }
    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        Ok(false)
    } else if error.raw_os_error() == Some(libc::EPERM) {
        Ok(true)
    } else {
        Err(error.into())
    }
}

/// Poll an adopted process without confusing a terminated child zombie for a
/// live process. After supervisor recovery the process normally is not our
/// child, in which case `waitpid` returns `ECHILD` and the exact UDS adoption
/// proof remains the sole source of signal authority; here we only observe its
/// continued existence with signal 0.
fn poll_adopted_process(process_id: u32) -> Result<Option<ProcessExit>, ProcessDriverError> {
    let pid = i32::try_from(process_id)
        .map_err(|_| ProcessDriverError::new("adopted child PID does not fit Unix pid_t"))?;
    let mut status = 0_i32;
    // SAFETY: `pid` is the exact process identity proven during adoption,
    // `status` points to writable storage, and WNOHANG never blocks.
    let waited = unsafe { libc::waitpid(pid, &mut status, libc::WNOHANG) };
    if waited > 0 {
        let exited = libc::WIFEXITED(status);
        return Ok(Some(ProcessExit {
            success: exited && libc::WEXITSTATUS(status) == 0,
            code: exited.then(|| libc::WEXITSTATUS(status)),
        }));
    }
    if waited == 0 {
        return Ok(None);
    }

    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ECHILD) {
        return process_exists(u64::from(process_id)).map(|exists| {
            (!exists).then_some(ProcessExit {
                success: false,
                code: None,
            })
        });
    }
    Err(error.into())
}

#[cfg(test)]
#[path = "unix_tests.rs"]
mod tests;
