use crate::credential_store;
use crate::logging::debug_log;
use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use crate::setup::SandboxNetworkIdentity;
use crate::setup::SandboxUsersFile;
use crate::setup::SetupMarker;
use crate::setup::gather_read_roots;
use crate::setup::gather_write_roots_for_permissions;
use crate::setup::offline_proxy_settings_from_env;
use crate::setup::run_elevated_setup_with_proxy_settings;
use crate::setup::run_setup_refresh_with_overrides_and_proxy_settings;
use crate::setup::setup_marker_path;
use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

#[derive(Debug, Clone)]
struct SandboxIdentity {
    username: String,
    password: String,
}

#[derive(Debug, Clone)]
pub struct SandboxCreds {
    pub username: String,
    pub password: String,
}

/// Returns true when the on-disk setup artifacts exist and match the current
/// setup version.
///
/// This is a coarse readiness check; `require_logon_sandbox_creds` performs the
/// additional runtime validation for offline firewall settings.
pub fn sandbox_setup_is_complete(codex_home: &Path) -> bool {
    let marker_ok = matches!(load_marker(codex_home), Ok(Some(marker)) if marker.version_matches());
    if !marker_ok {
        return false;
    }
    matches!(load_users(codex_home), Ok(Some(users)) if users.version_matches())
}

fn load_marker(codex_home: &Path) -> Result<Option<SetupMarker>> {
    let path = setup_marker_path(codex_home);
    let marker = match fs::read_to_string(&path) {
        Ok(contents) => match serde_json::from_str::<SetupMarker>(&contents) {
            Ok(m) => Some(m),
            Err(err) => {
                debug_log(
                    &format!("sandbox setup marker parse failed: {err}"),
                    Some(codex_home),
                );
                None
            }
        },
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => None,
        Err(err) => {
            debug_log(
                &format!("sandbox setup marker read failed: {err}"),
                Some(codex_home),
            );
            None
        }
    };
    Ok(marker)
}

fn load_users(codex_home: &Path) -> Result<Option<SandboxUsersFile>> {
    // Only genuine absence is None. Inaccessible, redirected, unprotected,
    // malformed or incompatible credentials cannot trigger fresh provisioning.
    credential_store::read_protected_users(codex_home)
        .context("validate retained sandbox credential file without changing it")
}

fn select_identity(
    network_identity: SandboxNetworkIdentity,
    codex_home: &Path,
) -> Result<Option<SandboxIdentity>> {
    let _marker = match load_marker(codex_home)? {
        Some(m) if m.version_matches() => m,
        _ => return Ok(None),
    };
    let Some((username, password)) =
        credential_store::verified_identity(codex_home, network_identity)?
    else {
        return Ok(None);
    };
    Ok(Some(SandboxIdentity { username, password }))
}

