//! Retained-handle private state primitives for Windows product owners.
//!
//! Callers keep policy and schema ownership. This module owns the Windows-only
//! filesystem facts: no followed reparse points, exact retained-directory
//! ancestry, one-link regular files, current-user ownership, no untrusted
//! effective write ACE, and write-through replacement.

use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::ffi::OsStringExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;

use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::AddAccessAllowedAceEx;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::IsWellKnownSid;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Security::WinBuiltinAdministratorsSid;
use windows_sys::Win32::Security::WinCreatorOwnerSid;
use windows_sys::Win32::Security::WinLocalSystemSid;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_APPEND_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_EA;
use windows_sys::Win32::Storage::FileSystem::GetFinalPathNameByHandleW;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
use windows_sys::Win32::Storage::FileSystem::MoveFileExW;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;

const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const ACCESS_DENIED_ACE_TYPE: u8 = 1;
const INHERIT_ONLY_ACE: u8 = 0x08;

/// Access mode for a private state child.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrivateFileAccess {
    /// Open an existing child for reads.
    Read,
    /// Open an existing child for retained-owner reads and writes.
    Write,
    /// Open or create a child for retained-owner reads and writes.
    Create,
}

/// Creates or opens a retained private-state directory.
pub fn open_private_state_directory(root: &Path) -> io::Result<File> {
    let created = match std::fs::create_dir(root) {
        Ok(()) => true,
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => false,
        Err(error) => return Err(error),
    };
    reject_reparse_ancestry(root)?;
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    if created {
        options.access_mode(FILE_GENERIC_READ | FILE_GENERIC_WRITE | WRITE_DAC);
    }
    let directory = options
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(root)?;
    if created {
        install_private_dacl(&directory)?;
    }
    validate_handle(&directory, HandleKind::Directory)?;
    Ok(directory)
}

fn install_private_dacl(directory: &File) -> io::Result<()> {
    let current_user = CurrentUser::read()?;
    let mut storage = private_dacl(&current_user)?;
    let dacl = storage.as_mut_ptr().cast::<ACL>();
    let status = unsafe {
        SetSecurityInfo(
            directory.as_raw_handle() as HANDLE,
            1, // SE_FILE_OBJECT
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            dacl,
            ptr::null_mut(),
        )
    };
    if status != ERROR_SUCCESS {
        return Err(io::Error::from_raw_os_error(status as i32));
    }
    Ok(())
}

