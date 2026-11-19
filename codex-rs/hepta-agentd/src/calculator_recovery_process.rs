//! Explicit old-incarnation recovery in the trusted Calculator host. This starts
//! only the hash-bound companion helper and gives it one private recovery
//! datagram. No effect descriptor, issuer, new operation or directory scan.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixDatagram;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CalculatorRecoveryChannel;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_types::StableId;

use crate::AgentdCalculatorRecoveryChannel;
use crate::AgentdError;
use crate::AgentdProductionWriterHost;

const READY: &[u8] = b"TRILL_CALCULATOR_RECOVERY_READY_V1\n";
const MAX_HELPER_BYTES: u64 = 128 * 1024 * 1024;

/// Values supplied by the trusted startup manifest/original retained source,
/// never an Objective text or ordinary control message. The helper runs under
/// the same account as the original application data owner.
#[derive(Clone, Debug)]
pub struct AgentdCalculatorPreviousRecoveryLaunch {
    pub helper: PathBuf,
    pub helper_sha256: Sha256Digest,
    pub state_directory: PathBuf,
    pub previous_target: CalculatorTargetIdentity,
    pub operation_id: String,
}

struct RunningHelper {
    child: Child,
    channel: AgentdCalculatorRecoveryChannel,
}

impl Drop for RunningHelper {
    fn drop(&mut self) {
        if matches!(self.child.try_wait(), Ok(None)) {
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
    }
}

#[derive(Default)]
struct ProcessState {
    running: Option<RunningHelper>,
    starts: u64,
}

pub(crate) struct ProcessRecoveryChannel {
    launch: AgentdCalculatorPreviousRecoveryLaunch,
    // Execute sealed verified ELF bytes through /proc/self/fd. Neither path
    // replacement nor an in-place write can change a later helper restart.
    executable: File,
    state: Mutex<ProcessState>,
}

impl ProcessRecoveryChannel {
    pub(crate) fn prepare(launch: AgentdCalculatorPreviousRecoveryLaunch) -> io::Result<Self> {
        launch
            .previous_target
            .validate()
            .map_err(io::Error::other)?;
        StableId::new(&launch.operation_id).map_err(io::Error::other)?;
        if !launch.helper.is_absolute() || !launch.state_directory.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "absolute Calculator recovery paths required",
            ));
        }
        let mut executable = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
            .open(&launch.helper)?;
        let metadata = executable.metadata()?;
        // SAFETY: geteuid has no memory arguments or side effects.
        let uid = unsafe { libc::geteuid() };
        if !metadata.is_file()
            || (metadata.uid() != uid && metadata.uid() != 0)
            || metadata.mode() & 0o022 != 0
            || metadata.mode() & 0o111 == 0
            || metadata.len() > MAX_HELPER_BYTES
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "Calculator recovery executable custody",
            ));
        }
        let mut bytes = Vec::new();
        Read::by_ref(&mut executable)
            .take(MAX_HELPER_BYTES + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_HELPER_BYTES
            || !bytes.starts_with(b"\x7fELF")
            || Sha256Digest::for_bytes(&bytes) != launch.helper_sha256
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "Calculator recovery executable identity mismatch",
            ));
        }
        // SAFETY: the constant C string is NUL terminated, flags are valid.
        let fd = unsafe {
            libc::memfd_create(
                c"trill-calculator-recovery".as_ptr(),
                libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING,
            )
        };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: memfd_create returned a new descriptor owned by this scope.
        let mut executable = unsafe { File::from_raw_fd(fd) };
        executable.write_all(&bytes)?;
        // SAFETY: fd remains owned by executable. The bytes are immutable
        // before any child receives access to the executable.
        if unsafe { libc::fchmod(fd, 0o500) } != 0
            || unsafe {
                libc::fcntl(
                    fd,
                    libc::F_ADD_SEALS,
                    libc::F_SEAL_WRITE
                        | libc::F_SEAL_GROW
                        | libc::F_SEAL_SHRINK
                        | libc::F_SEAL_SEAL,
                )
            } != 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(Self {
            launch,
            executable,
            state: Mutex::new(ProcessState::default()),
        })
    }

    fn ensure_started(&self, state: &mut ProcessState) -> io::Result<()> {
        if let Some(running) = &mut state.running {
            if running.child.try_wait()?.is_none() {
                return Ok(());
            }
            // Reap is observed before replacing an old process. Restart uses
            // the same verified inode, target and operation, never new effects.
            drop(state.running.take());
        }
        let (parent, child) = UnixDatagram::pair()?;
        let channel = AgentdCalculatorRecoveryChannel::from_private_channel(parent)?;
        let target = &self.launch.previous_target;
        let mut command = Command::new(format!("/proc/self/fd/{}", self.executable.as_raw_fd()));
        command
            .args(["--state-dir"])
            .arg(&self.launch.state_directory)
            .args([
                "--calculator-session",
                &target.session_instance,
                "--task-id",
                &target.task_id.to_string(),
                "--calculator-incarnation",
                &target.incarnation,
            ])
            .env_clear()
            .stdin(Stdio::from(OwnedFd::from(child)))
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        // SAFETY: getpid only reads the current process identity.
        let parent_pid = unsafe { libc::getpid() };
        // SAFETY: the post-fork closure performs only async-signal-safe Linux
        // syscalls. Exec retains stdin's recovery pair and stdout/stderr only.
        // CLOEXEC preserves the sealed ELF until exec resolves /proc/self/fd.
        unsafe {
            command.pre_exec(move || {
                if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL) != 0 {
                    return Err(io::Error::last_os_error());
                }
                if libc::getppid() != parent_pid {
                    return Err(io::Error::from_raw_os_error(libc::ESRCH));
                }
                if libc::syscall(
                    libc::SYS_close_range,
                    3_u32,
                    u32::MAX,
                    libc::CLOSE_RANGE_CLOEXEC,
                ) != 0
                {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let process = command.spawn()?;
        let mut running = RunningHelper {
            child: process,
            channel,
        };
        let ready = running
            .child
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("missing helper ready pipe"))?;
        wait_ready(ready, &mut running.child)?;
        state.running = Some(running);
        state.starts = state.starts.saturating_add(1);
        Ok(())
    }

    pub(crate) fn start(&self) -> io::Result<()> {
        let mut state = self
            .state
            .try_lock()
            .map_err(|_| io::Error::other("Calculator helper busy or poisoned"))?;
        self.ensure_started(&mut state)
    }
}

impl CalculatorRecoveryChannel for ProcessRecoveryChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        if request.is_empty() || request.len() > codex_hepta_memory::CALCULATOR_REQUEST_MAX_BYTES {
            return Err("Calculator process recovery frame bound".into());
        }
        let value: serde_json::Value =
            serde_json::from_slice(request).map_err(|error| error.to_string())?;
        if value["schema_version"] != 1
            || !matches!(value["action"].as_str(), Some("observe" | "acknowledge"))
            || value["target"]
                != serde_json::to_value(&self.launch.previous_target)
                    .map_err(|error| error.to_string())?
            || value["operation_id"].as_str() != Some(self.launch.operation_id.as_str())
        {
            return Err(
                "Calculator helper can only observe/retire the explicit old operation".into(),
            );
        }
        let mut state = self
            .state
            .try_lock()
            .map_err(|_| "Calculator recovery process busy or poisoned")?;
        self.ensure_started(&mut state)
            .map_err(|error| error.to_string())?;
        state
            .running
            .as_ref()
            .ok_or("Calculator recovery helper unavailable")?
            .channel
            .exchange(request)
    }
}

