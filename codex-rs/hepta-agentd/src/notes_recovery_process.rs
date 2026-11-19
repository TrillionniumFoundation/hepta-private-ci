//! Explicit old-incarnation recovery in the trusted Notes host. This starts
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
use codex_hepta_memory::NotesRecoveryChannel;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdNotesRecoveryChannel;
use crate::AgentdProductionWriterHost;

const READY: &[u8] = b"TRILL_NOTES_RECOVERY_READY_V1\n";
const MAX_HELPER_BYTES: u64 = 128 * 1024 * 1024;

/// Values supplied by the trusted startup manifest/original retained source,
/// never an Objective text or ordinary control message. The helper runs under
/// the same account as the original application data owner.
#[derive(Clone, Debug)]
pub struct AgentdNotesPreviousRecoveryLaunch {
    pub helper: PathBuf,
    pub helper_sha256: Sha256Digest,
    pub state_directory: PathBuf,
    pub previous_target: NotesTargetIdentity,
    pub operation_id: String,
}

struct RunningHelper {
    child: Child,
    channel: AgentdNotesRecoveryChannel,
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
    launch: AgentdNotesPreviousRecoveryLaunch,
    // Execute sealed verified ELF bytes through /proc/self/fd. Neither path
    // replacement nor an in-place write can change a later helper restart.
    executable: File,
    state: Mutex<ProcessState>,
}

impl ProcessRecoveryChannel {
    pub(crate) fn prepare(launch: AgentdNotesPreviousRecoveryLaunch) -> io::Result<Self> {
        launch
            .previous_target
            .validate()
            .map_err(io::Error::other)?;
        StableId::new(&launch.operation_id).map_err(io::Error::other)?;
        if !launch.helper.is_absolute() || !launch.state_directory.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "absolute Notes recovery paths required",
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
                "Notes recovery executable custody",
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
                "Notes recovery executable identity mismatch",
            ));
        }
        // SAFETY: the constant C string is NUL terminated, flags are valid.
        let fd = unsafe {
            libc::memfd_create(
                c"trill-notes-recovery".as_ptr(),
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
        let channel = AgentdNotesRecoveryChannel::from_private_channel(parent)?;
        let target = &self.launch.previous_target;
        let mut command = Command::new(format!("/proc/self/fd/{}", self.executable.as_raw_fd()));
        command
            .args(["--state-dir"])
            .arg(&self.launch.state_directory)
            .args([
                "--notes-session",
                &target.session_instance,
                "--task-id",
                &target.task_id.to_string(),
                "--notes-incarnation",
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
            .map_err(|_| io::Error::other("Notes helper busy or poisoned"))?;
        self.ensure_started(&mut state)
    }

    #[cfg(test)]
    pub(crate) fn kill_and_reap_for_test(&self) -> io::Result<()> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| io::Error::other("Notes helper lock"))?;
        let running = state
            .running
            .as_mut()
            .ok_or_else(|| io::Error::other("helper not started"))?;
        running.child.kill()?;
        running.child.wait()?;
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn starts_for_test(&self) -> u64 {
        self.state.lock().expect("helper state").starts
    }
}

impl NotesRecoveryChannel for ProcessRecoveryChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        if request.is_empty() || request.len() > codex_hepta_memory::NOTES_REQUEST_MAX_BYTES {
            return Err("Notes process recovery frame bound".into());
        }
        let value: serde_json::Value =
            serde_json::from_slice(request).map_err(|error| error.to_string())?;
        if value["schema_version"] != 1
            || !matches!(
                value["action"].as_str(),
                Some("observe" | "acknowledge_terminal")
            )
            || value["target"]
                != serde_json::to_value(&self.launch.previous_target)
                    .map_err(|error| error.to_string())?
            || value["operation_id"].as_str() != Some(self.launch.operation_id.as_str())
        {
            return Err("Notes helper can only observe/retire the explicit old operation".into());
        }
        let mut state = self
            .state
            .try_lock()
            .map_err(|_| "Notes recovery process busy or poisoned")?;
        self.ensure_started(&mut state)
            .map_err(|error| error.to_string())?;
        state
            .running
            .as_ref()
            .ok_or("Notes recovery helper unavailable")?
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
                "Notes recovery helper exited before opening the old incarnation",
            ));
        }
        match pipe.read(&mut bytes[filled..]) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "Notes helper readiness EOF",
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
                io::Error::new(io::ErrorKind::TimedOut, "Notes helper readiness deadline")
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
            "Notes helper readiness marker mismatch",
        ));
    }
    Ok(())
}

