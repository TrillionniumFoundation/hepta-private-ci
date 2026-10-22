use super::LocalSid;
use super::create_workspace_write_token_with_caps_from;
use super::get_current_token_for_restriction;
use crate::winutil::to_wide;
use anyhow::Context;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::ffi::c_void;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::DuplicateToken;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GROUP_SECURITY_INFORMATION;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PRIVILEGE_SET;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;

type NativeError = (io::ErrorKind, Option<i32>);
type NativeOutcome<T> = std::result::Result<T, NativeError>;
type AccessOutcome = NativeOutcome<(bool, u32)>;

fn native_error(error: io::Error) -> NativeError {
    (error.kind(), error.raw_os_error())
}

struct LocalAllocation(*mut c_void);

impl Drop for LocalAllocation {
    fn drop(&mut self) {
        // SAFETY: this allocation is owned and no pointers into it remain live.
        unsafe { LocalFree(self.0 as HLOCAL) };
    }
}

fn set_exact_dacl(path: &Path, grants: &[(&LocalSid, u32)]) -> Result<()> {
    let entries: Vec<_> = grants
        .iter()
        .map(|(sid, mask)| EXPLICIT_ACCESS_W {
            grfAccessPermissions: *mask,
            grfAccessMode: GRANT_ACCESS,
            grfInheritance: 0,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: std::ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: sid.as_ptr().cast(),
            },
        })
        .collect();
    let mut acl = std::ptr::null_mut();
    // SAFETY: each SID and entry remains live; a null old ACL prevents any
    // ambient ACE from being copied into these deliberately separate grants.
    let status = unsafe {
        SetEntriesInAclW(
            entries.len() as u32,
            entries.as_ptr(),
            std::ptr::null_mut(),
            &mut acl,
        )
    };
    let acl = LocalAllocation(acl.cast());
    if status != ERROR_SUCCESS {
        return Err(io::Error::from_raw_os_error(status as i32).into());
    }
    // SAFETY: the test owns the existing path and ACL. Protected, non-inheriting
    // DACLs keep parent DELETE_CHILD separate from DELETE on each child.
    let status = unsafe {
        SetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            acl.0.cast(),
            std::ptr::null_mut(),
        )
    };
    if status != ERROR_SUCCESS {
        return Err(io::Error::from_raw_os_error(status as i32).into());
    }
    Ok(())
}

fn descriptor(path: &Path) -> Result<LocalAllocation> {
    let mut descriptor = std::ptr::null_mut();
    // SAFETY: the existing test path is owned; AccessCheck requires both owner
    // and group, in addition to the DACL actually stored by the filesystem.
    let status = unsafe {
        GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    let descriptor = LocalAllocation(descriptor);
    if status != ERROR_SUCCESS {
        return Err(io::Error::from_raw_os_error(status as i32).into());
    }
    Ok(descriptor)
}

fn impersonation_token(token: HANDLE) -> Result<OwnedHandle> {
    let mut duplicate = 0;
    // SAFETY: token is retained and supports duplication. DuplicateToken returns
    // the impersonation token with TOKEN_QUERY required by AccessCheck.
    if unsafe { DuplicateToken(token, SecurityImpersonation, &mut duplicate) } == 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: successful duplication returned a fresh, uniquely owned handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(duplicate as *mut c_void) })
}

