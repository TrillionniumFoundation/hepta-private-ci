use super::ExecCapturePolicy;
use super::ExecParams;
use super::exec_windows_sandbox;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_protocol::models::SandboxPermissions;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;

#[tokio::test]
async fn explicit_legacy_capture_rejects_without_a_child_or_automatic_elevation() {
    let fixture = tempfile::tempdir().expect("create legacy rejection fixture");
    let cwd = AbsolutePathBuf::from_absolute_path(fixture.path()).expect("absolute fixture");
    let marker = fixture.path().join("child-started");
    for permission_profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        let error = exec_windows_sandbox(
            ExecParams {
                command: vec![
                    "C:\\Windows\\System32\\cmd.exe".to_string(),
                    "/d".to_string(),
                    "/c".to_string(),
                    "echo started>\"%SPAWN_MARKER%\"".to_string(),
                ],
                cwd: cwd.clone(),
                expiration: 5_000.into(),
                capture_policy: ExecCapturePolicy::ShellTool,
                env: HashMap::from([("SPAWN_MARKER".to_string(), marker.display().to_string())]),
                network: None,
                network_environment_id: None,
                sandbox_permissions: SandboxPermissions::UseDefault,
                windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
                windows_sandbox_private_desktop: true,
                justification: None,
                arg0: None,
            },
            &permission_profile,
            &cwd,
            std::slice::from_ref(&cwd),
            None,
        )
        .await
        .err()
        .expect("unsafe legacy capture must be rejected before setup");
        assert_eq!(
            error.to_string(),
            "the legacy restricted-token Windows sandbox cannot enforce filesystem deletion boundaries; use the elevated Windows sandbox backend"
        );
        assert!(!marker.try_exists().expect("inspect child marker"));
    }
}
