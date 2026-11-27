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
        (
            DenyAceKind::Write,
            (FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD) & !READ_CONTROL,
            true,
        ),
        (
            DenyAceKind::Write,
            (FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD) & !SYNCHRONIZE,
            true,
        ),
        (
            DenyAceKind::Write,
            (FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD) & !(READ_CONTROL | SYNCHRONIZE),
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
        let complete =
            unsafe { kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory) };
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
                !unsafe {
                    kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
                },
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
        assert!(!unsafe {
            kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
        });
    }
    Ok(())
}

#[test]
fn complete_file_denies_require_direct_scope() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-181-282-383-484")?;
    for kind in [DenyAceKind::Read, DenyAceKind::Write] {
        for flags in [
            0,
            OBJECT_INHERIT_ACE,
            CONTAINER_INHERIT_ACE,
            OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
            u32::from(INHERIT_ONLY_ACE),
            u32::from(INHERITED_ACE),
            NO_PROPAGATE_INHERIT_ACE,
        ] {
            let mut acl = NativeAcl::new()?;
            acl.deny(&sid, kind.mask(), flags)?;
            // SAFETY: the ACL and SID remain valid for the complete query.
            let complete =
                unsafe { kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::File) };
            assert_eq!(complete, flags == 0, "flags={flags:#x}");
        }
    }
    Ok(())
}

