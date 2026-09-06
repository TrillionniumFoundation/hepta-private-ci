use super::collect_stdout_and_exit;
use super::current_thread_runtime;
use super::legacy_process_test_guard;
use super::sandbox_cwd;
use super::spawn_windows_sandbox_session_legacy;
use super::workspace_roots_for;
use crate::run_windows_sandbox_capture_with_filesystem_overrides;
use crate::token::LocalSid;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::ffi::c_void;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::PathBuf;
use std::ptr;
use std::time::Duration;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::DENY_ACCESS;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

struct DaclRestore {
    file: File,
    dacl: *mut ACL,
    descriptor: *mut c_void,
}

impl Drop for DaclRestore {
    fn drop(&mut self) {
        // This handle acquired WRITE_DAC before the fixture denied it. Restoring
        // through a newly opened handle would fail for the same reason as setup.
        let result = unsafe {
            let result = SetSecurityInfo(
                self.file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                self.dacl,
                ptr::null_mut(),
            );
            LocalFree(self.descriptor as HLOCAL);
            result
        };
        if result != ERROR_SUCCESS {
            eprintln!("failed to restore ACL failure fixture: {result}");
            assert!(std::thread::panicking(), "fixture ACL restoration failed");
        }
    }
}

struct AclSetupFailureFixture {
    // Restore the ACL before TempDir tries to remove the fixture.
    _acl_restore: DaclRestore,
    _test_root: TempDir,
    workspace: PathBuf,
    codex_home: PathBuf,
    protected_file: AbsolutePathBuf,
    marker: PathBuf,
}

impl AclSetupFailureFixture {
    fn new() -> Self {
        let test_root = TempDir::new_in(sandbox_cwd()).expect("create ACL failure test root");
        let workspace = test_root.path().join("workspace");
        fs::create_dir(&workspace).expect("create workspace");
        let codex_home = test_root.path().join("codex-home");
        let protected_path = test_root.path().join("protected.txt");
        fs::write(&protected_path, "protected").expect("seed protected file");
        let file = OpenOptions::new()
            .access_mode(READ_CONTROL | WRITE_DAC)
            .open(&protected_path)
            .expect("retain handle for restoring fixture ACL");
        let mut dacl = ptr::null_mut();
        let mut descriptor = ptr::null_mut();
        assert_eq!(
            unsafe {
                GetSecurityInfo(
                    file.as_raw_handle() as HANDLE,
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION,
                    ptr::null_mut(),
                    ptr::null_mut(),
                    &mut dacl,
                    ptr::null_mut(),
                    &mut descriptor,
                )
            },
            ERROR_SUCCESS,
            "read original fixture ACL",
        );
        let acl_restore = DaclRestore {
            file,
            dacl,
            descriptor,
        };

        // OWNER RIGHTS removes the owner's implicit WRITE_DAC; Everyone also
        // blocks grants inherited through the runner's user or group SIDs.
        // No data access or delete rights are denied, and no parent ACL changes.
        let everyone = LocalSid::from_string("S-1-1-0").expect("Everyone SID");
        let owner_rights = LocalSid::from_string("S-1-3-4").expect("Owner Rights SID");
        let entries = [everyone.as_ptr(), owner_rights.as_ptr()].map(|sid| EXPLICIT_ACCESS_W {
            grfAccessPermissions: WRITE_DAC,
            grfAccessMode: DENY_ACCESS,
            grfInheritance: 0,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: sid as *mut u16,
            },
        });
        let mut updated_dacl = ptr::null_mut();
        assert_eq!(
            unsafe {
                SetEntriesInAclW(
                    entries.len() as u32,
                    entries.as_ptr(),
                    acl_restore.dacl,
                    &mut updated_dacl,
                )
            },
            ERROR_SUCCESS,
            "build fixture ACL that rejects setup",
        );
        let result = unsafe {
            let result = SetSecurityInfo(
                acl_restore.file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                updated_dacl,
                ptr::null_mut(),
            );
            LocalFree(updated_dacl as HLOCAL);
            result
        };
        assert_eq!(result, ERROR_SUCCESS, "install fixture ACL");

        Self {
            _acl_restore: acl_restore,
            marker: workspace.join("process-started.txt"),
            _test_root: test_root,
            workspace,
            codex_home,
            protected_file: AbsolutePathBuf::from_absolute_path(protected_path)
                .expect("absolute protected file"),
        }
    }

    fn command() -> Vec<String> {
        vec![
            "C:\\Windows\\System32\\cmd.exe".to_string(),
            "/d".to_string(),
            "/c".to_string(),
            "echo started>\"%SPAWN_MARKER%\"".to_string(),
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
        ])
    }

    fn assert_rejected(&self, error: anyhow::Error) {
        assert_eq!(
            (
                error.to_string(),
                error.root_cause().to_string(),
                self.marker.try_exists().expect("inspect process marker"),
            ),
            (
                format!(
                    "apply legacy deny-write ACL to {}",
                    self.protected_file.display()
                ),
                format!(
                    "SetNamedSecurityInfoW failed for {}: {ERROR_ACCESS_DENIED}",
                    self.protected_file.display(),
                ),
                false,
            ),
        );
    }
}

#[test]
fn legacy_session_rejects_deny_acl_setup_failure_before_spawn() {
    let _guard = legacy_process_test_guard();
    current_thread_runtime().block_on(async {
        let fixture = AclSetupFailureFixture::new();
        let result = spawn_windows_sandbox_session_legacy(
            &PermissionProfile::workspace_write(),
            &workspace_roots_for(&fixture.workspace),
            &fixture.codex_home,
            AclSetupFailureFixture::command(),
            &fixture.workspace,
            fixture.env(),
            Some(5_000),
            &[],
            std::slice::from_ref(&fixture.protected_file),
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await;
        let result = match result {
            Ok(spawned) => {
                collect_stdout_and_exit(spawned, &fixture.codex_home, Duration::from_secs(10))
                    .await;
                Ok(())
            }
            Err(error) => Err(error),
        };
        fixture.assert_rejected(result.expect_err("ACL setup failure must prevent session spawn"));
    });
}

#[test]
fn legacy_capture_rejects_deny_acl_setup_failure_before_spawn() {
    let _guard = legacy_process_test_guard();
    let fixture = AclSetupFailureFixture::new();
    let result = run_windows_sandbox_capture_with_filesystem_overrides(
        &PermissionProfile::workspace_write(),
        &workspace_roots_for(&fixture.workspace),
        &fixture.codex_home,
        AclSetupFailureFixture::command(),
        &fixture.workspace,
        fixture.env(),
        Some(5_000),
        /*cancellation*/ None,
        &[],
        std::slice::from_ref(&fixture.protected_file),
        /*use_private_desktop*/ true,
    );
    fixture.assert_rejected(
        result
            .map(|_| ())
            .expect_err("ACL setup failure must prevent capture spawn"),
    );
}
