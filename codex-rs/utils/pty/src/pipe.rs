use std::collections::HashMap;
use std::io;
use std::io::ErrorKind;
use std::path::Path;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use std::sync::atomic::AtomicBool;

use anyhow::Result;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::process::Command;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;

use crate::direct_child::AsyncChild;
use crate::direct_custody;
use crate::direct_custody::DirectWait;
use crate::direct_custody::ObservedExit;
use crate::direct_custody::before_launch;
use crate::process::ChildTerminator;
use crate::process::ProcessHandle;
use crate::process::ProcessSignal;
use crate::process::SpawnedProcess;

#[cfg(target_os = "linux")]
use libc;

#[cfg(windows)]
enum WindowsChildTerminator {
    Job(Arc<crate::win::JobObject>),
    Process(Arc<std::os::windows::io::OwnedHandle>),
}

struct PipeChildTerminator {
    #[cfg(windows)]
    windows: WindowsChildTerminator,
    #[cfg(unix)]
    process_group_id: u32,
}

impl ChildTerminator for PipeChildTerminator {
    fn signal(&mut self, signal: ProcessSignal) -> io::Result<()> {
        match signal {
            ProcessSignal::Interrupt => {
                #[cfg(unix)]
                {
                    crate::process_group::interrupt_process_group(self.process_group_id)
                }

                #[cfg(windows)]
                {
                    self.kill()
                }

                #[cfg(not(any(unix, windows)))]
                {
                    Err(crate::process::unsupported_signal(signal))
                }
            }
        }
    }

    fn kill(&mut self) -> io::Result<()> {
        #[cfg(all(unix, not(target_os = "macos")))]
        {
            crate::process_group::kill_process_group(self.process_group_id)
        }

        #[cfg(target_os = "macos")]
        {
            crate::process_group::kill_process_group_with_member_fallback(self.process_group_id)
        }

        #[cfg(windows)]
        {
            match &self.windows {
                WindowsChildTerminator::Job(job) => job.terminate(),
                WindowsChildTerminator::Process(handle) => {
                    crate::win::JobObject::terminate_process_handle(handle)
                }
            }
        }

        #[cfg(not(any(unix, windows)))]
        {
            Ok(())
        }
    }
}

async fn read_output_stream<R>(mut reader: R, output_tx: mpsc::Sender<Vec<u8>>)
where
    R: AsyncRead + Unpin,
{
    let mut buf = vec![0u8; 8_192];
    loop {
        match reader.read(&mut buf).await {
            Ok(0) => break,
            Ok(n) => {
                let _ = output_tx.send(buf[..n].to_vec()).await;
            }
            Err(ref e) if e.kind() == ErrorKind::Interrupted => continue,
            Err(_) => break,
        }
    }
}

#[derive(Clone, Copy)]
enum PipeStdinMode {
    Piped,
    Null,
}

