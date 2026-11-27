use super::AuthorizedReadOnlySandboxFixture;
use super::authorized_elevated_fixture;
use super::collect_stdout_and_exit;
use super::current_thread_runtime;
use super::elevated_process_test_guard;
use super::spawn_windows_sandbox_session_elevated_for_permission_profile;
use super::workspace_roots_for;
use crate::ElevatedSandboxProfileCaptureRequest;
use crate::hosted_credential_lifetime::HostedCredentialCase;
use crate::run_windows_sandbox_capture_for_permission_profile_elevated;
use crate::token::LocalSid;
use crate::winutil::to_wide;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::ffi::c_void;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::marker::PhantomData;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::PathBuf;
use std::ptr;
use std::rc::Rc;
use std::time::Duration;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
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
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::DISABLE_MAX_PRIVILEGE;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TOKEN_DUPLICATE;
use windows_sys::Win32::Security::TOKEN_IMPERSONATE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;
use windows_sys::Win32::System::Threading::SetThreadToken;

struct PrivilegeRestrictedCaller {
    previous_token: Option<OwnedHandle>,
    // The guard must restore the same thread on which it entered impersonation.
    _same_thread: PhantomData<Rc<()>>,
}

impl PrivilegeRestrictedCaller {
    fn enter() -> Self {
        let token_access = TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_IMPERSONATE;
        let mut token = 0;
        // SAFETY: the current-thread pseudo-handle is valid and token is writable.
        let previous_token = if unsafe {
            OpenThreadToken(
                GetCurrentThread(),
                token_access,
                /*openasself*/ 1,
                &mut token,
            )
        } != 0
        {
            // SAFETY: successful OpenThreadToken returns an owned, valid handle.
            Some(unsafe { OwnedHandle::from_raw_handle(token as *mut c_void) })
        } else {
            assert_eq!(
                std::io::Error::last_os_error().raw_os_error(),
                Some(ERROR_NO_TOKEN as i32),
                "inspect caller thread token",
            );
            None
        };
        let process_token = if previous_token.is_none() {
            assert_ne!(
                // SAFETY: the process pseudo-handle is valid and token is writable.
                unsafe { OpenProcessToken(GetCurrentProcess(), token_access, &mut token) },
                0,
                "open caller process token: {}",
                std::io::Error::last_os_error(),
            );
            // SAFETY: successful OpenProcessToken returns an owned, valid handle.
            Some(unsafe { OwnedHandle::from_raw_handle(token as *mut c_void) })
        } else {
            None
        };
        let mut restricted_token = 0;
        assert_ne!(
            // SAFETY: a retained OwnedHandle keeps token valid with TOKEN_DUPLICATE;
            // all null arrays have zero counts and the output pointer is writable.
            unsafe {
                CreateRestrictedToken(
                    token,
                    DISABLE_MAX_PRIVILEGE,
                    /*disablesidcount*/ 0,
                    ptr::null(),
                    /*deleteprivilegecount*/ 0,
                    ptr::null(),
                    /*restrictedsidcount*/ 0,
                    ptr::null(),
                    &mut restricted_token,
                )
            },
            0,
            "remove caller privileges: {}",
            std::io::Error::last_os_error(),
        );
        // SAFETY: successful CreateRestrictedToken transfers this new handle to us.
        let restricted_token =
            unsafe { OwnedHandle::from_raw_handle(restricted_token as *mut c_void) };
        assert_ne!(
            // SAFETY: the live token has QUERY/DUPLICATE/IMPERSONATE access;
            // Windows retains its own reference after successful impersonation.
            unsafe { ImpersonateLoggedOnUser(restricted_token.as_raw_handle() as HANDLE) },
            0,
            "impersonate caller without privileges: {}",
            std::io::Error::last_os_error(),
        );
        drop(process_token);
        Self {
            previous_token,
            _same_thread: PhantomData,
        }
    }
}

