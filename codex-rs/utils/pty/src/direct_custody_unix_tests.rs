use super::DirectCustody;
use super::DirectLaunch;
use super::DirectRegistry;
use super::DirectWait;
use super::ProcessSpawnError;
use super::TargetSpawnPhase;
use crate::ProcessCleanupCustody;
use crate::ProcessCleanupObservation;
use crate::direct_child::AsyncChild;
use crate::direct_child::BlockingChild;
use crate::direct_child::PortableChild;
use pretty_assertions::assert_eq;
use std::io;
use std::io::Read as _;
use std::os::fd::AsRawFd as _;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt as _;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

const CHILD_MODE: &str = "CODEX_DIRECT_CUSTODY_CHILD_MODE";
const CHILD_TEST: &str = "direct_custody::tests::native_child_fixture";

fn child_command() -> io::Result<Command> {
    let mut command = Command::new(std::env::current_exe()?);
    command
        .args(["--exact", CHILD_TEST, "--nocapture"])
        .env(CHILD_MODE, "exit")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    Ok(command)
}

fn reap_original_child(pid: u32, deadline: Instant) -> anyhow::Result<()> {
    // The fixture owns this unreaped child. Reap it once to induce the actual
    // ECHILD boundary in the original observer; never query this PID afterward.
    let pid = libc::pid_t::try_from(pid)?;
    let mut status = 0;
    loop {
        match unsafe { libc::waitpid(pid, &mut status, libc::WNOHANG) } {
            actual if actual == pid => {
                assert!(libc::WIFEXITED(status));
                assert_eq!(libc::WEXITSTATUS(status), 81);
                return Ok(());
            }
            0 => {}
            -1 => {
                let error = io::Error::last_os_error();
                if error.kind() != io::ErrorKind::Interrupted {
                    return Err(error.into());
                }
            }
            _ => anyhow::bail!("waitpid returned a different fixture identity"),
        }
        if Instant::now() >= deadline {
            anyhow::bail!("original fixture child did not exit before its deadline");
        }
        std::thread::sleep(Duration::from_millis(1));
    }
}

struct Observation {
    waiter: DirectWait,
    receiver: tokio::sync::oneshot::Receiver<i32>,
    custody: Arc<DirectCustody>,
    exited: Arc<AtomicBool>,
    code: Arc<Mutex<Option<i32>>>,
}

impl Observation {
    fn new(launch: DirectLaunch) -> Self {
        let custody = launch.custody();
        let (sender, receiver) = tokio::sync::oneshot::channel();
        let exited = Arc::new(AtomicBool::new(false));
        let code = Arc::new(Mutex::new(None));
        let waiter = DirectWait::new(launch, Arc::clone(&exited), Arc::clone(&code), sender);
        Self {
            waiter,
            receiver,
            custody,
            exited,
            code,
        }
    }

    async fn assert_lost(
        self,
        error: io::Error,
        registry: &Arc<DirectRegistry>,
        deadline: Instant,
    ) -> anyhow::Result<()> {
        assert_eq!(error.raw_os_error(), Some(libc::ECHILD));
        self.waiter.finish(Err(error));
        assert!(
            tokio::time::timeout_at(deadline.into(), self.receiver)
                .await?
                .is_err()
        );
        assert!(!self.exited.load(Ordering::SeqCst));
        assert_eq!(
            *self
                .code
                .lock()
                .map_err(|_| io::Error::other("test exit lock poisoned"))?,
            None
        );
        assert_eq!(
            self.custody.observe_cleanup()?,
            ProcessCleanupObservation::NoTerminalObservation
        );
        assert!(registry.reserve().is_err());
        Ok(())
    }
}

#[tokio::test]
async fn pipe_wait_error_does_not_publish_a_synthetic_exit() -> anyhow::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(5);
    let registry = Arc::new(DirectRegistry::default());
    let mut launch = registry.reserve()?;
    launch.begin_attempt();
    let child = tokio::process::Command::from(child_command()?).spawn()?;
    let pid = child
        .id()
        .ok_or_else(|| io::Error::other("fixture child id missing"))?;
    let owner = Arc::new(AsyncChild::new(child));
    launch.attach_owner(owner.clone())?;
    let observation = Observation::new(launch);
    reap_original_child(pid, deadline)?;
    let error = tokio::time::timeout_at(deadline.into(), owner.wait())
        .await?
        .expect_err("original Tokio waiter must report the lost child observation");
    observation.assert_lost(error, &registry, deadline).await
}

