use std::io;
use std::process::Output;
use std::process::Stdio;
use std::time::Duration;

use codex_protocol::shell_environment::scrub_non_inheritable_env_vars;
#[cfg(windows)]
use codex_utils_pty::JobObject;
#[cfg(unix)]
use codex_utils_pty::process_group::kill_process_group;
use tokio::process::Child;
use tokio::process::Command;
use tokio::time::timeout;

struct KillGitProcessTreeOnDrop {
    #[cfg(unix)]
    process_id: u32,
    #[cfg(windows)]
    job: Option<JobObject>,
    #[cfg(unix)]
    armed: bool,
}

#[cfg(unix)]
impl Drop for KillGitProcessTreeOnDrop {
    fn drop(&mut self) {
        if self.armed {
            let _ = kill_process_group(self.process_id);
        }
    }
}

fn spawn_git_command(command: &mut Command) -> io::Result<(Child, KillGitProcessTreeOnDrop)> {
    scrub_non_inheritable_env_vars(command.as_std_mut());
    #[cfg(unix)]
    command.process_group(0);
    command.kill_on_drop(true);

    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    let (child, job) = match JobObject::create()
        .and_then(|job| job.spawn_contained(command).map(|child| (child, job)))
    {
        Ok((child, job)) => (child, Some(job)),
        Err(_) => {
            // A failed contained spawn leaves CREATE_SUSPENDED on the command.
            command.creation_flags(0);
            (command.spawn()?, None)
        }
    };
    #[cfg(not(windows))]
    let child = command.spawn()?;

    let process_tree = KillGitProcessTreeOnDrop {
        #[cfg(unix)]
        process_id: child
            .id()
            .ok_or_else(|| io::Error::other("Git child has no process ID"))?,
        #[cfg(windows)]
        job,
        #[cfg(unix)]
        armed: true,
    };

    Ok((child, process_tree))
}

async fn wait_for_git_command_with_timeout_output(
    child: Child,
    process_tree: KillGitProcessTreeOnDrop,
    timeout_duration: Duration,
) -> io::Result<Output> {
    #[cfg(unix)]
    let mut process_tree = process_tree;

    // wait_with_output drains both pipes concurrently. The deadline also covers
    // descendants that keep those pipes open after the Git wrapper has exited.
    let output = timeout(timeout_duration, child.wait_with_output())
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "Git process tree timed out"))??;

    #[cfg(windows)]
    if let Some(job) = &process_tree.job {
        job.preserve_descendants()?;
    }
    #[cfg(unix)]
    {
        process_tree.armed = false;
    }
    Ok(output)
}

/// Run Git with concurrent output draining and a deadline for the whole process
/// tree. Cancellation, timeout, or an I/O failure drops the original process-tree
/// guard; spawn and timeout errors remain distinguishable.
pub async fn run_git_command_with_timeout_output_checked(
    command: &mut Command,
    timeout_duration: Duration,
) -> io::Result<Output> {
    let (child, process_tree) = spawn_git_command(command)?;
    wait_for_git_command_with_timeout_output(child, process_tree, timeout_duration).await
}

pub(crate) async fn run_git_command_with_timeout_output(
    command: &mut Command,
    timeout_duration: Duration,
) -> Option<Output> {
    run_git_command_with_timeout_output_checked(command, timeout_duration)
        .await
        .ok()
}

#[cfg(test)]
#[path = "git_process_tests.rs"]
mod tests;