fn private_dacl(current_user: &CurrentUser) -> io::Result<Vec<u32>> {
    let sid_length = unsafe { GetLengthSid(current_user.sid()) } as usize;
    if sid_length == 0 {
        return Err(io::Error::last_os_error());
    }
    let acl_bytes = std::mem::size_of::<ACL>() + std::mem::size_of::<ACCESS_ALLOWED_ACE>()
        - std::mem::size_of::<u32>()
        + sid_length;
    let mut storage = vec![0_u32; acl_bytes.div_ceil(std::mem::size_of::<u32>())];
    let dacl = storage.as_mut_ptr().cast::<ACL>();
    if unsafe { InitializeAcl(dacl, acl_bytes as u32, ACL_REVISION) } == 0 {
        return Err(io::Error::last_os_error());
    }
    if unsafe {
        AddAccessAllowedAceEx(
            dacl,
            ACL_REVISION,
            OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
            FILE_ALL_ACCESS,
            current_user.sid(),
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(storage)
}

/// Opens one normal-name child relative to the retained private directory.
pub fn open_private_state_child(
    directory: &File,
    name: &str,
    access: PrivateFileAccess,
) -> io::Result<File> {
    let path = child_path(directory, name)?;
    let mut options = OpenOptions::new();
    match access {
        PrivateFileAccess::Read => {
            options.read(true);
        }
        PrivateFileAccess::Write => {
            options.read(true).write(true);
        }
        PrivateFileAccess::Create => {
            options.read(true).write(true).create(true);
        }
    }
    let file = options
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&path)?;
    validate_handle(&file, HandleKind::File)?;
    let opened = final_path(&file)?;
    if opened.parent() != path.parent() || opened.file_name() != path.file_name() {
        return Err(unsafe_state("private child escaped its retained directory"));
    }
    Ok(file)
}

/// Checks for one valid private child without following a redirect.
pub fn private_state_child_exists(directory: &File, name: &str) -> io::Result<bool> {
    let path = child_path(directory, name)?;
    let mut options = OpenOptions::new();
    options
        .read(true)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    match options.open(path) {
        Ok(file) => {
            validate_handle(&file, HandleKind::File)?;
            Ok(true)
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

/// Atomically and durably replaces one validated private child with another.
pub fn replace_private_state_child(
    directory: &File,
    source_name: &str,
    destination_name: &str,
) -> io::Result<()> {
    let source = child_path(directory, source_name)?;
    let destination = child_path(directory, destination_name)?;
    validate_handle(
        &OpenOptions::new()
            .read(true)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&source)?,
        HandleKind::File,
    )?;
    if private_state_child_exists(directory, destination_name)? {
        validate_handle(
            &OpenOptions::new()
                .read(true)
                .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
                .open(&destination)?,
            HandleKind::File,
        )?;
    }
    let source = wide_path(&source);
    let destination = wide_path(&destination);
    let replaced = unsafe {
        MoveFileExW(
            source.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if replaced == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum HandleKind {
    Directory,
    File,
}

fn validate_handle(file: &File, kind: HandleKind) -> io::Result<()> {
    let information = winapi_util::file::information(file)?;
    let attributes = information.file_attributes();
    let is_directory = attributes & u64::from(FILE_ATTRIBUTE_DIRECTORY) != 0;
    if attributes & u64::from(FILE_ATTRIBUTE_REPARSE_POINT) != 0
        || is_directory != matches!(kind, HandleKind::Directory)
        || matches!(kind, HandleKind::File) && information.number_of_links() != 1
    {
        return Err(unsafe_state("private state handle type is unsafe"));
    }
    validate_private_owner_and_dacl(file)
}

fn validate_private_owner_and_dacl(file: &File) -> io::Result<()> {
    capture_private_security(file).map(|_| ())
}

#[derive(Debug, Eq, PartialEq)]
struct PrivateSecuritySnapshot {
    owner: Vec<u8>,
    dacl: Vec<u8>,
    control: u16,
}

fn capture_private_security(file: &File) -> io::Result<PrivateSecuritySnapshot> {
    let current_user = CurrentUser::read()?;
    let mut owner = ptr::null_mut();
    let mut dacl: *mut ACL = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1, // SE_FILE_OBJECT
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut owner,
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    if status != ERROR_SUCCESS || descriptor.is_null() || owner.is_null() || dacl.is_null() {
        if !descriptor.is_null() {
            unsafe { LocalFree(descriptor as HLOCAL) };
        }
        return Err(unsafe_state(
            "private state security descriptor is incomplete",
        ));
    }
    // Read and copy the same descriptor that was validated, before LocalFree.
    let result = (|| {
        let mut control = 0;
        let mut revision = 0;
        let mut information: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
        let valid = unsafe {
            IsValidSid(owner) != 0
                && IsValidAcl(dacl) != 0
                && EqualSid(owner, current_user.sid()) != 0
                && !dacl_grants_untrusted_access(dacl, current_user.sid())
                && GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) != 0
                && GetAclInformation(
                    dacl,
                    (&mut information as *mut ACL_SIZE_INFORMATION).cast(),
                    std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                    AclSizeInformation,
                ) != 0
        };
        if !valid {
            return Err(unsafe_state("private state owner or DACL is unsafe"));
        }
        Ok(PrivateSecuritySnapshot {
            owner: unsafe {
                std::slice::from_raw_parts(owner.cast::<u8>(), GetLengthSid(owner) as usize)
            }
            .to_vec(),
            dacl: unsafe {
                std::slice::from_raw_parts(dacl.cast::<u8>(), information.AclBytesInUse as usize)
            }
            .to_vec(),
            control,
        })
    })();
    unsafe { LocalFree(descriptor as HLOCAL) };
    result
}

unsafe fn dacl_grants_untrusted_access(dacl: *mut ACL, current_user: *mut c_void) -> bool {
    let mut information: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
    if unsafe {
        GetAclInformation(
            dacl as *const ACL,
            (&mut information as *mut ACL_SIZE_INFORMATION).cast(),
            std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
            AclSizeInformation,
        )
    } == 0
    {
        return true;
    }
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: u32::MAX,
    };
    let access_mask = FILE_GENERIC_READ
        | FILE_GENERIC_WRITE
        | FILE_GENERIC_EXECUTE
        | FILE_WRITE_DATA
        | FILE_APPEND_DATA
        | FILE_WRITE_EA
        | FILE_WRITE_ATTRIBUTES
        | FILE_DELETE_CHILD
        | DELETE
        | WRITE_DAC
        | WRITE_OWNER;
    for index in 0..information.AceCount {
        let mut ace = ptr::null_mut();
        if unsafe { GetAce(dacl as *const ACL, index, &mut ace) } == 0 {
            return true;
        }
        let header = unsafe { &*(ace as *const ACE_HEADER) };
        if header.AceType == ACCESS_DENIED_ACE_TYPE || header.AceFlags & INHERIT_ONLY_ACE != 0 {
            continue;
        }
        if header.AceType != ACCESS_ALLOWED_ACE_TYPE {
            return true;
        }
        let allowed = unsafe { &*(ace as *const ACCESS_ALLOWED_ACE) };
        let sid = (ace as usize + std::mem::size_of::<ACE_HEADER>() + std::mem::size_of::<u32>())
            as *mut c_void;
        let mut mask = allowed.Mask;
        unsafe { MapGenericMask(&mut mask, &mapping) };
        if mask & access_mask != 0 && !unsafe { trusted_access_sid(sid, current_user) } {
            return true;
        }
    }
    false
}

unsafe fn trusted_access_sid(sid: *mut c_void, current_user: *mut c_void) -> bool {
    unsafe {
        EqualSid(sid, current_user) != 0
            || IsWellKnownSid(sid, WinLocalSystemSid) != 0
            || IsWellKnownSid(sid, WinBuiltinAdministratorsSid) != 0
            || IsWellKnownSid(sid, WinCreatorOwnerSid) != 0
    }
}

fn child_path(directory: &File, name: &str) -> io::Result<PathBuf> {
    let path = Path::new(name);
    let mut components = path.components();
    if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
        return Err(unsafe_state("private child name is not a normal component"));
    }
    Ok(final_path(directory)?.join(path))
}

fn final_path(file: &File) -> io::Result<PathBuf> {
    let handle = file.as_raw_handle() as HANDLE;
    let length = unsafe { GetFinalPathNameByHandleW(handle, ptr::null_mut(), 0, 0) };
    if length == 0 {
        return Err(io::Error::last_os_error());
    }
    let mut buffer = vec![0_u16; length as usize + 1];
    let written =
        unsafe { GetFinalPathNameByHandleW(handle, buffer.as_mut_ptr(), buffer.len() as u32, 0) };
    if written == 0 || written as usize >= buffer.len() {
        return Err(io::Error::last_os_error());
    }
    Ok(std::ffi::OsString::from_wide(&buffer[..written as usize]).into())
}

fn reject_reparse_ancestry(path: &Path) -> io::Result<()> {
    use std::os::windows::fs::MetadataExt;

    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(unsafe_state(
                "private state ancestry contains a reparse point",
            ));
        }
    }
    Ok(())
}

fn wide_path(path: &Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;

    path.as_os_str().encode_wide().chain(Some(0)).collect()
}

fn unsafe_state(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

struct CurrentUser {
    token: HANDLE,
    buffer: Vec<u8>,
}

impl CurrentUser {
    fn read() -> io::Result<Self> {
        // Filesystem access would use the thread token, while this policy is
        // explicitly process-user-owned. Do not accidentally mix principals.
        let mut thread_token = 0;
        if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut thread_token) } != 0 {
            unsafe { CloseHandle(thread_token) };
            return Err(unsafe_state("private state does not support impersonation"));
        }
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(ERROR_NO_TOKEN as i32) {
            return Err(error);
        }
        let mut token = 0;
        if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut length = 0;
        unsafe {
            GetTokenInformation(token, TokenUser, ptr::null_mut(), 0, &mut length);
        }
        if length == 0 {
            unsafe { CloseHandle(token) };
            return Err(io::Error::last_os_error());
        }
        let mut buffer = vec![0_u8; length as usize];
        let ok = unsafe {
            GetTokenInformation(
                token,
                TokenUser,
                buffer.as_mut_ptr().cast(),
                length,
                &mut length,
            )
        };
        if ok == 0 {
            unsafe { CloseHandle(token) };
            return Err(io::Error::last_os_error());
        }
        Ok(Self { token, buffer })
    }

    fn sid(&self) -> *mut c_void {
        let user = unsafe { ptr::read_unaligned(self.buffer.as_ptr() as *const TOKEN_USER) };
        user.User.Sid
    }
}