#[allow(clippy::too_many_arguments)]
pub fn require_logon_sandbox_creds(
    permissions: &ResolvedWindowsSandboxPermissions,
    command_cwd: &Path,
    env_map: &HashMap<String, String>,
    codex_home: &Path,
    read_roots_override: Option<&[PathBuf]>,
    read_roots_include_platform_defaults: bool,
    write_roots_override: Option<&[PathBuf]>,
    deny_read_paths_override: &[PathBuf],
    deny_write_paths_override: &[PathBuf],
    proxy_enforced: bool,
    proxy_settings_mode: crate::WindowsSandboxProxySettingsMode,
) -> Result<SandboxCreds> {
    // Validate existing credential storage even when the readiness marker is
    // absent or stale. A broken existing file is never treated as a new home.
    let _existing_users = load_users(codex_home)?;
    let sandbox_dir = crate::setup::sandbox_dir(codex_home);
    let needed_read = read_roots_override
        .map(<[PathBuf]>::to_vec)
        .unwrap_or_else(|| gather_read_roots(command_cwd, permissions, env_map, codex_home));
    let needed_write = write_roots_override
        .map(<[PathBuf]>::to_vec)
        .unwrap_or_else(|| gather_write_roots_for_permissions(permissions, command_cwd, env_map));
    let network_identity = SandboxNetworkIdentity::from_permissions(permissions, proxy_enforced);
    let marker = load_marker(codex_home)?;
    let desired_offline_proxy_settings = desired_offline_proxy_settings(
        marker.as_ref(),
        proxy_settings_mode,
        env_map,
        network_identity,
    );
    // NOTE: Do not add CODEX_HOME/.sandbox to `needed_write`; it must remain non-writable by the
    // restricted capability token. The setup helper's `lock_sandbox_dir` is responsible for
    // granting the sandbox group access to this directory without granting the capability SID.
    let mut setup_reason: Option<String> = None;

    let mut identity = match marker {
        Some(marker) if marker.version_matches() => {
            if let Some(reason) =
                marker.request_mismatch_reason(network_identity, &desired_offline_proxy_settings)
            {
                setup_reason = Some(reason);
                None
            } else {
                let selected = select_identity(network_identity, codex_home)?;
                if selected.is_none() {
                    setup_reason = Some(
                        "sandbox users missing or incompatible with marker version".to_string(),
                    );
                }
                selected
            }
        }
        _ => {
            setup_reason = Some("sandbox setup marker missing or incompatible".to_string());
            None
        }
    };

    if identity.is_none() {
        if let Some(reason) = &setup_reason {
            crate::logging::log_note(
                &format!("sandbox setup required: {reason}"),
                Some(&sandbox_dir),
            );
        } else {
            crate::logging::log_note("sandbox setup required", Some(&sandbox_dir));
        }
        run_elevated_setup_with_proxy_settings(
            crate::setup::SandboxSetupRequest {
                permissions,
                command_cwd,
                env_map,
                codex_home,
                proxy_enforced,
            },
            crate::setup::SetupRootOverrides {
                read_roots: Some(needed_read.clone()),
                read_roots_include_platform_defaults,
                write_roots: Some(needed_write.clone()),
                deny_read_paths: Some(deny_read_paths_override.to_vec()),
                deny_write_paths: Some(deny_write_paths_override.to_vec()),
            },
            &desired_offline_proxy_settings,
        )?;
        identity = select_identity(network_identity, codex_home)?;
    }
    // Always refresh ACLs (non-elevated) for current roots via the setup binary.
    run_setup_refresh_with_overrides_and_proxy_settings(
        crate::setup::SandboxSetupRequest {
            permissions,
            command_cwd,
            env_map,
            codex_home,
            proxy_enforced,
        },
        crate::setup::SetupRootOverrides {
            read_roots: Some(needed_read),
            read_roots_include_platform_defaults,
            write_roots: Some(needed_write),
            deny_read_paths: Some(deny_read_paths_override.to_vec()),
            deny_write_paths: Some(deny_write_paths_override.to_vec()),
        },
        &desired_offline_proxy_settings,
    )?;
    let identity = identity.ok_or_else(|| {
        anyhow!(
            "Windows sandbox setup is missing or out of date; rerun the sandbox setup with elevation"
        )
    })?;
    Ok(SandboxCreds {
        username: identity.username,
        password: identity.password,
    })
}

fn desired_offline_proxy_settings(
    marker: Option<&SetupMarker>,
    proxy_settings_mode: crate::WindowsSandboxProxySettingsMode,
    env_map: &HashMap<String, String>,
    network_identity: SandboxNetworkIdentity,
) -> crate::setup::OfflineProxySettings {
    match (marker, proxy_settings_mode) {
        (Some(marker), crate::WindowsSandboxProxySettingsMode::Preserve)
            if marker.version_matches() =>
        {
            marker.offline_proxy_settings()
        }
        _ => offline_proxy_settings_from_env(env_map, network_identity),
    }
}

