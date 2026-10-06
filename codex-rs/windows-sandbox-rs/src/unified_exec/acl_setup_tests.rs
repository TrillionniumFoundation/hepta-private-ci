// Direct legacy launches now fail before ACL setup; lower-level ACL authority tests remain below.
use super::collect_stdout_and_exit;
use super::current_thread_runtime;
use super::legacy_process_test_guard;
use super::sandbox_cwd;
use super::workspace_roots_for;
use crate::token::LocalSid;
use crate::unified_exec::backends::legacy::spawn_windows_sandbox_session_legacy;
use crate::windows_impl::run_windows_sandbox_capture_legacy;
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
use std::path::Path;
use std::path::PathBuf;
use std::ptr;
use std::rc::Rc;
use std::time::Duration;
use tempfile::TempDir;
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
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::DISABLE_MAX_PRIVILEGE;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TOKEN_DUPLICATE;
use windows_sys::Win32::Security::TOKEN_IMPERSONATE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_EA;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::SECURITY_IDENTIFICATION;
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

struct DaclSnapshot {
    dacl: *mut ACL,
    descriptor: *mut c_void,
}

impl DaclSnapshot {
    fn read(file: &File) -> Self {
        let mut dacl = ptr::null_mut();
        let mut descriptor = ptr::null_mut();
        // SAFETY: the retained file and both output pointers are valid.
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
            ERROR_SUCCESS
        );
        assert!(!dacl.is_null() && !descriptor.is_null());
        Self { dacl, descriptor }
    }

    fn bytes(&self) -> Vec<u8> {
        // SAFETY: GetSecurityInfo owns this initialized ACL in descriptor.
        unsafe { std::slice::from_raw_parts(self.dacl.cast::<u8>(), (*self.dacl).AclSize as usize) }
            .to_vec()
    }
}

impl Drop for DaclSnapshot {
    fn drop(&mut self) {
        // SAFETY: no ACL pointer escapes the descriptor's lifetime.
        unsafe { LocalFree(self.descriptor as HLOCAL) };
    }
}

struct DaclRestore {
    file: File,
    original: DaclSnapshot,
}

impl Drop for DaclRestore {
    fn drop(&mut self) {
        // This handle acquired WRITE_DAC before the fixture denied it. Restoring
        // through a newly opened handle would fail for the same reason as setup.
        let result = unsafe {
            SetSecurityInfo(
                self.file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                self.original.dacl,
                ptr::null_mut(),
            )
        };
        if result != ERROR_SUCCESS {
            eprintln!("failed to restore ACL failure fixture: {result}");
            assert!(std::thread::panicking(), "fixture ACL restoration failed");
        }
    }
}

#[derive(Clone, Copy)]
enum FixtureObject {
    File,
    Directory,
}