fn native_deny_entries(path: &Path, sid: &LocalSid) -> Result<Vec<(u8, u32)>> {
    // SAFETY: the existing path is live; this function owns the returned descriptor.
    let (dacl, descriptor) = unsafe { fetch_dacl_handle(path)? };
    let result = (|| {
        let mut entries = Vec::new();
        let mut info: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
        // SAFETY: the descriptor retains the ACL; info is writable and correctly sized.
        if unsafe {
            GetAclInformation(
                dacl,
                (&mut info as *mut ACL_SIZE_INFORMATION).cast(),
                std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            )
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        for index in 0..info.AceCount {
            let mut ace = std::ptr::null_mut();
            // SAFETY: the descriptor retains each ACE returned by the ACL query.
            if unsafe { GetAce(dacl, index, &mut ace) } == 0 {
                return Err(std::io::Error::last_os_error().into());
            }
            // SAFETY: GetAce returned a live native ACE header.
            let header = unsafe { &*(ace as *const ACE_HEADER) };
            if header.AceType == ACCESS_DENIED_ACE_TYPE {
                // SAFETY: the native header identifies an ACCESS_DENIED_ACE.
                let deny = unsafe { &*(ace as *const ACCESS_DENIED_ACE) };
                let trustee = std::ptr::addr_of!(deny.SidStart).cast_mut().cast();
                // SAFETY: both SIDs are valid and live throughout the comparison.
                if unsafe { EqualSid(trustee, sid.as_ptr()) } != 0 {
                    entries.push((header.AceFlags, deny.Mask));
                }
            }
        }
        Ok(entries)
    })();
    // SAFETY: no ACL or ACE reference escapes the closure; release the owned descriptor.
    unsafe { LocalFree(descriptor as HLOCAL) };
    result
}

#[test]
fn native_file_and_directory_denies_retain_full_masks_and_are_idempotent() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let sid = LocalSid::from_string("S-1-5-21-191-292-393-494")?;
    for (kind, name, expected_mask) in [
        (DenyAceKind::Read, "read", FILE_GENERIC_READ),
        (
            DenyAceKind::Write,
            "write",
            FILE_WRITE_DATA
                | FILE_APPEND_DATA
                | FILE_WRITE_EA
                | FILE_WRITE_ATTRIBUTES
                | DELETE
                | FILE_DELETE_CHILD,
        ),
    ] {
        for directory in [false, true] {
            let path = fixture.path().join(format!("{name}-{directory}"));
            let expected_flags = if directory {
                std::fs::create_dir(&path)?;
                (OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE) as u8
            } else {
                std::fs::write(&path, "preserved")?;
                0
            };
            // SAFETY: the native fixture object and validated SID remain live.
            let first = unsafe { add_deny_ace(&path, sid.as_ptr(), kind)? };
            let after_first = native_deny_entries(&path, &sid)?;
            // SAFETY: repeat the repair against the same existing native object.
            let second = unsafe { add_deny_ace(&path, sid.as_ptr(), kind)? };
            let after_second = native_deny_entries(&path, &sid)?;
            assert_eq!(
                (first, second, after_first, after_second),
                (
                    true,
                    false,
                    vec![(expected_flags, expected_mask)],
                    vec![(expected_flags, expected_mask)],
                )
            );
        }
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

#[test]
fn normalized_deny_pair_requires_every_right_in_effective_and_recursive_scopes() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-181-282-383-484")?;
    let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE | u32::from(INHERIT_ONLY_ACE);
    for (kind, mapped) in [
        (DenyAceKind::Read, FILE_GENERIC_READ),
        (
            DenyAceKind::Write,
            FILE_WRITE_DATA
                | FILE_APPEND_DATA
                | FILE_WRITE_EA
                | FILE_WRITE_ATTRIBUTES
                | DELETE
                | FILE_DELETE_CHILD,
        ),
    ] {
        let mut complete = NativeAcl::new()?;
        complete.deny(&sid, mapped, 0)?;
        complete.deny(&sid, kind.mask(), inheritance)?;
        assert!(unsafe {
            kind.already_present(complete.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
        });
        for bit in (0..32)
            .map(|index| 1_u32 << index)
            .filter(|bit| mapped & bit != 0)
        {
            for (effective, recursive) in [(mapped & !bit, mapped), (mapped, mapped & !bit)] {
                let mut incomplete = NativeAcl::new()?;
                incomplete.deny(&sid, effective, 0)?;
                incomplete.deny(&sid, recursive, inheritance)?;
                assert!(
                    !unsafe {
                        kind.already_present(
                            incomplete.as_ptr(),
                            sid.as_ptr(),
                            DenyAceScope::Directory,
                        )
                    },
                    "missing right {bit:#x}, effective={effective:#x}, recursive={recursive:#x}",
                );
            }
        }
    }
    Ok(())
}

#[test]
fn fresh_write_deny_preserves_generic_read_and_denies_data_mutation() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let path = fixture.path().join("readable.txt");
    std::fs::write(&path, "readable")?;
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .open(&path)?;
    // SAFETY: the existing path supplies a descriptor owned by the restore guard.
    let (dacl, descriptor) = unsafe { fetch_dacl_handle(&path)? };
    let restore = RestoreDacl {
        file,
        dacl,
        descriptor,
    };
    let everyone = LocalSid::from_string("S-1-1-0")?;
    // SAFETY: the owned fixture and validated SID remain live; restoration uses
    // the writable handle retained before the deny was added.
    let repaired = unsafe { add_deny_write_ace(&path, everyone.as_ptr())? };
    let readable = (|| -> std::io::Result<String> {
        let mut contents = String::new();
        OpenOptions::new()
            .access_mode(FILE_GENERIC_READ)
            .open(&path)?
            .read_to_string(&mut contents)?;
        Ok(contents)
    })()
    .map_err(|error| error.kind());
    let denied = [
        FILE_WRITE_DATA,
        FILE_APPEND_DATA,
        FILE_WRITE_EA,
        FILE_WRITE_ATTRIBUTES,
    ]
    .map(|access| {
        OpenOptions::new()
            .access_mode(access | SYNCHRONIZE)
            .open(&path)
            .map(drop)
            .err()
            .map(|error| error.kind())
    });
    drop(restore);
    assert_eq!(
        (repaired, readable, denied),
        (
            true,
            Ok("readable".to_string()),
            [Some(std::io::ErrorKind::PermissionDenied); 4],
        ),
    );
    Ok(())
}

#[test]
fn normalized_deny_pair_cannot_combine_wrong_identity_or_nonrecursive_scope() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-191-292-393-494")?;
    let other = LocalSid::from_string("S-1-5-21-192-293-394-495")?;
    let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
    for kind in [DenyAceKind::Read, DenyAceKind::Write] {
        for (recursive_sid, flags) in [
            (&other, inheritance | u32::from(INHERIT_ONLY_ACE)),
            (&sid, OBJECT_INHERIT_ACE | u32::from(INHERIT_ONLY_ACE)),
            (&sid, CONTAINER_INHERIT_ACE | u32::from(INHERIT_ONLY_ACE)),
            (
                &sid,
                inheritance | u32::from(INHERIT_ONLY_ACE) | NO_PROPAGATE_INHERIT_ACE,
            ),
            (
                &sid,
                inheritance | u32::from(INHERIT_ONLY_ACE) | u32::from(INHERITED_ACE),
            ),
        ] {
            let mut acl = NativeAcl::new()?;
            acl.deny(&sid, kind.mask(), 0)?;
            acl.deny(recursive_sid, kind.mask(), flags)?;
            assert!(!unsafe {
                kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
            });
        }
        let mut acl = NativeAcl::new()?;
        acl.deny(&sid, kind.mask(), 0)?;
        if unsafe {
            AddAccessAllowedAceEx(acl.as_ptr(), ACL_REVISION, 0, FILE_ALL_ACCESS, sid.as_ptr())
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        acl.deny(&sid, kind.mask(), inheritance | u32::from(INHERIT_ONLY_ACE))?;
        assert!(!unsafe {
            kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
        });
    }
    Ok(())
}

fn actual_dacl_bytes(path: &Path) -> Result<Vec<u8>> {
    // SAFETY: the descriptor owns all ACL bytes until the copy is complete.
    unsafe {
        let (dacl, descriptor) = fetch_dacl_handle(path)?;
        let bytes = if dacl.is_null() {
            Vec::new()
        } else {
            std::slice::from_raw_parts(dacl.cast::<u8>(), usize::from((*dacl).AclSize)).to_vec()
        };
        if !descriptor.is_null() {
            LocalFree(descriptor as HLOCAL);
        }
        Ok(bytes)
    }
}

#[test]
fn native_normalized_directory_and_file_denies_repeat_without_any_acl_change() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-201-302-403-504")?;
    for kind in [DenyAceKind::Read, DenyAceKind::Write] {
        let fixture = tempfile::tempdir()?;
        let directory = fixture.path().join("directory");
        std::fs::create_dir(&directory)?;
        let file = directory.join("file.txt");
        std::fs::write(&file, b"retain exact data")?;
        for path in [&directory, &file] {
            // SAFETY: the live, deliberately unassigned SID cannot deny this
            // test owner's cleanup. Each existing target has the original DACL.
            assert!(unsafe { deny::add_deny_ace(path, sid.as_ptr(), kind)? });
            let after_first = actual_dacl_bytes(path)?;
            assert!(!unsafe { deny::add_deny_ace(path, sid.as_ptr(), kind)? });
            assert_eq!(actual_dacl_bytes(path)?, after_first);
        }
        assert_eq!(std::fs::read(file)?, b"retain exact data");
    }
    Ok(())
}

