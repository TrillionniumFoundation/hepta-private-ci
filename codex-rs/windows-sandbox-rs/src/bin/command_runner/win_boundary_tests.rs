use super::spawn_ipc_process;
use anyhow::Result;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_windows_sandbox::SpawnRequest;
use codex_windows_sandbox::WindowsFilesystemIsolationUnavailable;
use pretty_assertions::assert_eq;
use std::collections::HashMap;

#[test]
fn standalone_runner_refuses_before_token_preparation_or_child_spawn() -> Result<()> {
    for profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        let fixture = tempfile::tempdir()?;
        let home = fixture.path().join("must-not-create-home");
        let marker = fixture.path().join("must-not-run-child");
        let request = SpawnRequest {
            command: vec![
                "cmd.exe".to_string(),
                "/D".to_string(),
                "/C".to_string(),
                format!("echo unexpected-child>\"{}\"", marker.display()),
            ],
            cwd: fixture.path().to_path_buf(),
            env: HashMap::from([("HTTP_PROXY".to_string(), "unchanged".to_string())]),
            permission_profile: profile,
            workspace_roots: vec![AbsolutePathBuf::from_absolute_path(fixture.path())?],
            codex_home: home.clone(),
            real_codex_home: home.clone(),
            // The guard must run even before SID parsing can reject this request.
            cap_sids: vec!["not-a-valid-sid".to_string()],
            network_proxy_restricting_sid: None,
            timeout_ms: Some(1_000),
            tty: false,
            stdin_open: false,
            use_private_desktop: false,
        };
        let original_env = request.env.clone();
        let Err(error) = spawn_ipc_process(&request) else {
            panic!("standalone managed child launch must refuse");
        };
        assert_eq!(
            error.downcast_ref::<WindowsFilesystemIsolationUnavailable>(),
            Some(&WindowsFilesystemIsolationUnavailable)
        );
        assert_eq!(request.env, original_env);
        assert_eq!((home.exists(), marker.exists()), (false, false));
    }
    Ok(())
}