impl FixtureObject {
    fn inheritance(self) -> u32 {
        match self {
            Self::File => 0,
            Self::Directory => OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
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
    denied_dacl: Vec<u8>,
    object: FixtureObject,
}

impl AclSetupFailureFixture {
    fn new(object: FixtureObject) -> Self {
        let test_root = TempDir::new_in(sandbox_cwd()).expect("create ACL failure test root");
        let workspace = test_root.path().join("workspace");
        fs::create_dir(&workspace).expect("create workspace");
        let codex_home = test_root.path().join("codex-home");
        let protected_path = test_root.path().join("protected.txt");
        match object {
            FixtureObject::File => {
                fs::write(&protected_path, "protected").expect("seed protected file")
            }
            FixtureObject::Directory => {
                fs::create_dir(&protected_path).expect("seed protected directory")
            }
        }
        let file = OpenOptions::new()
            .access_mode(READ_CONTROL | FILE_READ_ATTRIBUTES | WRITE_DAC)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
            .open(&protected_path)
            .expect("retain handle for restoring fixture ACL");
        let original = DaclSnapshot::read(&file);
        let acl_restore = DaclRestore { file, original };

        // OWNER RIGHTS removes implicit READ_CONTROL as well as WRITE_DAC.
        // Keep explicit inspection grants and prove read access below. Everyone
        // blocks write-DAC grants from user/group SIDs; data/delete rights and
        // parent ACLs are unchanged.
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
                    acl_restore.original.dacl,
                    &mut updated_dacl,
                )
            },
            ERROR_SUCCESS,
            "build fixture ACL that rejects setup",
        );
        // SAFETY: the restoration handle and allocated DACL remain live through
        // the setter. The returned allocation is freed after the call.
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
        let denied_dacl = DaclSnapshot::read(&acl_restore.file).bytes();
        let fixture = Self {
            _acl_restore: acl_restore,
            marker: workspace.join("process-started.txt"),
            _test_root: test_root,
            workspace,
            codex_home,
            protected_file: AbsolutePathBuf::from_absolute_path(protected_path)
                .expect("absolute protected file"),
            denied_dacl,
            object,
        };
        fixture.assert_write_denied_but_readable();
        fixture
    }

    fn assert_write_denied_but_readable(&self) {
        let open = |access| {
            OpenOptions::new()
                .access_mode(access)
                .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
                .security_qos_flags(SECURITY_IDENTIFICATION)
                .open(self.protected_file.as_path())
        };
        // The exact production mask must be denied; a pre-granted restoration
        // handle or an unrelated ReOpenFile error cannot establish this fact.
        assert_eq!(
            open(READ_CONTROL | FILE_READ_ATTRIBUTES | WRITE_DAC)
                .err()
                .and_then(|error| error.raw_os_error()),
            Some(ERROR_ACCESS_DENIED as i32)
        );
        let readable =
            open(READ_CONTROL | FILE_READ_ATTRIBUTES).expect("inspection remains allowed");
        readable.metadata().expect("metadata remains readable");
        assert_eq!(DaclSnapshot::read(&readable).bytes(), self.dacl_bytes());
    }

    fn dacl_bytes(&self) -> Vec<u8> {
        DaclSnapshot::read(&self._acl_restore.file).bytes()
    }

    fn seed_target_deny(&self, sid: &LocalSid, mask: u32) {
        let current = DaclSnapshot::read(&self._acl_restore.file);
        let entry = EXPLICIT_ACCESS_W {
            grfAccessPermissions: mask,
            grfAccessMode: DENY_ACCESS,
            grfInheritance: self.object.inheritance(),
            Trustee: TRUSTEE_W {
                pMultipleTrustee: ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: sid.as_ptr().cast(),
            },
        };
        let mut updated = ptr::null_mut();
        // SAFETY: descriptors and SID remain live; the setter uses authority
        // retained before denial solely to prepare this native test fixture.
        assert_eq!(
            unsafe { SetEntriesInAclW(1, &entry, current.dacl, &mut updated) },
            ERROR_SUCCESS
        );
        let result = unsafe {
            let result = SetSecurityInfo(
                self._acl_restore.file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                updated,
                ptr::null_mut(),
            );
            LocalFree(updated as HLOCAL);
            result
        };
        assert_eq!(result, ERROR_SUCCESS);
        self.assert_write_denied_but_readable();
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

    fn assert_contained(&self, error: anyhow::Error) {
        assert_eq!(
            (
                error.to_string(),
                error
                    .root_cause()
                    .downcast_ref::<std::io::Error>()
                    .and_then(std::io::Error::raw_os_error),
                self.marker.try_exists().expect("inspect process marker"),
                self.codex_home.try_exists().expect("inspect helper home"),
                self.dacl_bytes()
            ),
            (
                crate::WINDOWS_LEGACY_CONTAINMENT_ERROR.to_string(),
                None,
                false,
                false,
                self.denied_dacl.clone()
            ),
        );
    }
}