#[test]
fn acl_repair_rejects_replaced_path_with_different_object_type() -> Result<()> {
    for original_is_directory in [false, true] {
        let fixture = tempfile::tempdir()?;
        let path = fixture.path().join("target");
        let moved = fixture.path().join("held-original");
        if original_is_directory {
            std::fs::create_dir(&path)?;
        } else {
            std::fs::write(&path, b"original data")?;
        }
        let pinned = File::options()
            .access_mode(READ_CONTROL)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
            .open(&path)?;
        let original_dacl = actual_dacl_bytes(&path)?;
        // Ordinary file and directory handles can establish the same identity.
        drop(deny::open_acl_repair_handle(&pinned, &path)?);
        std::fs::rename(&path, &moved)?;
        if original_is_directory {
            std::fs::write(&path, b"replacement data")?;
        } else {
            std::fs::create_dir(&path)?;
        }
        let replacement_dacl = actual_dacl_bytes(&path)?;
        let error = deny::open_acl_repair_handle(&pinned, &path)
            .expect_err("replacement must not receive an ACL repair for the held object");
        assert_eq!(
            error.to_string(),
            format!("ACL repair target changed for {}", path.display()),
        );
        assert_eq!(
            (actual_dacl_bytes(&moved)?, actual_dacl_bytes(&path)?),
            (original_dacl, replacement_dacl),
        );
        let (data_path, expected) = if original_is_directory {
            (&path, b"replacement data".as_slice())
        } else {
            (&moved, b"original data".as_slice())
        };
        assert_eq!(std::fs::read(data_path)?, expected);
    }
    Ok(())
}

#[test]
fn complete_denies_skip_inherited_partial_denies_before_explicit_full_denies() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-171-272-373-474")?;
    for scope in [DenyAceScope::Directory, DenyAceScope::File] {
        let inheritance = scope.inheritance();
        for (kind, partial_mask) in [
            (DenyAceKind::Read, FILE_READ_EA),
            (DenyAceKind::Write, DELETE),
        ] {
            let mut acl = NativeAcl::new()?;
            acl.deny(&sid, partial_mask, inheritance | u32::from(INHERITED_ACE))?;
            acl.deny(&sid, kind.mask(), inheritance)?;
            // SAFETY: the ACL and SID remain valid through the query.
            assert!(unsafe { kind.already_present(acl.as_ptr(), sid.as_ptr(), scope) });
        }
    }
    Ok(())
}