impl Drop for CurrentUser {
    fn drop(&mut self) {
        if self.token != 0 {
            unsafe { CloseHandle(self.token) };
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows_sys::Win32::Security::CreateWellKnownSid;
    use windows_sys::Win32::Security::WinWorldSid;

    fn world_sid() -> Vec<u32> {
        let mut length = 0;
        unsafe {
            CreateWellKnownSid(WinWorldSid, ptr::null_mut(), ptr::null_mut(), &mut length);
        }
        assert!(length > 0);
        let mut sid = vec![0_u32; (length as usize).div_ceil(std::mem::size_of::<u32>())];
        assert_ne!(
            unsafe {
                CreateWellKnownSid(
                    WinWorldSid,
                    ptr::null_mut(),
                    sid.as_mut_ptr().cast(),
                    &mut length,
                )
            },
            0
        );
        sid
    }

    #[test]
    fn public_read_access_is_not_private() {
        let current_user = CurrentUser::read().expect("current user");
        let world = world_sid();
        let current_user_length = unsafe { GetLengthSid(current_user.sid()) } as usize;
        let world_length = unsafe { GetLengthSid(world.as_ptr().cast_mut().cast()) } as usize;
        let acl_bytes = std::mem::size_of::<ACL>()
            + 2 * (std::mem::size_of::<ACCESS_ALLOWED_ACE>() - std::mem::size_of::<u32>())
            + current_user_length
            + world_length;
        let mut storage = vec![0_u32; acl_bytes.div_ceil(std::mem::size_of::<u32>())];
        let dacl = storage.as_mut_ptr().cast::<ACL>();
        assert_ne!(
            unsafe { InitializeAcl(dacl, acl_bytes as u32, ACL_REVISION) },
            0
        );
        assert_ne!(
            unsafe {
                AddAccessAllowedAceEx(dacl, ACL_REVISION, 0, FILE_ALL_ACCESS, current_user.sid())
            },
            0
        );
        assert_ne!(
            unsafe {
                AddAccessAllowedAceEx(
                    dacl,
                    ACL_REVISION,
                    0,
                    FILE_GENERIC_READ,
                    world.as_ptr().cast_mut().cast(),
                )
            },
            0
        );
        assert!(unsafe { dacl_grants_untrusted_access(dacl, current_user.sid()) });
    }

    #[test]
    fn retained_directory_opens_private_single_link_children() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let directory = open_private_state_directory(&root).expect("private directory");
        drop(directory);
        let directory = open_private_state_directory(&root).expect("reopen private directory");
        let file = open_private_state_child(&directory, "state.next", PrivateFileAccess::Create)
            .expect("private child");
        assert_eq!(
            winapi_util::file::information(&file)
                .expect("file information")
                .number_of_links(),
            1
        );
        assert!(private_state_child_exists(&directory, "state.next").expect("entry query"));
    }

    #[test]
    fn hard_link_is_rejected() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let directory = open_private_state_directory(&root).expect("private directory");
        drop(
            open_private_state_child(&directory, "state", PrivateFileAccess::Create)
                .expect("private child"),
        );
        std::fs::hard_link(root.join("state"), root.join("other")).expect("create hard link");
        assert!(open_private_state_child(&directory, "state", PrivateFileAccess::Read).is_err());
    }
}
