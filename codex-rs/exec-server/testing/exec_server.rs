//! Minimal exec-server fixture for Bazel-only integration tests.
//!
//! Linking only exec-server avoids depending on the full Codex CLI binary
//! when a test only needs a WebSocket executor endpoint. It handles the process
//! and filesystem helper modes because sandboxed requests re-exec this binary.

use codex_exec_server::ExecServerRuntimePaths;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use std::ffi::OsStr;

fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let helper = std::env::args_os().nth(1);
    #[cfg(unix)]
    if helper.as_deref() == Some(OsStr::new(codex_exec_server::CODEX_ARG0_EXEC_HELPER_ARG1)) {
        codex_exec_server::run_arg0_exec_helper_main();
    }
    if helper.as_deref() == Some(OsStr::new(codex_exec_server::CODEX_FS_HELPER_ARG1)) {
        codex_exec_server::run_fs_helper_main();
    }
    #[cfg(windows)]
    if helper.as_deref()
        == Some(OsStr::new(
            codex_windows_sandbox::CODEX_WINDOWS_SANDBOX_ARG1,
        ))
    {
        codex_windows_sandbox::run_windows_sandbox_wrapper_main();
    }
    // Each helper owns its runtime. Dispatch before starting the server runtime
    // so filesystem helpers neither nest Tokio runtimes nor start another server.
    run_server()
}

#[tokio::main]
async fn run_server() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let current_exe = std::env::current_exe()?;
    let runtime_paths =
        ExecServerRuntimePaths::new(current_exe, /*codex_linux_sandbox_exe*/ None)?;
    codex_exec_server::run_main(
        "ws://127.0.0.1:0",
        runtime_paths,
        HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
    )
    .await
}
