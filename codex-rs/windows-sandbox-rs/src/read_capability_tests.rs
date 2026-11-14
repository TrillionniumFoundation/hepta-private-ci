use super::WindowsSandboxReadScope;
use super::read_access_for_setup;
use super::read_cap_sid_for_root;
use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use crate::setup::SandboxSetupRequest;
use crate::setup::SetupRootOverrides;
use crate::token::LocalSid;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::path::PathBuf;

#[test]
fn only_an_unoverridden_full_read_profile_uses_normal_account_reads() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let env = std::collections::HashMap::new();
    let permissions =
        ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
            &codex_protocol::models::PermissionProfile::workspace_write(),
            &[codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(temporary.path())?],
        )?;
    let request = SandboxSetupRequest {
        permissions: &permissions,
        command_cwd: temporary.path(),
        env_map: &env,
        codex_home: temporary.path(),
        proxy_enforced: false,
    };
    let overrides = [
        SetupRootOverrides::default(),
        SetupRootOverrides {
            read_roots: Some(vec![temporary.path().to_path_buf()]),
            ..SetupRootOverrides::default()
        },
        SetupRootOverrides {
            deny_read_paths: Some(vec![temporary.path().join("private")]),
            ..SetupRootOverrides::default()
        },
    ];
    let actual = overrides
        .iter()
        .map(|overrides| {
            let plan = read_access_for_setup(&request, overrides)?;
            Ok((plan.scope, plan.capability_sids.is_empty()))
        })
        .collect::<Result<Vec<_>>>()?;
    assert_eq!(
        actual,
        vec![
            (WindowsSandboxReadScope::FullDisk, true),
            (WindowsSandboxReadScope::CapabilityRoots, false),
            (WindowsSandboxReadScope::CapabilityRoots, false),
        ]
    );
    Ok(())
}

#[test]
fn a_profile_with_only_named_read_roots_retains_capability_checks() -> Result<()> {
    use codex_protocol::models::ManagedFileSystemPermissions;
    use codex_protocol::models::PermissionProfile;
    use codex_protocol::permissions::FileSystemAccessMode;
    use codex_protocol::permissions::FileSystemPath;
    use codex_protocol::permissions::FileSystemSandboxEntry;
    use codex_protocol::permissions::NetworkSandboxPolicy;
    use codex_utils_absolute_path::AbsolutePathBuf;

    let temporary = tempfile::tempdir()?;
    let root = AbsolutePathBuf::from_absolute_path(temporary.path())?;
    let profile = PermissionProfile::Managed {
        file_system: ManagedFileSystemPermissions::Restricted {
            entries: vec![FileSystemSandboxEntry {
                path: FileSystemPath::Path { path: root.into() },
                access: FileSystemAccessMode::Write,
                missing_path_behavior: None,
            }],
            glob_scan_max_depth: None,
        },
        network: NetworkSandboxPolicy::Restricted,
    };
    let permissions = ResolvedWindowsSandboxPermissions::try_from_permission_profile(&profile)?;
    let env = std::collections::HashMap::new();
    let request = SandboxSetupRequest {
        permissions: &permissions,
        command_cwd: temporary.path(),
        env_map: &env,
        codex_home: temporary.path(),
        proxy_enforced: false,
    };
    let plan = read_access_for_setup(&request, &SetupRootOverrides::default())?;
    assert_eq!(
        (plan.scope, plan.capability_sids.is_empty()),
        (WindowsSandboxReadScope::CapabilityRoots, false)
    );
    Ok(())
}

#[test]
fn canonical_read_roots_share_only_their_own_capability() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let first = temp.path().join("ReadRoot");
    let second = temp.path().join("OtherRoot");
    std::fs::create_dir(&first)?;
    std::fs::create_dir(&second)?;
    let canonical = dunce::canonicalize(&first)?;
    let alias = PathBuf::from(
        canonical
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_uppercase(),
    );
    let first_sid = read_cap_sid_for_root(&first)?;
    let alias_sid = read_cap_sid_for_root(&alias)?;
    let second_sid = read_cap_sid_for_root(&second)?;
    LocalSid::from_string(&first_sid)?;
    LocalSid::from_string(&second_sid)?;
    assert_eq!(&first_sid, &alias_sid);
    assert_ne!(first_sid, second_sid);
    Ok(())
}
