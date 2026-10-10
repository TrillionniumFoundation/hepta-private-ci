use super::*;
use crate::token::LocalSid;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::AddAccessAllowedAceEx;
use windows_sys::Win32::Security::AddAccessDeniedAceEx;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::NO_PROPAGATE_INHERIT_ACE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_EA;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

struct NativeAcl(Vec<u32>);

impl NativeAcl {
    fn new() -> Result<Self> {
        let mut acl = Self(vec![0; 128]);
        // SAFETY: the u32 buffer is DWORD-aligned and owns all writable ACL bytes.
        if unsafe {
            InitializeAcl(
                acl.as_ptr(),
                (acl.0.len() * std::mem::size_of::<u32>()) as u32,
                ACL_REVISION,
            )
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(acl)
    }

    fn as_ptr(&mut self) -> *mut ACL {
        self.0.as_mut_ptr().cast()
    }

    fn deny(&mut self, sid: &LocalSid, mask: u32, flags: u32) -> Result<()> {
        // SAFETY: the initialized ACL and validated SID remain live for the call.
        if unsafe { AddAccessDeniedAceEx(self.as_ptr(), ACL_REVISION, flags, mask, sid.as_ptr()) }
            == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(())
    }
}

#[test]
fn complete_denies_compare_mapped_masks_and_require_every_right() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-151-252-353-454")?;
    let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
    for (kind, mask, expected) in [
        (
            DenyAceKind::Write,
            GENERIC_WRITE_MASK | DELETE | FILE_DELETE_CHILD,
            true,
        ),
        (
            DenyAceKind::Write,
            FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD,
            true,
        ),
        (DenyAceKind::Write, FILE_GENERIC_WRITE, false),
        (DenyAceKind::Write, FILE_GENERIC_READ, false),
        (DenyAceKind::Write, DELETE, false),
        (DenyAceKind::Read, GENERIC_READ_MASK, true),
        (DenyAceKind::Read, FILE_GENERIC_READ, true),
        (DenyAceKind::Read, FILE_GENERIC_WRITE, false),
        (DenyAceKind::Read, FILE_READ_EA, false),
    ] {
        let mut acl = NativeAcl::new()?;
        acl.deny(&sid, mask, inheritance)?;
        // SAFETY: both arguments point into live, initialized native objects.
        let complete = unsafe { kind.already_present(acl.as_ptr(), sid.as_ptr()) };
        assert_eq!(complete, expected, "mask={mask:#x}");
    }
    Ok(())
}

#[test]
fn complete_denies_require_effective_recursive_scope_and_precede_allows() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-161-262-363-464")?;
    let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
    for kind in [DenyAceKind::Read, DenyAceKind::Write] {
        for flags in [
            0,
            OBJECT_INHERIT_ACE,
            CONTAINER_INHERIT_ACE,
            inheritance | u32::from(INHERIT_ONLY_ACE),
            inheritance | u32::from(INHERITED_ACE),
            inheritance | NO_PROPAGATE_INHERIT_ACE,
        ] {
            let mut acl = NativeAcl::new()?;
            acl.deny(&sid, kind.mask(), flags)?;
            // SAFETY: the ACL and SID are valid and retained for this query.
            assert!(
                !unsafe { kind.already_present(acl.as_ptr(), sid.as_ptr()) },
                "flags={flags:#x}",
            );
        }
        let mut acl = NativeAcl::new()?;
        // SAFETY: append into the initialized ACL using the live SID. This
        // deliberately noncanonical order must not make a later deny sufficient.
        if unsafe {
            AddAccessAllowedAceEx(
                acl.as_ptr(),
                ACL_REVISION,
                inheritance,
                FILE_ALL_ACCESS,
                sid.as_ptr(),
            )
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        acl.deny(&sid, kind.mask(), inheritance)?;
        // SAFETY: the ACL and SID remain valid through the query.
        assert!(!unsafe { kind.already_present(acl.as_ptr(), sid.as_ptr()) });
    }
    Ok(())
}

struct RestoreDacl {
    file: File,
    dacl: *mut ACL,
    descriptor: *mut c_void,
}

impl Drop for RestoreDacl {
    fn drop(&mut self) {
        // SAFETY: the handle retained WRITE_DAC before denial, and descriptor
        // owns dacl until LocalFree after SetSecurityInfo finishes copying it.
        let result = unsafe {
            let result = SetSecurityInfo(
                self.file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                self.dacl,
                std::ptr::null_mut(),
            );
            LocalFree(self.descriptor as HLOCAL);
            result
        };
        assert_eq!(result, ERROR_SUCCESS, "restore native read-denial fixture");
    }
}

#[test]
fn partial_read_deny_is_repaired_before_native_file_data_access() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let path = fixture.path().join("read.txt");
    std::fs::write(&path, "readable")?;
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .open(&path)?;
    // SAFETY: path exists; the returned descriptor is owned by the restore guard.
    let (dacl, descriptor) = unsafe { fetch_dacl_handle(&path)? };
    let restore = RestoreDacl {
        file,
        dacl,
        descriptor,
    };
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: FILE_READ_EA,
        grfAccessMode: DENY_ACCESS,
        grfInheritance: OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: everyone.as_ptr().cast(),
        },
    };
    let mut partial_dacl = std::ptr::null_mut();
    // SAFETY: all ACL/SID pointers and the writable output remain live. The
    // resulting allocation is freed after the setter copies the ACL.
    let code = unsafe {
        let code = SetEntriesInAclW(
            /*ccountofexplicitentries*/ 1,
            &entry,
            restore.dacl,
            &mut partial_dacl,
        );
        let code = if code == ERROR_SUCCESS {
            SetSecurityInfo(
                restore.file.as_raw_handle() as HANDLE,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                partial_dacl,
                std::ptr::null_mut(),
            )
        } else {
            code
        };
        if !partial_dacl.is_null() {
            LocalFree(partial_dacl as HLOCAL);
        }
        code
    };
    acl_api_result(&path, "seed partial read deny", code)?;
    let mut before = String::new();
    OpenOptions::new()
        .access_mode(FILE_READ_DATA | SYNCHRONIZE)
        .open(&path)?
        .read_to_string(&mut before)?;
    assert_eq!(before, "readable");
    // SAFETY: the existing fixture path and validated Everyone SID are live.
    let repaired = unsafe { add_deny_read_ace(&path, everyone.as_ptr())? };
    let denied = OpenOptions::new()
        .access_mode(FILE_READ_DATA | SYNCHRONIZE)
        .open(&path)
        .err()
        .map(|error| error.kind());
    assert_eq!(
        (repaired, denied),
        (true, Some(std::io::ErrorKind::PermissionDenied)),
    );
    drop(restore);
    assert_eq!(std::fs::read_to_string(&path)?, "readable");
    Ok(())
}

#[test]
fn deny_ace_update_failure_is_an_error() {
    let path = std::path::Path::new(r"C:\world-writable");
    let error = acl_api_result(path, "SetNamedSecurityInfoW", ERROR_ACCESS_DENIED)
        .expect_err("access denied must not look like an already-present ACE");

    assert_eq!(
        error.to_string(),
        r"SetNamedSecurityInfoW failed for C:\world-writable: 5"
    );
}
