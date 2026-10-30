//! Run the original PowerShell case with an explicit child-local Ctrl-C state.
//!
//! The Windows ignore-Ctrl-C attribute is inherited independently of ConPTY
//! input mode. A test runner may set it before this library test starts. Only
//! an exact, isolated re-execution changes that attribute; the parent harness
//! and production process creation keep their existing behavior.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use std::ffi::OsStr;
use std::time::Duration;
use tokio::process::Command;
use winapi::shared::minwindef::BOOL;
use winapi::um::wincon::PHANDLER_ROUTINE;

const CASE: &str = "tests::windows_tests::conpty_ctrl_c_interrupts_powershell_foreground_child";
const CHILD_ENV: &str = "CODEX_PTY_CTRL_C_TEST_CHILD";
const CHILD_READY: &str = "__CODEX_PTY_CTRL_C_ORIGINAL_CHILD__";

#[link(name = "kernel32")]
unsafe extern "system" {
    #[link_name = "SetConsoleCtrlHandler"]
    fn set_console_ctrl_handler(callback: PHANDLER_ROUTINE, add: BOOL) -> BOOL;
}

pub(super) enum Invocation {
    OriginalChild,
    ParentVerified,
}

pub(super) async fn prepare() -> Result<Invocation> {
    if let Some(case) = std::env::var_os(CHILD_ENV) {
        ensure!(case.as_os_str() == OsStr::new(CASE), "unexpected isolated Ctrl-C case");
        // SAFETY: This exact child runs only this one test. A null callback and
        // FALSE change its own inherited ignore attribute, not any existing
        // process. No handler pointer is retained and the parent never calls it.
        if unsafe { set_console_ctrl_handler(/*callback*/ None, /*add*/ 0) } == 0 {
            return Err(std::io::Error::last_os_error())
                .context("restore normal Ctrl-C processing in the isolated test child");
        }
        println!("\n{CHILD_READY}");
        return Ok(Invocation::OriginalChild);
    }

    let executable = std::env::current_exe().context("locate the original PTY test executable")?;
    let mut command = Command::new(executable);
    command
        .args(["--exact", CASE, "--nocapture", "--color", "never", "--test-threads=1"])
        .env(CHILD_ENV, CASE)
        .kill_on_drop(true);
    let output = tokio::time::timeout(Duration::from_secs(90), command.output())
        .await
        .context("isolated original Ctrl-C test did not finish")?
        .context("execute the isolated original Ctrl-C test")?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    eprintln!("isolated original Ctrl-C test\nstdout:\n{stdout}\nstderr:\n{stderr}");
    ensure!(
        output.status.success(),
        "isolated original Ctrl-C test failed: {}; stdout={stdout:?}; stderr={stderr:?}",
        output.status,
    );
    ensure!(
        stdout.lines().filter(|line| *line == CHILD_READY).count() == 1,
        "the exact original Ctrl-C child must report its successful setup once",
    );
    ensure!(
        stdout.lines().filter(|line| line.starts_with("test result: ok. 1 passed; 0 failed; 0 ignored;")).count() == 1,
        "the original Ctrl-C test must execute once without a skip; stdout={stdout:?}",
    );
    Ok(Invocation::ParentVerified)
}
