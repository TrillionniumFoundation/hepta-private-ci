use std::path::PathBuf;

use codex_test_binary_support::TestBinaryDispatchGuard;
use ctor::ctor;

pub(crate) mod exec_server;

pub(crate) const DELAYED_OUTPUT_AFTER_EXIT_PARENT_ARG: &str =
    codex_test_binary_support::exec_server::DELAYED_OUTPUT_AFTER_EXIT_PARENT_ARG;
pub(crate) const SYSTEM_PROXY_REQUEST_URL_ENV: &str =
    codex_test_binary_support::exec_server::SYSTEM_PROXY_REQUEST_URL_ENV;
pub(crate) const SYSTEM_PROXY_URL_ENV: &str =
    codex_test_binary_support::exec_server::SYSTEM_PROXY_URL_ENV;

#[ctor]
pub static TEST_BINARY_DISPATCH_GUARD: Option<TestBinaryDispatchGuard> = {
    let guard = codex_test_binary_support::exec_server::configure_exec_server_test_dispatch();
    codex_test_binary_support::exec_server::maybe_run_exec_server_test_modes(guard.as_ref());
    guard
};

#[cfg(windows)]
struct WindowsTestBinaryRuntime {
    _directory: tempfile::TempDir,
    executable: PathBuf,
}

pub(crate) fn current_test_binary_helper_paths() -> anyhow::Result<(PathBuf, Option<PathBuf>)> {
    let current_exe = codex_test_binary_support::test_binary_helper_exe()?;
    #[cfg(windows)]
    let current_exe = {
        // Real sandbox helpers are discovered beside the running executable.
        // Keep one staged runtime for the test process so helpers can outlive
        // individual harnesses without recopying the large test binary per case.
        static RUNTIME: std::sync::OnceLock<anyhow::Result<WindowsTestBinaryRuntime>> =
            std::sync::OnceLock::new();
        let runtime = RUNTIME
            .get_or_init(|| {
                let directory = tempfile::TempDir::new()?;
                let executable = directory.path().join("codex-exec-server-tests.exe");
                std::fs::hard_link(&current_exe, &executable)
                    .or_else(|_| std::fs::copy(&current_exe, &executable).map(|_| ()))?;
                for helper in ["codex-command-runner", "codex-windows-sandbox-setup"] {
                    let source = codex_utils_cargo_bin::cargo_bin(helper)?;
                    let destination = directory.path().join(format!("{helper}.exe"));
                    std::fs::hard_link(&source, &destination)
                        .or_else(|_| std::fs::copy(&source, &destination).map(|_| ()))?;
                }
                Ok(WindowsTestBinaryRuntime {
                    _directory: directory,
                    executable,
                })
            })
            .as_ref()
            .map_err(|error| anyhow::anyhow!("failed to stage Windows test runtime: {error:#}"))?;
        runtime.executable.clone()
    };
    let codex_linux_sandbox_exe = if cfg!(target_os = "linux") {
        TEST_BINARY_DISPATCH_GUARD
            .as_ref()
            .and_then(|guard| guard.paths().codex_linux_sandbox_exe.clone())
            .or_else(|| Some(current_exe.clone()))
    } else {
        None
    };
    Ok((current_exe, codex_linux_sandbox_exe))
}