fn check_access(descriptor: &LocalAllocation, token: &OwnedHandle, desired: u32) -> AccessOutcome {
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut privilege_bytes = std::mem::size_of::<PRIVILEGE_SET>() as u32;
    let mut privileges = vec![0_u32; privilege_bytes as usize / std::mem::size_of::<u32>()];
    loop {
        let mut granted = 0;
        let mut allowed = 0;
        // SAFETY: the descriptor and impersonation token are retained. The
        // DWORD buffer is aligned for PRIVILEGE_SET; desired has no generic bits.
        let succeeded = unsafe {
            AccessCheck(
                descriptor.0,
                token.as_raw_handle() as HANDLE,
                desired,
                &mapping,
                privileges.as_mut_ptr().cast(),
                &mut privilege_bytes,
                &mut granted,
                &mut allowed,
            )
        };
        if succeeded != 0 {
            return Ok((allowed != 0, granted));
        }
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(ERROR_INSUFFICIENT_BUFFER as i32)
            || privilege_bytes as usize <= privileges.len() * std::mem::size_of::<u32>()
        {
            return Err(native_error(error));
        }
        privileges.resize(
            (privilege_bytes as usize).div_ceil(std::mem::size_of::<u32>()),
            /*value*/ 0,
        );
    }
}

struct Impersonation;

