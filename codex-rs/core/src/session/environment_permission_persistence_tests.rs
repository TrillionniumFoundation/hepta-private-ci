use crate::config::PermissionProfileSnapshot;
use crate::environment_selection::TurnEnvironmentState;
use crate::session::tests::make_session_and_context;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_protocol::permissions::FileSystemSpecialPath;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;

fn profile_with_workspace_carveout(access: FileSystemAccessMode) -> PermissionProfile {
    let base = PermissionProfile::workspace_write();
    let mut file_system = base.file_system_sandbox_policy();
    file_system.entries.push(FileSystemSandboxEntry::new(
        FileSystemPath::Special {
            value: FileSystemSpecialPath::ProjectRoots {
                subpath: Some("private".to_string()),
            },
        },
        access,
    ));
    PermissionProfile::from_runtime_permissions(&file_system, base.network_sandbox_policy())
}

async fn persist_profiles(
    cwd: PathUri,
    workspace_roots: Vec<PathUri>,
    profile: &PermissionProfile,
) -> (PermissionProfile, PermissionProfile) {
    let (session, mut turn_context) = make_session_and_context().await;
    let TurnEnvironmentState::Ready(environment) = &mut turn_context.environments.environments[0]
    else {
        panic!("ready primary environment");
    };
    environment.selection.cwd = cwd;
    environment.selection.workspace_roots = workspace_roots;
    environment.config_mut().permission_profile =
        PermissionProfileSnapshot::legacy(profile.clone());
    let selection = environment.selection.clone();
    let turn_profile = turn_context
        .to_turn_context_item()
        .permission_profile
        .expect("persisted turn profile");
    let mut state = session.state.lock().await;
    state
        .session_configuration
        .set_permission_profile_for_tests(profile.clone())
        .expect("test permission profile");
    let settings_profile = state
        .session_configuration
        .thread_settings_snapshot(&[selection])
        .permission_profile;
    let persisted =
        serde_json::to_vec(&(turn_profile, settings_profile)).expect("serialize profiles");
    serde_json::from_slice(&persisted).expect("reload profiles")
}

#[tokio::test]
async fn foreign_and_mixed_paths_preserve_distinct_configured_policies_in_both_snapshots() {
    let temp = tempfile::tempdir().expect("native workspace");
    let native = PathUri::from_host_native_path(temp.path()).expect("native cwd");
    let foreign = PathUri::parse(if cfg!(windows) {
        "file:///workspace"
    } else {
        "file:///C:/workspace"
    })
    .expect("foreign cwd");
    assert!(foreign.to_abs_path().is_err());
    let read = profile_with_workspace_carveout(FileSystemAccessMode::Read);
    let deny = profile_with_workspace_carveout(FileSystemAccessMode::Deny);
    assert_ne!(read, deny);
    for (cwd, roots) in [
        (foreign.clone(), vec![foreign.clone()]),
        (foreign.clone(), Vec::new()),
        (native.clone(), vec![native.clone(), foreign]),
    ] {
        for profile in [&read, &deny] {
            assert_eq!(
                persist_profiles(cwd.clone(), roots.clone(), profile).await,
                (profile.clone(), profile.clone()),
            );
        }
    }
}

#[tokio::test]
async fn native_paths_keep_materialized_policies_in_both_snapshots() {
    let temp = tempfile::tempdir().expect("native workspace");
    let cwd = PathUri::from_host_native_path(temp.path()).expect("native cwd");
    let profile = profile_with_workspace_carveout(FileSystemAccessMode::Read);
    for roots in [vec![cwd.clone()], Vec::new()] {
        let native_roots = roots
            .iter()
            .map(|root| root.to_abs_path().expect("native root"))
            .collect::<Vec<_>>();
        let expected = profile
            .clone()
            .materialize_project_roots_with_workspace_roots(&native_roots);
        assert_eq!(
            persist_profiles(cwd.clone(), roots, &profile).await,
            (expected.clone(), expected),
        );
    }
}