/// On Windows, process-tree containment is best-effort because Tokio returns
/// only after the root process starts, so job assignment cannot be atomic.
async fn spawn_process_with_stdin_mode(
    program: &str,
    args: &[String],
    cwd: &Path,
    env: &HashMap<String, String>,
    arg0: &Option<String>,
    stdin_mode: PipeStdinMode,
    inherited_fds: &[i32],
) -> Result<SpawnedProcess> {
    if program.is_empty() {
        return Err(before_launch(anyhow::anyhow!(
            "missing program for pipe spawn"
        )));
    }

    #[cfg(not(unix))]
    let _ = inherited_fds;

    let mut command = Command::new(program);
    #[cfg(unix)]
    if let Some(arg0) = arg0 {
        command.arg0(arg0);
    }
    #[cfg(target_os = "linux")]
    let parent_pid = unsafe { libc::getpid() };
    #[cfg(unix)]
    let inherited_fds = inherited_fds.to_vec();
    #[cfg(unix)]
    unsafe {
        command.pre_exec(move || {
            crate::process_group::detach_from_tty()?;
            #[cfg(target_os = "linux")]
            crate::process_group::set_parent_death_signal(parent_pid)?;
            crate::pty::close_inherited_fds_except(&inherited_fds);
            Ok(())
        });
    }
    #[cfg(not(unix))]
    let _ = arg0;
    command.current_dir(cwd);
    command.env_clear();
    for (key, value) in env {
        command.env(key, value);
    }
    for arg in args {
        command.arg(arg);
    }
    match stdin_mode {
        PipeStdinMode::Piped => {
            command.stdin(Stdio::piped());
        }
        PipeStdinMode::Null => {
            command.stdin(Stdio::null());
        }
    }
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());

    #[cfg(windows)]
    let job = crate::win::JobObject::create().map(Arc::new);
    let mut launch = direct_custody::reserve().map_err(before_launch)?;
    launch.begin_attempt();
    let child = command.spawn().map_err(|error| launch.spawn_error(error))?;
    let owner = Arc::new(AsyncChild::new(child));
    launch
        .attach_owner(owner.clone())
        .map_err(|error| launch.spawn_error(error))?;
    let custody = launch.custody();
    let mut child = owner.child.try_lock().map_err(|_| {
        launch.spawn_error(io::Error::other(
            "original direct child is unexpectedly busy",
        ))
    })?;
    #[cfg(windows)]
    let windows_terminator = {
        use std::os::windows::io::BorrowedHandle;
        // Accept the small race: a descendant created between spawn and
        // assignment is not guaranteed to join the job and can escape termination.
        let pid = child
            .id()
            .ok_or_else(|| launch.spawn_error(io::Error::other("missing child pid")))?;
        let process_handle = child
            .raw_handle()
            .ok_or_else(|| launch.spawn_error(io::Error::other("missing child process handle")))?;
        // Hold the original Child while duplicating its actual kernel handle.
        // The fallback never reopens a PID after an observation failure.
        let retained = owner
            .retain_original_handle(unsafe { BorrowedHandle::borrow_raw(process_handle) })
            .map_err(|error| launch.spawn_error(error))?;
        let assigned_job = job.and_then(|job| {
            job.assign_process(process_handle)?;
            Ok(job)
        });
        match assigned_job {
            Ok(job) => WindowsChildTerminator::Job(job),
            Err(err) => {
                log::warn!(
                    "Windows pipe process tree containment unavailable for pid {pid}: {err}"
                );
                WindowsChildTerminator::Process(retained)
            }
        }
    };
    #[cfg(unix)]
    let process_group_id = child
        .id()
        .ok_or_else(|| launch.spawn_error(io::Error::other("missing child pid")))?;

    let stdin = child.stdin.take();
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    drop(child);

    let (writer_tx, mut writer_rx) = mpsc::channel::<Vec<u8>>(128);
    let (stdout_tx, stdout_rx) = mpsc::channel::<Vec<u8>>(128);
    let (stderr_tx, stderr_rx) = mpsc::channel::<Vec<u8>>(128);
    let writer_handle = if let Some(stdin) = stdin {
        tokio::spawn(async move {
            let mut writer = stdin;
            while let Some(bytes) = writer_rx.recv().await {
                let _ = writer.write_all(&bytes).await;
                let _ = writer.flush().await;
            }
        })
    } else {
        drop(writer_rx);
        tokio::spawn(async {})
    };

    let stdout_handle = stdout.map(|stdout| {
        let stdout_tx = stdout_tx.clone();
        tokio::spawn(async move {
            read_output_stream(BufReader::new(stdout), stdout_tx).await;
        })
    });
    let stderr_handle = stderr.map(|stderr| {
        let stderr_tx = stderr_tx.clone();
        tokio::spawn(async move {
            read_output_stream(BufReader::new(stderr), stderr_tx).await;
        })
    });
    let mut reader_abort_handles = Vec::new();
    if let Some(handle) = stdout_handle.as_ref() {
        reader_abort_handles.push(handle.abort_handle());
    }
    if let Some(handle) = stderr_handle.as_ref() {
        reader_abort_handles.push(handle.abort_handle());
    }
    let reader_handle = tokio::spawn(async move {
        if let Some(handle) = stdout_handle {
            let _ = handle.await;
        }
        if let Some(handle) = stderr_handle {
            let _ = handle.await;
        }
    });

    let (exit_tx, exit_rx) = oneshot::channel::<i32>();
    let exit_status = Arc::new(AtomicBool::new(false));
    let wait_exit_status = Arc::clone(&exit_status);
    let exit_code = Arc::new(StdMutex::new(None));
    let wait_exit_code = Arc::clone(&exit_code);
    #[cfg(windows)]
    let wait_job = match &windows_terminator {
        WindowsChildTerminator::Job(job) => Some(Arc::clone(job)),
        WindowsChildTerminator::Process(_) => None,
    };
    let observation = DirectWait::new(launch, wait_exit_status, wait_exit_code, exit_tx);
    let wait_handle: JoinHandle<()> = tokio::spawn(async move {
        let result = match owner.wait().await {
            Ok(status) => {
                #[cfg(windows)]
                if let Some(job) = wait_job
                    && let Err(err) = job.preserve_descendants()
                {
                    log::warn!(
                        "Windows pipe failed to preserve descendants after root exit: {err}"
                    );
                }
                Ok(ObservedExit::from_status(status))
            }
            Err(error) => Err(error),
        };
        observation.finish(result);
    });

    let handle = ProcessHandle::new(
        writer_tx,
        custody.guard_terminator(Box::new(PipeChildTerminator {
            #[cfg(windows)]
            windows: windows_terminator,
            #[cfg(unix)]
            process_group_id,
        })),
        reader_handle,
        reader_abort_handles,
        writer_handle,
        wait_handle,
        exit_status,
        exit_code,
        /*pty_handles*/ None,
        /*resizer*/ None,
    );
    handle
        .retain_cleanup_custody(custody.clone())
        .map_err(|error| custody.spawn_error(error))?;

    Ok(SpawnedProcess {
        session: handle,
        stdout_rx,
        stderr_rx,
        exit_rx,
    })
}

/// Spawn a process using regular pipes and preserve selected inherited file
/// descriptors across exec on Unix.
pub async fn spawn_process(
    program: &str,
    args: &[String],
    cwd: &Path,
    env: &HashMap<String, String>,
    arg0: &Option<String>,
    inherited_fds: &[i32],
) -> Result<SpawnedProcess> {
    spawn_process_with_stdin_mode(
        program,
        args,
        cwd,
        env,
        arg0,
        PipeStdinMode::Piped,
        inherited_fds,
    )
    .await
}

/// Spawn a process using regular pipes, close stdin immediately, and preserve
/// selected inherited file descriptors across exec on Unix.
pub async fn spawn_process_no_stdin(
    program: &str,
    args: &[String],
    cwd: &Path,
    env: &HashMap<String, String>,
    arg0: &Option<String>,
    inherited_fds: &[i32],
) -> Result<SpawnedProcess> {
    spawn_process_with_stdin_mode(
        program,
        args,
        cwd,
        env,
        arg0,
        PipeStdinMode::Null,
        inherited_fds,
    )
    .await
}

#[cfg(all(test, windows))]
#[path = "pipe_tests.rs"]
mod tests;