#[tokio::test]
async fn portable_wait_error_does_not_publish_a_synthetic_exit() -> anyhow::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(5);
    let registry = Arc::new(DirectRegistry::default());
    let mut launch = registry.reserve()?;
    launch.begin_attempt();
    let child = child_command()?.spawn()?;
    let pid = child.id();
    let owner = Arc::new(PortableChild::new(Box::new(child)));
    launch.attach_owner(owner.clone())?;
    let observation = Observation::new(launch);
    reap_original_child(pid, deadline)?;
    let error = owner
        .wait()
        .expect_err("original portable waiter must report the lost observation");
    observation.assert_lost(error, &registry, deadline).await
}

#[tokio::test]
async fn inherited_fd_wait_error_does_not_publish_a_synthetic_exit() -> anyhow::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(5);
    let registry = Arc::new(DirectRegistry::default());
    let mut launch = registry.reserve()?;
    launch.begin_attempt();
    let child = child_command()?.spawn()?;
    let pid = child.id();
    let owner = Arc::new(BlockingChild::new(child));
    launch.attach_owner(owner.clone())?;
    let observation = Observation::new(launch);
    reap_original_child(pid, deadline)?;
    let error = owner
        .wait()
        .expect_err("original blocking waiter must report the lost observation");
    observation.assert_lost(error, &registry, deadline).await
}

#[tokio::test]
async fn forced_fork_exec_error_is_closed_without_bypassing_the_attempt() -> anyhow::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(5);
    let (mut marker, child_marker) = UnixStream::pair()?;
    marker.set_read_timeout(Some(deadline.saturating_duration_since(Instant::now())))?;
    let marker_fd = child_marker.as_raw_fd();
    let mut command = child_command()?;
    // This is the same forced-fork std boundary as the inherited-fd backend.
    // Only async-signal-safe write and an errno result run in the child.
    unsafe {
        command.pre_exec(move || {
            if libc::write(marker_fd, b"F".as_ptr().cast(), 1) != 1 {
                return Err(io::Error::last_os_error());
            }
            Err(io::Error::from_raw_os_error(libc::EACCES))
        });
    }
    let registry = Arc::new(DirectRegistry::default());
    let mut launch = registry.reserve()?;
    launch.begin_attempt();
    let error = command
        .spawn()
        .expect_err("real pre_exec rejection must return an error");
    assert_eq!(error.raw_os_error(), Some(libc::EACCES));
    let error = launch.reaped_std_spawn_error(error);
    let typed = error
        .downcast_ref::<ProcessSpawnError>()
        .ok_or_else(|| io::Error::other("typed spawn error missing"))?;
    assert_eq!(typed.phase(), TargetSpawnPhase::LaunchFailedClosed);
    assert!(typed.cleanup_custody().is_none());
    let mut actual = [0u8; 1];
    marker.read_exact(&mut actual)?;
    assert_eq!(actual, *b"F");
    // The same registry can admit a real later child after this proven closed
    // launch. This is not a reset of an unknown reservation or a new registry.
    let mut subsequent = registry.reserve()?;
    subsequent.begin_attempt();
    let child = child_command()?.spawn()?;
    let owner = Arc::new(BlockingChild::new(child));
    subsequent.attach_owner(owner.clone())?;
    let observed = Observation::new(subsequent);
    let worker = tokio::task::spawn_blocking(move || {
        observed
            .waiter
            .finish(owner.wait().map(super::ObservedExit::from_status));
    });
    assert_eq!(
        tokio::time::timeout_at(deadline.into(), observed.receiver).await??,
        81
    );
    tokio::time::timeout_at(deadline.into(), worker).await??;
    assert!(observed.exited.load(Ordering::SeqCst));
    assert_eq!(
        *observed
            .code
            .lock()
            .map_err(|_| io::Error::other("test exit lock poisoned"))?,
        Some(81)
    );
    assert_eq!(
        observed.custody.observe_cleanup()?,
        ProcessCleanupObservation::OwnerTerminated {
            owner_exit_code: Some(81)
        },
    );
    assert!(registry.reserve().is_ok());
    Ok(())
}

#[test]
fn native_child_fixture() {
    if std::env::var(CHILD_MODE).as_deref() == Ok("exit") {
        std::process::exit(81);
    }
}