impl Drop for PrivilegeRestrictedCaller {
    fn drop(&mut self) {
        // SAFETY: this non-Send guard runs on the entering thread, and any previous
        // impersonation token remains owned here with TOKEN_IMPERSONATE access.
        let restored = unsafe {
            match &self.previous_token {
                Some(token) => SetThreadToken(ptr::null(), token.as_raw_handle() as HANDLE),
                None => RevertToSelf(),
            }
        };
        if restored == 0 {
            // A reused test thread must never continue under the fixture token.
            std::process::abort();
        }
    }
}

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
    // Restore the actual ACL before shared policy handoff and owned data cleanup.
    _acl_restore: DaclRestore,
    _codex_home: HostedCredentialCase,
    _test_root: AuthorizedReadOnlySandboxFixture,
    workspace: PathBuf,
    codex_home: PathBuf,
    protected_file: AbsolutePathBuf,
    marker: PathBuf,
}

impl AclSetupFailureFixture {
    fn new(test_name: &str) -> Self {
        let test_root = authorized_elevated_fixture();
        let private_home = HostedCredentialCase::new(test_name, test_root.path())
            .expect("join original owned credential run and case lease");
        let workspace = test_root.path().join("workspace");
        fs::create_dir(&workspace).expect("create workspace");
        let codex_home = private_home.path().to_path_buf();
        let protected_path = test_root.path().join("protected.txt");
        fs::write(&protected_path, "protected").expect("seed protected file");
        // Establish the real private-account route before installing the ACL
        // refusal. A preflight failure cannot masquerade as the tested rejection.
        let profile = PermissionProfile::workspace_write();
        let roots = workspace_roots_for(&workspace);
        let healthy = run_windows_sandbox_capture_for_permission_profile_elevated(
            ElevatedSandboxProfileCaptureRequest {
                permission_profile: &profile,
                workspace_roots: &roots,
                codex_home: &codex_home,
                command: vec![
                    "C:\\Windows\\System32\\cmd.exe".to_string(),
                    "/d".to_string(),
                    "/c".to_string(),
                    "echo private-route-ready".to_string(),
                ],
                cwd: &workspace,
                env_map: HashMap::from([
                    ("TEMP".to_string(), workspace.display().to_string()),
                    ("TMP".to_string(), workspace.display().to_string()),
                ]),
                timeout_ms: Some(5_000),
                cancellation: None,
                use_private_desktop: true,
                proxy_enforced: false,
                network_proxy_restricting_sid: None,
                read_roots_override: None,
                read_roots_include_platform_defaults: false,
                write_roots_override: None,
                deny_read_paths_override: &[],
                deny_write_paths_override: &[],
            },
        )
        .expect("healthy elevated route before ACL refusal");
        assert_eq!((healthy.exit_code, healthy.timed_out), (0, false));
        assert!(String::from_utf8_lossy(&healthy.stdout).contains("private-route-ready"));
        assert!(
            crate::setup_error::read_setup_error_report(&codex_home)
                .expect("inspect helper report after healthy route")
                .is_none(),
            "the negative control must start with no previous helper failure report",
        );
        assert!(
            !workspace
                .join("process-started.txt")
                .try_exists()
                .expect("inspect initial process marker")
        );
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
        // SAFETY: the restoration handle and allocated DACL remain live through
        // both calls; the pathname buffer lives for its complete API call.
        let (result, named_result) = unsafe {
            let result = SetSecurityInfo(
                acl_restore.file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                updated_dacl,
                ptr::null_mut(),
            );
            // Exercise the same pathname-based native API as sandbox setup.
            // Reapplying this DACL cannot expand access on unexpected success.
            let named_result = (result == ERROR_SUCCESS).then(|| {
                SetNamedSecurityInfoW(
                    to_wide(&protected_path).as_ptr() as *mut u16,
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION,
                    ptr::null_mut(),
                    ptr::null_mut(),
                    updated_dacl,
                    ptr::null_mut(),
                )
            });
            LocalFree(updated_dacl as HLOCAL);
            (result, named_result)
        };
        assert_eq!(result, ERROR_SUCCESS, "install fixture ACL");
        assert_eq!(
            named_result,
            Some(ERROR_ACCESS_DENIED),
            "fixture must reject the named ACL setter before testing spawn",
        );
        let write_dac_error = match OpenOptions::new()
            .access_mode(WRITE_DAC)
            .custom_flags(windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS)
            .open(&protected_path)
        {
            Ok(_) => None,
            Err(error) => error.raw_os_error(),
        };
        assert_eq!(
            write_dac_error,
            Some(ERROR_ACCESS_DENIED as i32),
            "fixture must deny a fresh WRITE_DAC handle",
        );

        Self {
            _acl_restore: acl_restore,
            _codex_home: private_home,
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
        let chain = format!("{error:#}");
        let report = crate::setup_error::read_setup_error_report(&self.codex_home)
            .expect("read original helper failure report")
            .expect("failed real helper must retain its structured report");
        let expected_path = format!("deny ACE failed on {}", self.protected_file.display());
        for evidence in [&chain, &report.message] {
            assert!(
                evidence.contains("setup refresh"),
                "wrong failure phase: {evidence}"
            );
            assert!(
                evidence.contains(&expected_path),
                "wrong failed object: {evidence}"
            );
            assert!(
                evidence.contains("(os error 5)"),
                "native WRITE_DAC denial missing: {evidence}"
            );
        }
        assert_eq!(
            self.marker.try_exists().expect("inspect process marker"),
            false
        );
        assert_eq!(
            fs::read_to_string(self.protected_file.as_path()).expect("read protected file"),
            "protected"
        );
    }

    fn finish(self) {
        let Self {
            _acl_restore,
            mut _codex_home,
            _test_root,
            ..
        } = self;
        drop(_acl_restore);
        _codex_home
            .prepare_handoff()
            .expect("archive original helper report and reset owned shared policy");
        _test_root.close().expect("close owned ACL refusal fixture");
        _codex_home
            .finish()
            .expect("retain case completion awaiting original outer native terminal");
    }
}

#[test]
fn elevated_session_rejects_deny_acl_setup_failure_before_spawn() {
    let _guard = elevated_process_test_guard();
    // Construct and probe under the process primary identity first. Command::new
    // does not pass this later thread impersonation token to the refresh helper.
    let fixture = AclSetupFailureFixture::new(
        "unified_exec::tests::acl_setup_tests::elevated_session_rejects_deny_acl_setup_failure_before_spawn",
    );
    let caller = PrivilegeRestrictedCaller::enter();
    current_thread_runtime().block_on(async {
        let result = spawn_windows_sandbox_session_elevated_for_permission_profile(
            &PermissionProfile::workspace_write(),
            &workspace_roots_for(&fixture.workspace),
            &fixture.codex_home,
            AclSetupFailureFixture::command(),
            &fixture.workspace,
            fixture.env(),
            false,
            None,
            Some(5_000),
            None,
            false,
            None,
            &[],
            std::slice::from_ref(&fixture.protected_file),
            false,
            false,
            true,
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
    drop(caller);
    fixture.finish();
}

#[test]
fn elevated_capture_rejects_deny_acl_setup_failure_before_spawn() {
    let _guard = elevated_process_test_guard();
    let fixture = AclSetupFailureFixture::new(
        "unified_exec::tests::acl_setup_tests::elevated_capture_rejects_deny_acl_setup_failure_before_spawn",
    );
    let caller = PrivilegeRestrictedCaller::enter();
    let result = run_windows_sandbox_capture_for_permission_profile_elevated(
        ElevatedSandboxProfileCaptureRequest {
            permission_profile: &PermissionProfile::workspace_write(),
            workspace_roots: &workspace_roots_for(&fixture.workspace),
            codex_home: &fixture.codex_home,
            command: AclSetupFailureFixture::command(),
            cwd: &fixture.workspace,
            env_map: fixture.env(),
            timeout_ms: Some(5_000),
            cancellation: None,
            use_private_desktop: true,
            proxy_enforced: false,
            network_proxy_restricting_sid: None,
            read_roots_override: None,
            read_roots_include_platform_defaults: false,
            write_roots_override: None,
            deny_read_paths_override: &[],
            deny_write_paths_override: std::slice::from_ref(&fixture.protected_file),
        },
    );
    fixture.assert_rejected(
        result
            .map(|_| ())
            .expect_err("ACL setup failure must prevent capture spawn"),
    );
    drop(caller);
    fixture.finish();
}