impl Drop for Impersonation {
    fn drop(&mut self) {
        // SAFETY: this guard is created only after successful impersonation.
        if unsafe { RevertToSelf() } == 0 {
            // Never return an impersonating thread to the shared test harness.
            std::process::abort();
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum DeleteAuthority {
    Object,
    Parent,
}

#[derive(Debug, PartialEq)]
struct AccessObservation {
    read: AccessOutcome,
    write: AccessOutcome,
    file_delete: AccessOutcome,
    directory_delete: AccessOutcome,
    parent_delete_child: AccessOutcome,
}

#[derive(Debug, PartialEq)]
struct StateObservation {
    read_write_contents: NativeOutcome<String>,
    created_exists: NativeOutcome<bool>,
    delete_file_exists: NativeOutcome<bool>,
    delete_dir_exists: NativeOutcome<bool>,
}

#[derive(Debug, PartialEq)]
struct Observation {
    location: &'static str,
    authority: DeleteAuthority,
    restricted: bool,
    access: AccessObservation,
    read: NativeOutcome<String>,
    mutations: [NativeOutcome<()>; 4],
    after: StateObservation,
}

#[test]
fn workspace_delete_checks_object_and_parent_authority_separately() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let workspace_cap = LocalSid::from_string("S-1-5-21-201-302-403-504")?;
    let temp_cap = LocalSid::from_string("S-1-5-21-211-312-413-514")?;
    // SAFETY: each newly created handle is immediately placed under sole ownership.
    let base = unsafe {
        OwnedHandle::from_raw_handle(get_current_token_for_restriction()? as *mut c_void)
    };
    let restricted = unsafe {
        OwnedHandle::from_raw_handle(create_workspace_write_token_with_caps_from(
            base.as_raw_handle() as HANDLE,
            &[workspace_cap.as_ptr(), temp_cap.as_ptr()],
        )? as *mut c_void)
    };
    let ordinary = impersonation_token(base.as_raw_handle() as HANDLE)?;
    let confined = impersonation_token(restricted.as_raw_handle() as HANDLE)?;
    let readable_writable = FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE;
    let mut observed = Vec::new();
    let mut expected = Vec::new();
    for (location, capability) in [
        ("outside", None),
        ("workspace", Some(&workspace_cap)),
        ("temp", Some(&temp_cap)),
    ] {
        for authority in [DeleteAuthority::Object, DeleteAuthority::Parent] {
            for (restricted, token) in [(false, &ordinary), (true, &confined)] {
                let root = fixture
                    .path()
                    .join(format!("{location}-{authority:?}-{restricted}"));
                std::fs::create_dir(&root)?;
                let read_write = root.join("read-write.txt");
                let delete_file = root.join("delete.txt");
                let delete_dir = root.join("delete-dir");
                let created = root.join("created.txt");
                std::fs::write(&read_write, "original")?;
                std::fs::write(&delete_file, "delete")?;
                std::fs::create_dir(&delete_dir)?;
                let (parent_delete, object_delete) = match authority {
                    DeleteAuthority::Object => (0, DELETE),
                    DeleteAuthority::Parent => (FILE_DELETE_CHILD, 0),
                };
                let mut parent_grants = vec![(&everyone, readable_writable | parent_delete)];
                let mut object_grants = vec![(&everyone, readable_writable | object_delete)];
                if let Some(capability) = capability {
                    parent_grants.push((capability, readable_writable | parent_delete));
                    object_grants.push((capability, readable_writable | object_delete));
                }
                set_exact_dacl(&root, &parent_grants).context("set isolated parent DACL")?;
                for path in [&read_write, &delete_file, &delete_dir] {
                    set_exact_dacl(path, &object_grants).context("set isolated object DACL")?;
                }
                let parent_descriptor = descriptor(&root)?;
                let object_descriptor = descriptor(&delete_file)?;
                let directory_descriptor = descriptor(&delete_dir)?;
                let access = AccessObservation {
                    read: check_access(&object_descriptor, token, FILE_READ_DATA),
                    write: check_access(&object_descriptor, token, FILE_WRITE_DATA),
                    file_delete: check_access(&object_descriptor, token, DELETE),
                    directory_delete: check_access(&directory_descriptor, token, DELETE),
                    parent_delete_child: check_access(&parent_descriptor, token, FILE_DELETE_CHILD),
                };
                // SAFETY: the owned impersonation token stays live until the
                // guard reverts, including if a filesystem operation fails.
                if unsafe { ImpersonateLoggedOnUser(token.as_raw_handle() as HANDLE) } == 0 {
                    return Err(io::Error::last_os_error().into());
                }
                let (read, mutations) = {
                    let _impersonation = Impersonation;
                    let read = std::fs::read_to_string(&read_write).map_err(native_error);
                    let mutations = [
                        std::fs::write(&read_write, "overwritten"),
                        std::fs::write(&created, "created"),
                        std::fs::remove_file(&delete_file),
                        std::fs::remove_dir(&delete_dir),
                    ]
                    .map(|result| result.map_err(native_error));
                    (read, mutations)
                };
                observed.push(Observation {
                    location,
                    authority,
                    restricted,
                    access,
                    read,
                    mutations,
                    after: StateObservation {
                        read_write_contents: std::fs::read_to_string(&read_write)
                            .map_err(native_error),
                        created_exists: created.try_exists().map_err(native_error),
                        delete_file_exists: delete_file.try_exists().map_err(native_error),
                        delete_dir_exists: delete_dir.try_exists().map_err(native_error),
                    },
                });
                let writable = !restricted || capability.is_some();
                let file_delete = writable && object_delete != 0;
                let parent_delete_child = writable && parent_delete != 0;
                let expected_access = AccessObservation {
                    read: Ok((true, FILE_READ_DATA)),
                    write: Ok((writable, if writable { FILE_WRITE_DATA } else { 0 })),
                    file_delete: Ok((file_delete, if file_delete { DELETE } else { 0 })),
                    directory_delete: Ok((file_delete, if file_delete { DELETE } else { 0 })),
                    parent_delete_child: Ok((
                        parent_delete_child,
                        if parent_delete_child {
                            FILE_DELETE_CHILD
                        } else {
                            0
                        },
                    )),
                };
                expected.push(Observation {
                    location,
                    authority,
                    restricted,
                    access: expected_access,
                    read: Ok("original".to_owned()),
                    mutations: if writable {
                        [Ok(()); 4]
                    } else {
                        [Err((io::ErrorKind::PermissionDenied, Some(5))); 4]
                    },
                    after: StateObservation {
                        read_write_contents: Ok(
                            if writable { "overwritten" } else { "original" }.to_owned()
                        ),
                        created_exists: Ok(writable),
                        delete_file_exists: Ok(!writable),
                        delete_dir_exists: Ok(!writable),
                    },
                });
            }
        }
    }
    // Collect both permission routes, both token controls, and both allowed
    // roots before asserting. A successful outside delete always fails here.
    assert_eq!(observed, expected);
    Ok(())
}
