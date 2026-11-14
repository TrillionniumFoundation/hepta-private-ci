use super::RunnerTransportRequest;
use super::spawn_runner_transport_with_retry;
use crate::blocking_caller::CapturedCaller;
use crate::identity::SandboxIdentityRequest;
use crate::identity::refresh_logon_sandbox_creds_with_lease;
use crate::ipc_framed::SpawnRequest;
use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use crate::runner_client::RunnerTransport;
use crate::runner_client::spawn_runner_transport;
use crate::sandbox_account::SandboxAccountLease;
use crate::spawn_prep::prepare_elevated_spawn_context_for_permissions;
use anyhow::Result;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

pub(super) struct SessionSetup {
    pub(super) permission_profile: PermissionProfile,
    pub(super) workspace_roots: Vec<AbsolutePathBuf>,
    pub(super) codex_home: PathBuf,
    pub(super) cwd: PathBuf,
    pub(super) command: Vec<String>,
    pub(super) env_map: HashMap<String, String>,
    pub(super) read_roots_override: Option<Vec<PathBuf>>,
    pub(super) read_roots_include_platform_defaults: bool,
    pub(super) write_roots_override: Option<Vec<PathBuf>>,
    pub(super) deny_read_paths_override: Vec<PathBuf>,
    pub(super) deny_write_paths_override: Vec<PathBuf>,
    pub(super) proxy_enforced: bool,
    pub(super) proxy_settings_mode: crate::WindowsSandboxProxySettingsMode,
    pub(super) network_proxy_restricting_sid: Option<String>,
    pub(super) timeout_ms: Option<u64>,
    pub(super) tty: bool,
    pub(super) stdin_open: bool,
    pub(super) use_private_desktop: bool,
}

struct PendingRequest(Arc<AtomicBool>);

impl Drop for PendingRequest {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

fn with_active_request<T>(active: &AtomicBool, operation: impl FnOnce() -> Result<T>) -> Result<T> {
    anyhow::ensure!(
        active.load(Ordering::Acquire),
        "sandbox session request was cancelled"
    );
    operation()
}

pub(super) async fn start(
    mut options: SessionSetup,
    caller: CapturedCaller,
) -> Result<RunnerTransport> {
    let active = Arc::new(AtomicBool::new(true));
    let _pending = PendingRequest(Arc::clone(&active));
    tokio::task::spawn_blocking(move || -> Result<_> {
        let _caller = caller.enter()?;
        anyhow::ensure!(
            active.load(Ordering::Acquire),
            "sandbox session request was cancelled"
        );
        let account_lease = SandboxAccountLease::acquire()?;
        anyhow::ensure!(
            active.load(Ordering::Acquire),
            "sandbox session request was cancelled"
        );
        let permissions =
            ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
                &options.permission_profile,
                &options.workspace_roots,
            )?;
        let elevated = prepare_elevated_spawn_context_for_permissions(
            permissions.clone(),
            &options.codex_home,
            &options.cwd,
            &mut options.env_map,
            &options.command,
            options.read_roots_override.as_deref(),
            options.read_roots_include_platform_defaults,
            options.write_roots_override.as_deref(),
            &options.deny_read_paths_override,
            &options.deny_write_paths_override,
            options.proxy_enforced,
            options.proxy_settings_mode,
            &account_lease,
        )?;
        anyhow::ensure!(
            active.load(Ordering::Acquire),
            "sandbox session request was cancelled"
        );
        let request = RunnerTransportRequest {
            permissions,
            codex_home: options.codex_home.clone(),
            cwd: options.cwd.clone(),
            env_map: options.env_map.clone(),
            logs_base_dir: elevated.logs_base_dir,
            spawn_request: SpawnRequest {
                command: options.command,
                cwd: options.cwd,
                env: options.env_map,
                permission_profile: options.permission_profile,
                workspace_roots: options.workspace_roots,
                codex_home: elevated.sandbox_base,
                real_codex_home: options.codex_home,
                cap_sids: elevated.cap_sids,
                read_cap_sids: elevated.read_cap_sids,
                network_proxy_restricting_sid: options.network_proxy_restricting_sid,
                timeout_ms: options.timeout_ms,
                tty: options.tty,
                stdin_open: options.stdin_open,
                use_private_desktop: options.use_private_desktop,
            },
            read_roots_override: options.read_roots_override,
            read_roots_include_platform_defaults: options.read_roots_include_platform_defaults,
            write_roots_override: options.write_roots_override,
            deny_read_paths_override: options.deny_read_paths_override,
            deny_write_paths_override: options.deny_write_paths_override,
            proxy_enforced: options.proxy_enforced,
            proxy_settings_mode: options.proxy_settings_mode,
        };
        let transport = spawn_runner_transport_with_retry(
            elevated.sandbox_creds,
            &request,
            |codex_home, cwd, sandbox_creds, logs_base_dir, spawn_request| {
                with_active_request(&active, || {
                    spawn_runner_transport(
                        codex_home,
                        cwd,
                        sandbox_creds,
                        logs_base_dir,
                        spawn_request,
                    )
                })
            },
            |permissions,
             command_cwd,
             env_map,
             codex_home,
             read_roots_override,
             read_roots_include_platform_defaults,
             write_roots_override,
             deny_read_paths_override,
             deny_write_paths_override,
             proxy_enforced,
             proxy_settings_mode| {
                anyhow::ensure!(
                    active.load(Ordering::Acquire),
                    "sandbox session request was cancelled"
                );
                refresh_logon_sandbox_creds_with_lease(
                    SandboxIdentityRequest {
                        permissions,
                        command_cwd,
                        env_map,
                        codex_home,
                        read_roots_override,
                        read_roots_include_platform_defaults,
                        write_roots_override,
                        deny_read_paths_override,
                        deny_write_paths_override,
                        proxy_enforced,
                        proxy_settings_mode,
                    },
                    &account_lease,
                )
            },
        )?;
        // If the awaiting future disappeared during the handshake, dropping the
        // transport closes its pipes and lets the runner clean up its child.
        anyhow::ensure!(
            active.load(Ordering::Acquire),
            "sandbox session request was cancelled"
        );
        Ok(transport)
    })
    .await
    .map_err(|err| anyhow::anyhow!("runner setup task failed: {err}"))?
}

#[cfg(test)]
#[path = "elevated_session_setup_tests.rs"]
mod tests;
