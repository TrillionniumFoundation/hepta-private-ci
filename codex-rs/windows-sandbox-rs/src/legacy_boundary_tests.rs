use super::LegacyFilesystemIsolationUnavailable;
use crate::run_windows_sandbox_capture;
use crate::run_windows_sandbox_capture_with_filesystem_overrides;
use crate::run_windows_sandbox_legacy_preflight;
use crate::spawn_windows_sandbox_session_legacy;
use anyhow::Result;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::path::Path;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;

fn dacl_snapshot(path: &Path) -> Result<Vec<u16>> {
    // SAFETY: the owned fixture exists. The descriptor and converted string
    // remain allocated until copied, then each LocalAlloc owner is freed once.
    unsafe {
        let (_, descriptor) = crate::fetch_dacl_handle(path)?;
        let mut text = std::ptr::null_mut();
        let mut length = 0;
        let status = ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor,
            SDDL_REVISION_1,
            DACL_SECURITY_INFORMATION,
            &mut text,
            &mut length,
        );
        let result = if status == 0 {
            Err(std::io::Error::last_os_error().into())
        } else {
            Ok(std::slice::from_raw_parts(text, length as usize).to_vec())
        };
        if !text.is_null() {
            LocalFree(text as HLOCAL);
        }
        if !descriptor.is_null() {
            LocalFree(descriptor as HLOCAL);
        }
        result
    }
}

fn marker_command(marker: &Path) -> Vec<String> {
    vec![
        "cmd.exe".to_string(),
        "/D".to_string(),
        "/C".to_string(),
        format!("echo unexpected-child>\"{}\"", marker.display()),
    ]
}

#[test]
fn direct_legacy_entrypoints_refuse_before_home_acl_or_child_side_effects() -> Result<()> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    for profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        let fixture = tempfile::tempdir()?;
        let cwd = fixture.path();
        let roots = [AbsolutePathBuf::from_absolute_path(cwd)?];
        let home = cwd.join("must-not-create-home");
        let marker = cwd.join("must-not-run-child");
        let original_acl = dacl_snapshot(cwd)?;
        let env = HashMap::from([("HEPTA_LEGACY_GUARD".to_string(), "unchanged".to_string())]);

        let capture = run_windows_sandbox_capture(
            &profile,
            &roots,
            &home,
            marker_command(&marker),
            cwd,
            env.clone(),
            /*timeout_ms*/ Some(1_000),
            /*cancellation*/ None,
            /*use_private_desktop*/ false,
        );
        let Err(capture_error) = capture else {
            panic!("legacy capture must refuse");
        };
        assert_eq!(
            capture_error.downcast_ref::<LegacyFilesystemIsolationUnavailable>(),
            Some(&LegacyFilesystemIsolationUnavailable)
        );

        let capture_with_overrides = run_windows_sandbox_capture_with_filesystem_overrides(
            &profile,
            &roots,
            &home,
            marker_command(&marker),
            cwd,
            env.clone(),
            /*timeout_ms*/ Some(1_000),
            /*cancellation*/ None,
            &[],
            &roots,
            /*use_private_desktop*/ false,
        );
        let Err(override_error) = capture_with_overrides else {
            panic!("legacy override must refuse");
        };
        assert_eq!(
            override_error.downcast_ref::<LegacyFilesystemIsolationUnavailable>(),
            Some(&LegacyFilesystemIsolationUnavailable)
        );

        let session = runtime.block_on(spawn_windows_sandbox_session_legacy(
            &profile,
            &roots,
            &home,
            marker_command(&marker),
            cwd,
            env.clone(),
            /*timeout_ms*/ Some(1_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ false,
        ));
        let Err(session_error) = session else {
            panic!("legacy session must refuse");
        };
        assert_eq!(
            session_error.downcast_ref::<LegacyFilesystemIsolationUnavailable>(),
            Some(&LegacyFilesystemIsolationUnavailable)
        );

        let preflight_error =
            run_windows_sandbox_legacy_preflight(&profile, &roots, &home, cwd, &env)
                .expect_err("legacy ACL preflight must refuse");
        assert_eq!(
            preflight_error.downcast_ref::<LegacyFilesystemIsolationUnavailable>(),
            Some(&LegacyFilesystemIsolationUnavailable)
        );
        assert_eq!((home.exists(), marker.exists()), (false, false));
        assert_eq!(dacl_snapshot(cwd)?, original_acl);
    }
    Ok(())
}

