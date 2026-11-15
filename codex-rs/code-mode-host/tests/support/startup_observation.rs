//! Bounded observations of the existing child after its readiness deadline failed.

use std::io;
use std::process::Stdio;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::process::Child;
use tokio::process::Command;
use tokio::time::Instant;
use tokio::time::timeout;
use tokio::time::timeout_at;

const OBSERVATION_BUDGET: Duration = Duration::from_secs(/*secs*/ 3);
const REAP_BUDGET: Duration = Duration::from_millis(/*millis*/ 100);
const METADATA_LIMIT: usize = 4096;
const STACK_LIMIT: usize = 65536;
static OBSERVED: AtomicBool = AtomicBool::new(/*v*/ false);

pub(super) async fn observe_failed_child(child: &mut Child) -> String {
    // This mutable borrow keeps the original child under its existing owner.
    // A child that exits after this check remains unreaped until we return, so
    // its PID cannot be recycled into an unrelated process during observation.
    match child.try_wait() {
        Ok(None) => {}
        Ok(Some(status)) => return format!("child already exited: {status}"),
        Err(error) => return format!("cannot inspect the owned child: {error}"),
    }
    let Some(pid) = child.id() else {
        return "owned child has no live PID".to_string();
    };
    if OBSERVED.swap(/*val*/ true, Ordering::Relaxed) {
        return "observation already attempted for this test binary".to_string();
    }

    // Never queue sampling work behind another failing test. At most one child
    // in each test binary is observed; successful starts never call this module.
    let started = Instant::now();
    let deadline = started + OBSERVATION_BUDGET;
    let pid_arg = pid.to_string();
    let metadata = run_tool(
        "/bin/ps",
        &[
            "-p",
            &pid_arg,
            "-o",
            "pid=,ppid=,state=,pcpu=,time=,etime=,rss=,vsz=",
        ],
        METADATA_LIMIT,
        deadline,
    )
    .await;
    let stack = run_tool(
        "/usr/bin/sample",
        &[&pid_arg, "1", "10", "-file", "/dev/stdout"],
        STACK_LIMIT,
        deadline,
    )
    .await;
    format!(
        "owned_pid={pid}, elapsed={:?}, readiness_result=timeout\nmetadata:\n{metadata}\nstack:\n{stack}",
        started.elapsed()
    )
}

async fn run_tool(program: &str, args: &[&str], stdout_limit: usize, deadline: Instant) -> String {
    if Instant::now() >= deadline {
        return format!("{program}: shared diagnostic budget exhausted before spawn");
    }
    let mut tool = match Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(/*kill_on_drop*/ true)
        .spawn()
    {
        Ok(tool) => tool,
        Err(error) => return format!("{program}: spawn failed: {error}"),
    };
    let Some(stdout) = tool.stdout.take() else {
        return format!("{program}: stdout was not captured");
    };
    let Some(stderr) = tool.stderr.take() else {
        return format!("{program}: stderr was not captured");
    };
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let mut output_bytes = 0_usize;
    let mut error_bytes = 0_usize;
    let result = timeout_at(deadline, async {
        tokio::try_join!(
            tool.wait(),
            read_prefix(stdout, &mut output, &mut output_bytes, stdout_limit),
            read_prefix(stderr, &mut errors, &mut error_bytes, METADATA_LIMIT),
        )
    })
    .await;
    let (status, completed) = match result {
        Ok(Ok((status, (), ()))) => (format!("exit={status}"), true),
        Ok(Err(error)) => (format!("capture failed: {error}"), false),
        Err(error) => (format!("shared diagnostic budget elapsed: {error}"), false),
    };
    let cleanup = if completed {
        String::new()
    } else {
        // Stop only the diagnostic utility. The original host remains owned
        // by HostHarness and still returns the original readiness failure.
        let killed = tool.start_kill();
        let reaped = timeout(REAP_BUDGET, tool.wait()).await;
        format!("; diagnostic_kill={killed:?}; diagnostic_reap={reaped:?}")
    };
    let rendered_output = render_prefix(&output, stdout_limit);
    let rendered_errors = render_prefix(&errors, METADATA_LIMIT);
    format!(
        "{program}: {status}{cleanup}, stdout_seen={output_bytes}, stderr_seen={error_bytes}, stdout_kept={}, stderr_kept={}, stdout_logged={}, stderr_logged={}\n{rendered_output}\n{rendered_errors}",
        output.len(),
        errors.len(),
        rendered_output.len(),
        rendered_errors.len()
    )
}

fn render_prefix(bytes: &[u8], limit: usize) -> String {
    let mut text = String::from_utf8_lossy(bytes).into_owned();
    let mut end = limit.min(text.len());
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    text.truncate(end);
    text
}

async fn read_prefix(
    mut stream: impl AsyncRead + Unpin,
    prefix: &mut Vec<u8>,
    total_bytes: &mut usize,
    limit: usize,
) -> io::Result<()> {
    let mut buffer = [0_u8; 4096];
    loop {
        let count = stream.read(&mut buffer).await?;
        if count == 0 {
            return Ok(());
        }
        *total_bytes = total_bytes.saturating_add(count);
        let keep = count.min(limit.saturating_sub(prefix.len()));
        prefix.extend_from_slice(&buffer[..keep]);
        // Drain excess bytes while the shared deadline remains active, so a
        // diagnostic utility cannot block on a full pipe after the prefix cap.
    }
}
