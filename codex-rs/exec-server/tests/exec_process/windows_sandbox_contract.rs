use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_exec_server::ExecParams;
use codex_exec_server::ExecServerError;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::ProcessId;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::protocol::SandboxPolicy;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::create_process_context;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[serial_test::serial(remote_exec_server)]
async fn remote_windows_restricted_token_request_is_rejected() -> Result<()> {
    let context = create_process_context(/*use_remote*/ true).await?;
    let server = context._server.as_ref().context("remote exec-server")?;
    let sandbox_state = server.codex_home().join(".sandbox");
    assert!(!sandbox_state.try_exists()?);
    let workspace = TempDir::new()?;
    let launch_marker = workspace.path().join("unexpected-launch.txt");
    let cwd = PathUri::from_host_native_path(workspace.path())?;
    let mut sandbox = FileSystemSandboxContext::from_legacy_sandbox_policy(
        SandboxPolicy::new_read_only_policy(),
        cwd.clone(),
    )?;
    sandbox.windows_sandbox_level = WindowsSandboxLevel::RestrictedToken;

    let result = context
        .backend
        .start(ExecParams {
            process_id: ProcessId::from("proc-windows-legacy-refused"),
            argv: vec![
                r"C:\Windows\System32\cmd.exe".to_string(),
                "/D".to_string(),
                "/S".to_string(),
                "/C".to_string(),
                format!("echo unexpected > \"{}\"", launch_marker.display()),
            ],
            cwd,
            shell_snapshot: None,
            env_policy: /*env_policy*/ None,
            env: Default::default(),
            tty: false,
            pipe_stdin: true,
            arg0: None,
            sandbox: Some(sandbox),
            enforce_managed_network: false,
            managed_network: None,
            network_proxy: None,
        })
        .await;
    // Capture both observations before any reply classification or cleanup.
    // An inaccessible path is an error, never evidence that it is absent.
    let observed = (launch_marker.try_exists(), sandbox_state.try_exists());
    let error = match result {
        Ok(session) => {
            let cleanup = session.process.terminate().await;
            bail!(
                "RestrictedToken unexpectedly returned a process session; \
                 observations={observed:?}, cleanup={cleanup:?}"
            );
        }
        Err(error) => error,
    };
    let observed = (
        observed.0.context("inspect launch marker after request")?,
        observed.1.context("inspect sandbox state after request")?,
    );
    assert_eq!(observed, (false, false), "request failed with {error:?}");
    let ExecServerError::Server { code, message } = error else {
        bail!("expected the original legacy isolation refusal, got {error:?}");
    };
    assert_eq!(code, -32603);
    assert_eq!(
        message,
        "legacy Windows sandbox isolation is unavailable: ambient parent FILE_DELETE_CHILD \
         can bypass deletion boundaries; no qualified replacement preserves this read policy"
    );
    Ok(())
}
