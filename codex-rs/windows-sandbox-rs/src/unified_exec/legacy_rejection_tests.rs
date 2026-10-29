use super::current_thread_runtime;
use super::sandbox_process_test_guard;
use super::spawn_windows_sandbox_session_legacy;
use super::workspace_roots_for;
use crate::acl::fetch_dacl_handle;
use crate::run_windows_sandbox_capture;
use crate::run_windows_sandbox_capture_with_filesystem_overrides;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::ffi::c_void;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::GetAce;

struct SecurityDescriptor(*mut c_void);

impl Drop for SecurityDescriptor {
    fn drop(&mut self) {
        // SAFETY: fetch_dacl_handle transfers this LocalAlloc descriptor to us.
        unsafe { LocalFree(self.0 as HLOCAL) };
    }
}

pub(super) type NativeDacl = Option<(u8, Vec<Vec<u8>>)>;

pub(super) fn native_dacl(path: &Path) -> NativeDacl {
    // SAFETY: the existing fixture path is queried read-only; the guard retains
    // the returned descriptor and all ACE memory until it has been copied.
    let (dacl, descriptor) = unsafe { fetch_dacl_handle(path) }.expect("read fixture DACL");
    let _descriptor = SecurityDescriptor(descriptor);
    if dacl.is_null() {
        return None;
    }
    // Compare the stored ACE order, flags, access masks and SIDs, excluding ACL
    // allocation slack which is not part of the access policy.
    let mut entries = Vec::new();
    // SAFETY: GetSecurityInfo returned a valid ACL owned by the retained guard.
    let (revision, ace_count) = unsafe { ((*dacl).AclRevision, (*dacl).AceCount) };
    for index in 0..u32::from(ace_count) {
        let mut ace = std::ptr::null_mut();
        // SAFETY: the ACL is live and index is below the native ACE count.
        assert_ne!(unsafe { GetAce(dacl, index, &mut ace) }, 0, "read ACE");
        // SAFETY: a successful GetAce returns a complete ACE including its header.
        let bytes = unsafe {
            std::slice::from_raw_parts(
                ace.cast::<u8>(),
                usize::from((*ace.cast::<ACE_HEADER>()).AceSize),
            )
        };
        entries.push(bytes.to_vec());
    }
    Some((revision, entries))
}

struct RejectedLaunch {
    _root: TempDir,
    workspace: PathBuf,
    codex_home: PathBuf,
    outside_file: PathBuf,
    marker: PathBuf,
    before: Vec<(PathBuf, NativeDacl)>,
}

impl RejectedLaunch {
    fn new() -> Self {
        let root = TempDir::new().expect("create rejection fixture");
        let workspace = root.path().join("workspace");
        let outside = root.path().join("outside");
        fs::create_dir(&workspace).expect("create workspace");
        fs::create_dir(&outside).expect("create outside directory");
        let outside_file = outside.join("keep.txt");
        fs::write(&outside_file, "preserved").expect("seed outside file");
        let before = [root.path(), &workspace, &outside, &outside_file]
            .into_iter()
            .map(|path| (path.to_path_buf(), native_dacl(path)))
            .collect();
        Self {
            codex_home: root.path().join("uncreated-codex-home"),
            marker: workspace.join("child-started"),
            _root: root,
            workspace,
            outside_file,
            before,
        }
    }

    fn command(&self) -> Vec<String> {
        vec![
            "C:\\Windows\\System32\\cmd.exe".to_string(),
            "/d".to_string(),
            "/c".to_string(),
            "echo started>\"%SPAWN_MARKER%\" & del /f /q \"%OUTSIDE_FILE%\"".to_string(),
        ]
    }

    fn env(&self) -> HashMap<String, String> {
        HashMap::from([
            ("TEMP".to_string(), self.workspace.display().to_string()),
            ("TMP".to_string(), self.workspace.display().to_string()),
            (
                "SPAWN_MARKER".to_string(),
                self.marker.display().to_string(),
            ),
            (
                "OUTSIDE_FILE".to_string(),
                self.outside_file.display().to_string(),
            ),
        ])
    }

    fn assert_rejected(&self, error: anyhow::Error) {
        assert_eq!(
            error.to_string(),
            "the legacy restricted-token Windows sandbox cannot enforce filesystem deletion boundaries; use the elevated Windows sandbox backend"
        );
        assert_eq!(
            (
                self.codex_home.try_exists().expect("inspect code home"),
                self.marker.try_exists().expect("inspect child marker"),
                fs::read_to_string(&self.outside_file).expect("outside file survives"),
            ),
            (false, false, "preserved".to_string()),
        );
        for (path, before) in &self.before {
            assert_eq!(
                &native_dacl(path),
                before,
                "DACL changed at {}",
                path.display()
            );
        }
    }
}

#[test]
fn direct_legacy_sessions_reject_before_child_home_or_acl_changes() {
    let _guard = sandbox_process_test_guard();
    current_thread_runtime().block_on(async {
        for permission_profile in [
            PermissionProfile::read_only(),
            PermissionProfile::workspace_write(),
        ] {
            for tty in [false, true] {
                let fixture = RejectedLaunch::new();
                let error = spawn_windows_sandbox_session_legacy(
                    &permission_profile,
                    &workspace_roots_for(&fixture.workspace),
                    &fixture.codex_home,
                    fixture.command(),
                    &fixture.workspace,
                    fixture.env(),
                    Some(5_000),
                    &[],
                    &[],
                    tty,
                    /*stdin_open*/ false,
                    /*use_private_desktop*/ true,
                )
                .await
                .expect_err("unsafe legacy session must be rejected");
                fixture.assert_rejected(error);
            }
        }
    });
}

#[test]
fn direct_legacy_capture_rejects_before_child_home_or_acl_changes() {
    let _guard = sandbox_process_test_guard();
    for permission_profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        for with_overrides in [false, true] {
            let fixture = RejectedLaunch::new();
            let result = if with_overrides {
                let deny_write = AbsolutePathBuf::from_absolute_path(&fixture.outside_file)
                    .expect("absolute deny-write path");
                run_windows_sandbox_capture_with_filesystem_overrides(
                    &permission_profile,
                    &workspace_roots_for(&fixture.workspace),
                    &fixture.codex_home,
                    fixture.command(),
                    &fixture.workspace,
                    fixture.env(),
                    Some(5_000),
                    /*cancellation*/ None,
                    &[],
                    std::slice::from_ref(&deny_write),
                    /*use_private_desktop*/ true,
                )
            } else {
                run_windows_sandbox_capture(
                    &permission_profile,
                    &workspace_roots_for(&fixture.workspace),
                    &fixture.codex_home,
                    fixture.command(),
                    &fixture.workspace,
                    fixture.env(),
                    Some(5_000),
                    /*cancellation*/ None,
                    /*use_private_desktop*/ true,
                )
            };
            fixture.assert_rejected(
                result
                    .map(|_| ())
                    .expect_err("unsafe legacy capture must be rejected"),
            );
        }
    }
}