#[test]
fn legacy_session_is_contained_before_deny_acl_setup() {
    let _guard = legacy_process_test_guard();
    // Keep privilege removal local to this thread, including the native setup
    // calls in the current-thread runtime. The process token remains unchanged.
    let _caller = PrivilegeRestrictedCaller::enter();
    current_thread_runtime().block_on(async {
        let fixture = AclSetupFailureFixture::new(FixtureObject::File);
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
        fixture.assert_contained(
            result.expect_err("containment must prevent session setup and spawn"),
        );
    });
}

#[test]
fn legacy_capture_is_contained_before_deny_acl_setup() {
    let _guard = legacy_process_test_guard();
    let _caller = PrivilegeRestrictedCaller::enter();
    let fixture = AclSetupFailureFixture::new(FixtureObject::File);
    let result = run_windows_sandbox_capture_legacy(
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
    fixture.assert_contained(
        result
            .map(|_| ())
            .expect_err("containment must prevent capture setup and spawn"),
    );
}

#[derive(Clone, Copy)]
enum FixtureDeny {
    Read,
    Write,
}

impl FixtureDeny {
    fn mask(self) -> u32 {
        match self {
            Self::Read => FILE_GENERIC_READ,
            Self::Write => FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD,
        }
    }

    fn partial_mask(self) -> u32 {
        match self {
            Self::Read => FILE_READ_EA,
            Self::Write => FILE_WRITE_DATA,
        }
    }

    fn apply(self, path: &Path, sid: &LocalSid) -> anyhow::Result<bool> {
        // SAFETY: caller-owned fixtures exist and LocalSid owns the valid SID.
        unsafe {
            match self {
                Self::Read => crate::acl::add_deny_read_ace(path, sid.as_ptr()),
                Self::Write => crate::acl::add_deny_write_ace(path, sid.as_ptr()),
            }
        }
    }
}

#[test]
fn complete_denies_are_unchanged_when_write_dac_is_denied() -> anyhow::Result<()> {
    let _caller = PrivilegeRestrictedCaller::enter();
    let sid = LocalSid::from_string("S-1-5-21-211-322-433-544")?;
    for object in [FixtureObject::File, FixtureObject::Directory] {
        for kind in [FixtureDeny::Read, FixtureDeny::Write] {
            let fixture = AclSetupFailureFixture::new(object);
            fixture.seed_target_deny(&sid, kind.mask());
            let before = fixture.dacl_bytes();
            assert_eq!(
                (
                    kind.apply(fixture.protected_file.as_path(), &sid)?,
                    kind.apply(fixture.protected_file.as_path(), &sid)?
                ),
                (false, false)
            );
            assert_eq!(
                before,
                fixture.dacl_bytes(),
                "complete deny must not be rewritten"
            );
        }
    }
    Ok(())
}

#[test]
fn incomplete_denies_preserve_original_write_denial_and_acl() -> anyhow::Result<()> {
    let _caller = PrivilegeRestrictedCaller::enter();
    let sid = LocalSid::from_string("S-1-5-21-221-332-443-554")?;
    for object in [FixtureObject::File, FixtureObject::Directory] {
        for kind in [FixtureDeny::Read, FixtureDeny::Write] {
            let fixture = AclSetupFailureFixture::new(object);
            fixture.seed_target_deny(&sid, kind.partial_mask());
            let before = fixture.dacl_bytes();
            let error = kind
                .apply(fixture.protected_file.as_path(), &sid)
                .expect_err("repair needs authority");
            assert_eq!(
                error
                    .root_cause()
                    .downcast_ref::<std::io::Error>()
                    .and_then(std::io::Error::raw_os_error),
                Some(ERROR_ACCESS_DENIED as i32)
            );
            assert_eq!(
                before,
                fixture.dacl_bytes(),
                "denied repair must not modify the ACL"
            );
            assert!(!fixture.marker.try_exists()?);
        }
    }
    Ok(())
}