fn revalidate_retained_identity(
    network_identity: SandboxNetworkIdentity,
    codex_home: &Path,
) -> Result<SandboxCreds> {
    let _existing_users = load_users(codex_home)?;
    let identity = select_identity(network_identity, codex_home)?
        .context("sandbox login revalidation requires an existing ready marker and protected credentials; no reset or provisioning was attempted")?;
    Ok(SandboxCreds {
        username: identity.username,
        password: identity.password,
    })
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn refresh_logon_sandbox_creds(
    permissions: &ResolvedWindowsSandboxPermissions,
    _command_cwd: &Path,
    env_map: &HashMap<String, String>,
    codex_home: &Path,
    _read_roots_override: Option<&[PathBuf]>,
    _read_roots_include_platform_defaults: bool,
    _write_roots_override: Option<&[PathBuf]>,
    _deny_read_paths_override: &[PathBuf],
    _deny_write_paths_override: &[PathBuf],
    proxy_enforced: bool,
    proxy_settings_mode: crate::WindowsSandboxProxySettingsMode,
) -> Result<SandboxCreds> {
    let network_identity = SandboxNetworkIdentity::from_permissions(permissions, proxy_enforced);
    let marker = load_marker(codex_home)?
        .filter(|marker| marker.version_matches())
        .context(
            "sandbox login revalidation has no current readiness marker; no reset attempted",
        )?;
    let desired = desired_offline_proxy_settings(
        Some(&marker),
        proxy_settings_mode,
        env_map,
        network_identity,
    );
    if let Some(reason) = marker.request_mismatch_reason(network_identity, &desired) {
        anyhow::bail!("sandbox login revalidation cannot change shared network setup: {reason}");
    }
    // The existing one retry may reauthenticate the same fixed local identities.
    // It cannot delete ciphertext, rotate passwords or invoke a setup helper.
    revalidate_retained_identity(network_identity, codex_home)
}

#[cfg(test)]
mod tests {
    use super::desired_offline_proxy_settings;
    use super::revalidate_retained_identity;
    use crate::WindowsSandboxProxySettingsMode;
    use crate::setup::SandboxNetworkIdentity;
    use crate::setup::SetupMarker;
    use crate::setup::sandbox_users_path;
    use pretty_assertions::assert_eq;
    use std::collections::HashMap;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn failed_login_revalidation_preserves_existing_credential_bytes() {
        let codex_home = TempDir::new().expect("tempdir");
        let users_path = sandbox_users_path(codex_home.path());
        fs::create_dir_all(users_path.parent().expect("sandbox secrets dir"))
            .expect("create sandbox secrets dir");
        let original = b"invalid-existing-credential-evidence";
        fs::write(&users_path, original).expect("write original failure evidence");

        let result =
            revalidate_retained_identity(SandboxNetworkIdentity::Offline, codex_home.path());
        assert!(
            result.is_err(),
            "invalid existing credentials must remain a failure"
        );
        assert_eq!(
            fs::read(&users_path).expect("read preserved original"),
            original
        );
    }

    #[test]
    fn failed_login_revalidation_does_not_create_missing_credentials() {
        let codex_home = TempDir::new().expect("tempdir");
        let users_path = sandbox_users_path(codex_home.path());
        let parent = users_path.parent().expect("sandbox secrets dir");
        assert!(!parent.try_exists().expect("read initial directory absence"));

        let result =
            revalidate_retained_identity(SandboxNetworkIdentity::Offline, codex_home.path());
        assert!(
            result.is_err(),
            "missing credentials must not cause automatic rebuilding"
        );
        assert!(!users_path.try_exists().expect("read original file absence"));
        assert!(
            !parent
                .try_exists()
                .expect("read original directory absence")
        );
    }

    #[test]
    fn preserving_proxy_settings_uses_the_existing_marker() {
        let marker = SetupMarker {
            version: crate::setup::SETUP_VERSION,
            offline_username: "offline".to_string(),
            online_username: "online".to_string(),
            created_at: None,
            proxy_ports: vec![7890],
            allow_local_binding: true,
        };
        let env_map = HashMap::from([(
            "HTTP_PROXY".to_string(),
            "http://127.0.0.1:8080".to_string(),
        )]);

        assert_eq!(
            desired_offline_proxy_settings(
                Some(&marker),
                WindowsSandboxProxySettingsMode::Preserve,
                &env_map,
                SandboxNetworkIdentity::Offline,
            ),
            marker.offline_proxy_settings()
        );
        assert_eq!(
            desired_offline_proxy_settings(
                Some(&marker),
                WindowsSandboxProxySettingsMode::Reconcile,
                &env_map,
                SandboxNetworkIdentity::Offline,
            )
            .proxy_ports,
            vec![8080]
        );
    }

    #[test]
    fn guardian_preserve_mode_does_not_churn_marker_with_empty_proxy_ports() {
        let marker = SetupMarker {
            version: crate::setup::SETUP_VERSION,
            offline_username: "offline".to_string(),
            online_username: "online".to_string(),
            created_at: None,
            proxy_ports: vec![3128, 8081],
            allow_local_binding: true,
        };
        let env_map = HashMap::new();
        let reconciled = desired_offline_proxy_settings(
            Some(&marker),
            WindowsSandboxProxySettingsMode::Reconcile,
            &env_map,
            SandboxNetworkIdentity::Offline,
        );
        assert_eq!(reconciled.proxy_ports, Vec::<u16>::new());

        let desired = desired_offline_proxy_settings(
            Some(&marker),
            WindowsSandboxProxySettingsMode::Preserve,
            &env_map,
            SandboxNetworkIdentity::Offline,
        );
        assert_eq!(desired, marker.offline_proxy_settings());
        assert_eq!(
            marker.request_mismatch_reason(SandboxNetworkIdentity::Offline, &desired),
            None
        );
    }
}