#[test]
fn account_broker_entrypoints_refuse_before_home_acl_or_child_side_effects() -> Result<()> {
    use crate::ElevatedSandboxProfileCaptureRequest;
    use crate::WindowsFilesystemIsolationUnavailable;
    use crate::WindowsSandboxProxySettingsMode;
    use crate::WindowsSandboxSessionRequest;
    use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
    use crate::run_windows_sandbox_capture_for_permission_profile_elevated;
    use crate::spawn_prep::prepare_elevated_spawn_context_for_permissions;
    use crate::spawn_windows_sandbox_session_elevated_for_permission_profile;
    use crate::spawn_windows_sandbox_session_for_level;
    use codex_protocol::config_types::WindowsSandboxLevel;

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    for profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        let fixture = tempfile::tempdir()?;
        let cwd = fixture.path();
        let roots = [AbsolutePathBuf::from_absolute_path(cwd)?];
        let home = cwd.join("must-not-create-home");
        let marker = cwd.join("must-not-run-child");
        let original_acl = dacl_snapshot(cwd)?;
        let env = HashMap::from([("HTTP_PROXY".to_string(), "unchanged".to_string())]);
        let mut prepared_env = env.clone();
        let permissions =
            ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
                &profile, &roots,
            )?;
        let Err(error) = prepare_elevated_spawn_context_for_permissions(
            permissions,
            &home,
            cwd,
            &mut prepared_env,
            &marker_command(&marker),
            /*read_roots_override*/ None,
            /*read_roots_include_platform_defaults*/ true,
            /*write_roots_override*/ None,
            &[],
            &[],
            /*proxy_enforced*/ false,
            WindowsSandboxProxySettingsMode::Reconcile,
        ) else {
            panic!("account broker preparation must refuse");
        };
        assert_eq!(
            error.downcast_ref::<WindowsFilesystemIsolationUnavailable>(),
            Some(&WindowsFilesystemIsolationUnavailable)
        );
        assert_eq!(prepared_env, env);

        let capture = run_windows_sandbox_capture_for_permission_profile_elevated(
            ElevatedSandboxProfileCaptureRequest {
                permission_profile: &profile,
                workspace_roots: &roots,
                codex_home: &home,
                command: marker_command(&marker),
                cwd,
                env_map: env.clone(),
                timeout_ms: Some(1_000),
                cancellation: None,
                use_private_desktop: false,
                proxy_enforced: false,
                network_proxy_restricting_sid: None,
                read_roots_override: None,
                read_roots_include_platform_defaults: true,
                write_roots_override: None,
                deny_read_paths_override: &[],
                deny_write_paths_override: &[],
            },
        );
        let Err(error) = capture else {
            panic!("account broker capture must refuse");
        };
        assert_eq!(
            error.downcast_ref::<WindowsFilesystemIsolationUnavailable>(),
            Some(&WindowsFilesystemIsolationUnavailable)
        );

        for level in [
            WindowsSandboxLevel::RestrictedToken,
            WindowsSandboxLevel::Elevated,
        ] {
            let session = runtime.block_on(spawn_windows_sandbox_session_for_level(
                WindowsSandboxSessionRequest {
                    permission_profile: &profile,
                    workspace_roots: &roots,
                    codex_home: &home,
                    command: marker_command(&marker),
                    cwd,
                    env_map: env.clone(),
                    windows_sandbox_level: level,
                    proxy_enforced: false,
                    network_proxy_restricting_sid: None,
                    proxy_settings_mode: WindowsSandboxProxySettingsMode::Reconcile,
                    timeout_ms: Some(1_000),
                    read_roots_override: None,
                    read_roots_include_platform_defaults: true,
                    write_roots_override: None,
                    deny_read_paths_override: &[],
                    deny_write_paths_override: &[],
                    tty: false,
                    stdin_open: false,
                    use_private_desktop: false,
                },
            ));
            let Err(error) = session else {
                panic!("managed session must refuse");
            };
            assert_eq!(
                error.downcast_ref::<WindowsFilesystemIsolationUnavailable>(),
                Some(&WindowsFilesystemIsolationUnavailable)
            );
        }
        let session = runtime.block_on(
            spawn_windows_sandbox_session_elevated_for_permission_profile(
                &profile,
                &roots,
                &home,
                marker_command(&marker),
                cwd,
                env,
                /*proxy_enforced*/ false,
                /*network_proxy_restricting_sid*/ None,
                /*timeout_ms*/ Some(1_000),
                /*read_roots_override*/ None,
                /*read_roots_include_platform_defaults*/ true,
                /*write_roots_override*/ None,
                &[],
                &[],
                /*tty*/ false,
                /*stdin_open*/ false,
                /*use_private_desktop*/ false,
            ),
        );
        let Err(error) = session else {
            panic!("explicit account broker session must refuse");
        };
        assert_eq!(
            error.downcast_ref::<WindowsFilesystemIsolationUnavailable>(),
            Some(&WindowsFilesystemIsolationUnavailable)
        );
        assert_eq!((home.exists(), marker.exists()), (false, false));
        assert_eq!(dacl_snapshot(cwd)?, original_acl);
    }
    Ok(())
}