fn wait_ready(mut pipe: std::process::ChildStdout, child: &mut Child) -> io::Result<()> {
    let fd = pipe.as_raw_fd();
    // SAFETY: fd belongs to the retained ChildStdout. These operations only
    // set nonblocking behavior on that pipe and wait on its readiness.
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        return Err(io::Error::last_os_error());
    }
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut bytes = vec![0_u8; READY.len()];
    let mut filled = 0;
    while filled < bytes.len() {
        if child.try_wait()?.is_some() {
            return Err(io::Error::other(
                "Calculator recovery helper exited before opening the old incarnation",
            ));
        }
        match pipe.read(&mut bytes[filled..]) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "Calculator helper readiness EOF",
                ));
            }
            Ok(count) => {
                filled += count;
                continue;
            }
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                ) => {}
            Err(error) => return Err(error),
        }
        let left = deadline
            .checked_duration_since(Instant::now())
            .filter(|left| !left.is_zero())
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::TimedOut,
                    "Calculator helper readiness deadline",
                )
            })?;
        let mut poll = libc::pollfd {
            fd,
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: one initialized pollfd remains live for this bounded poll.
        let result = unsafe { libc::poll(&mut poll, 1, left.as_millis().min(2000) as i32 + 1) };
        if result < 0 {
            let error = io::Error::last_os_error();
            if error.kind() != io::ErrorKind::Interrupted {
                return Err(error);
            }
        }
    }
    if bytes != READY {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Calculator helper readiness marker mismatch",
        ));
    }
    Ok(())
}

impl AgentdProductionWriterHost {
    /// Compose an actual independently running companion process after the
    /// original retained-source checks, before Calculator Organ readiness. The old
    /// target is never registered as a dispatcher and receives no issuer.
    pub async fn attach_previous_calculator_recovery_process(
        self,
        current: &CalculatorTargetIdentity,
        launch: AgentdCalculatorPreviousRecoveryLaunch,
    ) -> Result<Self, AgentdError> {
        let previous = launch.previous_target.clone();
        let operation_id = launch.operation_id.clone();
        let channel = Arc::new(ProcessRecoveryChannel::prepare(launch)?);
        let host = self
            .attach_explicit_previous_calculator_recovery(
                current,
                previous,
                &operation_id,
                channel.clone(),
            )
            .await?;
        channel.start()?;
        host.writer().verify_current_authority().await?;
        Ok(host)
    }
}

#[cfg(test)]
#[path = "calculator_recovery_process_tests.rs"]
mod tests;