impl AgentdProductionWriterHost {
    /// Compose an actual independently running companion process after the
    /// original retained-source checks, before Notes Organ readiness. The old
    /// target is never registered as a dispatcher and receives no issuer.
    pub async fn attach_previous_notes_recovery_process(
        self,
        current: &NotesTargetIdentity,
        launch: AgentdNotesPreviousRecoveryLaunch,
    ) -> Result<Self, AgentdError> {
        let previous = launch.previous_target.clone();
        let operation_id = launch.operation_id.clone();
        let channel = Arc::new(ProcessRecoveryChannel::prepare(launch)?);
        let host = self
            .attach_explicit_previous_notes_recovery(
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
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn launch(directory: &std::path::Path) -> io::Result<AgentdNotesPreviousRecoveryLaunch> {
        // Actual host ELF only checks executable custody; it is never started
        // as a Notes helper and cannot supply an application receipt.
        let helper = directory.join("helper");
        let bytes = std::fs::read("/bin/true")?;
        std::fs::write(&helper, &bytes)?;
        std::fs::set_permissions(&helper, std::fs::Permissions::from_mode(0o700))?;
        Ok(AgentdNotesPreviousRecoveryLaunch {
            helper,
            helper_sha256: Sha256Digest::for_bytes(&bytes),
            state_directory: directory.to_owned(),
            previous_target: NotesTargetIdentity {
                session_instance: "1".repeat(32),
                task_id: 1,
                incarnation: "2".repeat(32),
            },
            operation_id: "source-operation".into(),
        })
    }

    #[test]
    fn notes_recovery_process_rejects_unsafe_or_mismatched_executable_before_start()
    -> io::Result<()> {
        let directory = tempfile::tempdir()?;
        let mut selected = launch(directory.path())?;
        selected.helper_sha256 = Sha256Digest::for_bytes(b"different executable");
        assert!(ProcessRecoveryChannel::prepare(selected).is_err());
        let selected = launch(directory.path())?;
        std::fs::set_permissions(&selected.helper, std::fs::Permissions::from_mode(0o777))?;
        assert!(ProcessRecoveryChannel::prepare(selected).is_err());
        let mut selected = launch(directory.path())?;
        let link = directory.path().join("linked-helper");
        std::os::unix::fs::symlink(&selected.helper, &link)?;
        selected.helper = link;
        assert!(ProcessRecoveryChannel::prepare(selected).is_err());
        Ok(())
    }

    #[test]
    fn notes_recovery_process_seals_bytes_and_refuses_effect_or_foreign_operation_without_spawn()
    -> io::Result<()> {
        let directory = tempfile::tempdir()?;
        let selected = launch(directory.path())?;
        let target = selected.previous_target.clone();
        let path = selected.helper.clone();
        let channel = ProcessRecoveryChannel::prepare(selected)?;
        std::fs::write(path, b"path changed after verification")?;
        // SAFETY: the descriptor belongs to the retained sealed executable.
        let seals = unsafe { libc::fcntl(channel.executable.as_raw_fd(), libc::F_GET_SEALS) };
        assert_eq!(seals & libc::F_SEAL_WRITE, libc::F_SEAL_WRITE);
        for (action, operation) in [
            ("replace_note", "source-operation"),
            ("observe", "foreign-operation"),
            ("read_previous_receipt", "source-operation"),
        ] {
            let request = serde_json::to_vec(
                &serde_json::json!({"schema_version":1,"action":action,"target":target,"operation_id":operation}),
            )?;
            assert!(channel.exchange(&request).is_err());
        }
        assert_eq!(channel.starts_for_test(), 0);
        Ok(())
    }
}
