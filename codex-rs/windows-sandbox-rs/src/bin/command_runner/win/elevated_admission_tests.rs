use super::spawn_ipc_process;
use anyhow::Result;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_windows_sandbox::ElevatedWindowsSandboxIsolationUnavailable;
use codex_windows_sandbox::SpawnRequest;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::fs;

#[test]
fn runner_refuses_before_profile_hiding_or_child_creation() -> Result<()> {
    let root = tempfile::tempdir()?;
    let workspace = root.path().join("workspace");
    fs::create_dir(&workspace)?;
    let kept = workspace.join("kept.txt");
    fs::write(&kept, b"unchanged")?;
    let marker = workspace.join("child-started.txt");
    let home = root.path().join("runner-home-must-not-be-created");
    let request = SpawnRequest {
        command: vec![
            "C:\\Windows\\System32\\cmd.exe".to_owned(),
            "/d".to_owned(),
            "/c".to_owned(),
            "echo started>\"%SPAWN_MARKER%\"".to_owned(),
        ],
        cwd: workspace.clone(),
        env: HashMap::from([("SPAWN_MARKER".to_owned(), marker.display().to_string())]),
        permission_profile: PermissionProfile::workspace_write(),
        workspace_roots: vec![AbsolutePathBuf::from_absolute_path(&workspace)?],
        codex_home: home.clone(),
        real_codex_home: home.clone(),
        cap_sids: vec!["S-1-5-21-101-202-303-404".to_owned()],
        network_proxy_restricting_sid: None,
        timeout_ms: Some(5_000),
        tty: false,
        stdin_open: false,
        use_private_desktop: true,
    };
    let error = match spawn_ipc_process(&request) {
        Err(error) => error,
        Ok(_) => panic!("native runner unexpectedly admitted an elevated child"),
    };
    assert!(
        error.is::<ElevatedWindowsSandboxIsolationUnavailable>(),
        "unexpected error: {error:#}"
    );
    assert_eq!(fs::read(&kept)?, b"unchanged");
    assert_eq!((home.try_exists()?, marker.try_exists()?), (false, false));
    assert_eq!(fs::read_dir(root.path())?.count(), 1);
    assert_eq!(fs::read_dir(&workspace)?.count(), 1);
    Ok(())
}
