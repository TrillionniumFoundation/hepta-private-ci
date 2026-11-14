use crate::blocking_caller::CapturedCaller;

#[path = "elevated_session_setup.rs"]
mod session_setup;

use super::windows_common::finish_driver_spawn;
use super::windows_common::make_runner_resizer;
use super::windows_common::start_runner_pipe_writer;
use super::windows_common::start_runner_stdin_writer;
use super::windows_common::start_runner_stdout_reader;
use crate::identity::SandboxCreds;
use crate::ipc_framed::EmptyPayload;
use crate::ipc_framed::FramedMessage;
use crate::ipc_framed::IPC_PROTOCOL_VERSION;
use crate::ipc_framed::Message;
use crate::ipc_framed::SpawnRequest;
use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use crate::runner_client::retry_runner_spawn_once;
use anyhow::Result;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_pty::ProcessDriver;
use codex_utils_pty::SpawnedProcess;
use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

struct RunnerTransportRequest {
    permissions: ResolvedWindowsSandboxPermissions,
    codex_home: PathBuf,
    cwd: PathBuf,
    env_map: HashMap<String, String>,
    logs_base_dir: Option<PathBuf>,
    spawn_request: SpawnRequest,
    read_roots_override: Option<Vec<PathBuf>>,
    read_roots_include_platform_defaults: bool,
    write_roots_override: Option<Vec<PathBuf>>,
    deny_read_paths_override: Vec<PathBuf>,
    deny_write_paths_override: Vec<PathBuf>,
    proxy_enforced: bool,
    proxy_settings_mode: crate::WindowsSandboxProxySettingsMode,
}

fn spawn_runner_transport_with_retry<T>(
    sandbox_creds: SandboxCreds,
    request: &RunnerTransportRequest,
    mut spawn: impl FnMut(&Path, &Path, &SandboxCreds, Option<&Path>, SpawnRequest) -> Result<T>,
    refresh: impl FnOnce(
        &ResolvedWindowsSandboxPermissions,
        &Path,
        &HashMap<String, String>,
        &Path,
        Option<&[PathBuf]>,
        bool,
        Option<&[PathBuf]>,
        &[PathBuf],
        &[PathBuf],
        bool,
        crate::WindowsSandboxProxySettingsMode,
    ) -> Result<SandboxCreds>,
) -> Result<T> {
    retry_runner_spawn_once(
        sandbox_creds,
        &request.spawn_request.command,
        |sandbox_creds| {
            spawn(
                &request.codex_home,
                &request.cwd,
                &sandbox_creds,
                request.logs_base_dir.as_deref(),
                request.spawn_request.clone(),
            )
        },
        || {
            refresh(
                &request.permissions,
                &request.cwd,
                &request.env_map,
                &request.codex_home,
                request.read_roots_override.as_deref(),
                request.read_roots_include_platform_defaults,
                request.write_roots_override.as_deref(),
                &request.deny_read_paths_override,
                &request.deny_write_paths_override,
                request.proxy_enforced,
                request.proxy_settings_mode,
            )
        },
    )
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn spawn_windows_sandbox_session_elevated_for_permission_profile(
    permission_profile: &PermissionProfile,
    workspace_roots: &[AbsolutePathBuf],
    codex_home: &Path,
    command: Vec<String>,
    cwd: &Path,
    env_map: HashMap<String, String>,
    proxy_enforced: bool,
    network_proxy_restricting_sid: Option<String>,
    proxy_settings_mode: crate::WindowsSandboxProxySettingsMode,
    timeout_ms: Option<u64>,
    read_roots_override: Option<&[PathBuf]>,
    read_roots_include_platform_defaults: bool,
    write_roots_override: Option<&[PathBuf]>,
    deny_read_paths_override: &[AbsolutePathBuf],
    deny_write_paths_override: &[AbsolutePathBuf],
    tty: bool,
    stdin_open: bool,
    use_private_desktop: bool,
) -> Result<SpawnedProcess> {
    let options = session_setup::SessionSetup {
        permission_profile: permission_profile.clone(),
        workspace_roots: workspace_roots.to_vec(),
        codex_home: codex_home.to_path_buf(),
        cwd: cwd.to_path_buf(),
        command,
        env_map,
        read_roots_override: read_roots_override.map(<[PathBuf]>::to_vec),
        read_roots_include_platform_defaults,
        write_roots_override: write_roots_override.map(<[PathBuf]>::to_vec),
        deny_read_paths_override: deny_read_paths_override
            .iter()
            .map(AbsolutePathBuf::to_path_buf)
            .collect(),
        deny_write_paths_override: deny_write_paths_override
            .iter()
            .map(AbsolutePathBuf::to_path_buf)
            .collect(),
        proxy_enforced,
        proxy_settings_mode,
        network_proxy_restricting_sid,
        timeout_ms,
        tty,
        stdin_open,
        use_private_desktop,
    };
    let caller = CapturedCaller::capture()?;
    let transport = session_setup::start(options, caller).await?;
    let (pipe_write, pipe_read) = transport.into_files();

    let (writer_tx, writer_rx) = mpsc::channel::<Vec<u8>>(128);
    let (stdout_tx, stdout_rx) = broadcast::channel::<Vec<u8>>(256);
    let stderr_rx = if tty {
        None
    } else {
        Some(broadcast::channel::<Vec<u8>>(256))
    };
    let (exit_tx, exit_rx) = oneshot::channel::<i32>();

    let outbound_tx = start_runner_pipe_writer(pipe_write);
    let writer_handle = start_runner_stdin_writer(writer_rx, outbound_tx.clone(), tty, stdin_open);
    let terminator = {
        let outbound_tx = outbound_tx.clone();
        Some(Box::new(move || {
            let _ = outbound_tx.send(FramedMessage {
                version: IPC_PROTOCOL_VERSION,
                message: Message::Terminate {
                    payload: EmptyPayload::default(),
                },
            });
        }) as Box<dyn FnMut() + Send + Sync>)
    };

    start_runner_stdout_reader(
        pipe_read,
        stdout_tx,
        stderr_rx.as_ref().map(|(tx, _rx)| tx.clone()),
        exit_tx,
    );

    Ok(finish_driver_spawn(
        ProcessDriver {
            writer_tx,
            stdout_rx,
            stderr_rx: stderr_rx.map(|(_tx, rx)| rx),
            exit_rx,
            terminator,
            writer_handle: Some(writer_handle),
            resizer: if tty {
                Some(make_runner_resizer(outbound_tx))
            } else {
                None
            },
            tty,
        },
        stdin_open,
    ))
}

#[cfg(test)]
#[path = "elevated_tests.rs"]
mod tests;