#[test]
fn complete_denies_fail_closed_after_inherited_partial_denies() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-181-282-383-484")?;
    for scope in [DenyAceScope::Directory, DenyAceScope::File] {
        let inheritance = scope.inheritance();
        for (kind, partial_mask) in [
            (DenyAceKind::Read, FILE_READ_EA),
            (DenyAceKind::Write, DELETE),
        ] {
            let mut partial_acl = NativeAcl::new()?;
            partial_acl.deny(&sid, partial_mask, inheritance | u32::from(INHERITED_ACE))?;
            partial_acl.deny(&sid, partial_mask, inheritance)?;
            // SAFETY: the ACL and SID remain valid through the query.
            assert!(!unsafe { kind.already_present(partial_acl.as_ptr(), sid.as_ptr(), scope) });

            let mut allow_acl = NativeAcl::new()?;
            allow_acl.deny(&sid, partial_mask, inheritance | u32::from(INHERITED_ACE))?;
            // SAFETY: append into the initialized ACL using the live SID. This
            // inherited deny followed by an allow must not be bypassed by a later deny.
            if unsafe {
                AddAccessAllowedAceEx(
                    allow_acl.as_ptr(),
                    ACL_REVISION,
                    inheritance,
                    FILE_ALL_ACCESS,
                    sid.as_ptr(),
                )
            } == 0
            {
                return Err(std::io::Error::last_os_error().into());
            }
            allow_acl.deny(&sid, kind.mask(), inheritance)?;
            // SAFETY: the ACL and SID remain valid through the query.
            assert!(!unsafe { kind.already_present(allow_acl.as_ptr(), sid.as_ptr(), scope) });
        }
    }
    Ok(())
}

#[test]
fn complete_denies_accept_native_effective_and_inherit_only_components() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-171-272-373-474")?;
    let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
    for kind in [DenyAceKind::Read, DenyAceKind::Write] {
        let mut acl = NativeAcl::new()?;
        acl.deny(&sid, kind.mask(), /*flags*/ 0)?;
        // SAFETY: the initialized ACL and validated SID stay live for each query.
        assert!(!unsafe {
            kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
        });
        acl.deny(&sid, kind.mask(), inheritance | u32::from(INHERIT_ONLY_ACE))?;
        // SAFETY: Windows' separate effective and recursive components together
        // cover this object and both kinds of descendants.
        assert!(unsafe {
            kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
        });
    }
    Ok(())
}

#[test]
fn complete_denies_do_not_borrow_missing_scope_from_another_sid() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-181-282-383-484")?;
    let other = LocalSid::from_string("S-1-5-21-191-292-393-494")?;
    let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
    for kind in [DenyAceKind::Read, DenyAceKind::Write] {
        for flags in [
            OBJECT_INHERIT_ACE | u32::from(INHERIT_ONLY_ACE),
            CONTAINER_INHERIT_ACE | u32::from(INHERIT_ONLY_ACE),
            inheritance | u32::from(INHERIT_ONLY_ACE) | NO_PROPAGATE_INHERIT_ACE,
        ] {
            let mut acl = NativeAcl::new()?;
            acl.deny(&sid, kind.mask(), /*flags*/ 0)?;
            acl.deny(&sid, kind.mask(), flags)?;
            acl.deny(&other, kind.mask(), inheritance)?;
            // SAFETY: all native objects remain live; another SID's complete
            // deny cannot supply the queried SID's missing recursive scope.
            assert!(!unsafe {
                kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
            });
        }
    }
    Ok(())
}

#[test]
fn complete_denies_require_all_rights_in_each_split_scope() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-201-302-403-504")?;
    let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
    for (effective, descendants) in [
        (FILE_GENERIC_WRITE, DenyAceKind::Write.mask()),
        (DenyAceKind::Write.mask(), FILE_GENERIC_WRITE),
    ] {
        let mut acl = NativeAcl::new()?;
        acl.deny(&sid, effective, /*flags*/ 0)?;
        acl.deny(&sid, descendants, inheritance | u32::from(INHERIT_ONLY_ACE))?;
        // SAFETY: valid native inputs; complete rights in only one component
        // must not hide missing DELETE/DELETE_CHILD in the other component.
        assert!(!unsafe {
            DenyAceKind::Write.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::Directory)
        });
    }
    Ok(())
}

#[test]
fn complete_file_denies_need_effective_rights_but_no_inheritance() -> Result<()> {
    let sid = LocalSid::from_string("S-1-5-21-211-312-413-514")?;
    let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
    for kind in [DenyAceKind::Read, DenyAceKind::Write] {
        for (flags, expected) in [
            (0, true),
            (inheritance | u32::from(INHERIT_ONLY_ACE), false),
            (u32::from(INHERITED_ACE), false),
        ] {
            let mut acl = NativeAcl::new()?;
            acl.deny(&sid, kind.mask(), flags)?;
            // SAFETY: native ACL and SID remain valid. An inherited deny is
            // not a substitute for the explicit repair owned by this function.
            let complete =
                unsafe { kind.already_present(acl.as_ptr(), sid.as_ptr(), DenyAceScope::File) };
            assert_eq!(complete, expected, "flags={flags:#x}");
        }
    }
    Ok(())
}
