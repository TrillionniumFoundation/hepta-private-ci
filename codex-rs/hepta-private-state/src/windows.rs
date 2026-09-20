use std::ffi::c_void;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::io::RawHandle;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;

use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::Foundation::ERROR_FILE_NOT_FOUND;
use windows_sys::Win32::Foundation::ERROR_PATH_NOT_FOUND;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE_TYPE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::InitializeSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::READ_CONTROL;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR_REVISION;
use windows_sys::Win32::Security::SetSecurityDescriptorDacl;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Storage::FileSystem::CreateDirectoryW;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
use windows_sys::Win32::Storage::FileSystem::MoveFileExW;
use windows_sys::Win32::Storage::FileSystem::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Storage::FileSystem::OPEN_ALWAYS;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::System::Threading::GetCurrentProcess;

const SET_ACCESS: i32 = 2;

#[derive(Debug)]
pub struct PrivateStateDirectory {
    path: PathBuf,
    _handle: OwnedHandle,
    current_user_sid: Vec<u8>,
    system_sid: LocalSid,
}

#[derive(Debug)]
struct LocalSid(*mut c_void);

impl Drop for LocalSid {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                LocalFree(self.0 as HLOCAL);
            }
        }
    }
}

impl PrivateStateDirectory {
    pub fn open(path: &Path) -> io::Result<Self> {
        if !path.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "private state directory must be absolute",
            ));
        }
        let current_user_sid = current_user_sid()?;
        let system_sid = local_system_sid()?;
        let acl = OwnedAcl::new(
            sid_ptr(&current_user_sid),
            system_sid.0,
            FILE_ALL_ACCESS,
        )?;
        create_directory_if_missing(path, acl.as_ptr())?;
        let handle = open_directory(path)?;
        verify_directory(
            handle.raw(),
            sid_ptr(&current_user_sid),
            system_sid.0,
        )?;
        Ok(Self {
            path: path.to_owned(),
            _handle: handle.0,
            current_user_sid,
            system_sid,
        })
    }

    pub fn entry_exists(&self, name: &str) -> io::Result<bool> {
        validate_name(name)?;
        match self.open_existing(name) {
            Ok(_) => Ok(true),
            Err(error) if matches!(error.raw_os_error(), Some(code) if code as u32 == ERROR_FILE_NOT_FOUND || code as u32 == ERROR_PATH_NOT_FOUND) => Ok(false),
            Err(error) => Err(error),
        }
    }

    pub fn open_file(&self, name: &str, create: bool) -> io::Result<std::fs::File> {
        validate_name(name)?;
        let path = self.path.join(name);
        let wide = wide_path(&path)?;
        let disposition = if create { OPEN_ALWAYS } else { OPEN_EXISTING };
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                FILE_GENERIC_READ | FILE_GENERIC_WRITE | READ_CONTROL,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                ptr::null(),
                disposition,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
                0,
            )
        };
        if handle == 0 || handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        let owned = unsafe { OwnedHandle::from_raw_handle(handle as RawHandle) };
        verify_regular(handle)?;
        Ok(std::fs::File::from(owned))
    }

    pub fn replace(&self, staging: &str, destination: &str) -> io::Result<()> {
        validate_name(staging)?;
        validate_name(destination)?;
        let staging = wide_path(&self.path.join(staging))?;
        let destination = wide_path(&self.path.join(destination))?;
        let result = unsafe {
            MoveFileExW(
                staging.as_ptr(),
                destination.as_ptr(),
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
        };
        if result == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    pub fn sync_all(&self) -> io::Result<()> {
        // MoveFileExW(MOVEFILE_WRITE_THROUGH) is the durable publication point.
        Ok(())
    }

    fn open_existing(&self, name: &str) -> io::Result<OwnedHandle> {
        let path = wide_path(&self.path.join(name))?;
        let handle = unsafe {
            CreateFileW(
                path.as_ptr(),
                FILE_GENERIC_READ | READ_CONTROL,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                ptr::null(),
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
                0,
            )
        };
        if handle == 0 || handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        let owned = unsafe { OwnedHandle::from_raw_handle(handle as RawHandle) };
        verify_regular(handle)?;
        Ok(owned)
    }

    pub fn verify_trust(&self) -> io::Result<()> {
        verify_directory(
            self._handle.as_raw_handle() as HANDLE,
            sid_ptr(&self.current_user_sid),
            self.system_sid.0,
        )
    }
}

struct DirectoryHandle(OwnedHandle);

impl DirectoryHandle {
    fn raw(&self) -> HANDLE {
        self.0.as_raw_handle() as HANDLE
    }
}

use std::os::windows::io::AsRawHandle;

fn open_directory(path: &Path) -> io::Result<DirectoryHandle> {
    let wide = wide_path(path)?;
    let handle = unsafe {
        CreateFileW(
            wide.as_ptr(),
            FILE_GENERIC_READ | FILE_GENERIC_WRITE | READ_CONTROL,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            0,
        )
    };
    if handle == 0 || handle == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    let owned = unsafe { OwnedHandle::from_raw_handle(handle as RawHandle) };
    let info = file_info(handle)?;
    if info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY == 0
        || info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private state path is not a non-reparse directory",
        ));
    }
    Ok(DirectoryHandle(owned))
}

fn verify_regular(handle: HANDLE) -> io::Result<()> {
    let info = file_info(handle)?;
    if info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT) != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private state entry is not a regular non-reparse file",
        ));
    }
    Ok(())
}

fn file_info(handle: HANDLE) -> io::Result<BY_HANDLE_FILE_INFORMATION> {
    let mut info = unsafe { std::mem::zeroed::<BY_HANDLE_FILE_INFORMATION>() };
    if unsafe { GetFileInformationByHandle(handle, &mut info) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(info)
}

fn create_directory_if_missing(path: &Path, dacl: *mut ACL) -> io::Result<()> {
    let wide = wide_path(path)?;
    let mut descriptor = unsafe { std::mem::zeroed::<SECURITY_DESCRIPTOR>() };
    if unsafe {
        InitializeSecurityDescriptor(
            (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast(),
            SECURITY_DESCRIPTOR_REVISION,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if unsafe {
        SetSecurityDescriptorDacl(
            (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast(),
            1,
            dacl,
            0,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast(),
        bInheritHandle: 0,
    };
    if unsafe { CreateDirectoryW(wide.as_ptr(), &attributes) } == 0 {
        let code = unsafe { GetLastError() };
        if code != ERROR_ALREADY_EXISTS {
            return Err(io::Error::from_raw_os_error(code as i32));
        }
    }
    Ok(())
}

fn verify_directory(handle: HANDLE, current: *mut c_void, system: *mut c_void) -> io::Result<()> {
    let info = file_info(handle)?;
    if info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY == 0
        || info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private state directory is replaceable or redirected",
        ));
    }

    let mut owner: *mut c_void = ptr::null_mut();
    let mut dacl: *mut ACL = ptr::null_mut();
    let mut descriptor: *mut c_void = ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            handle,
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut owner,
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    if code != ERROR_SUCCESS {
        return Err(io::Error::from_raw_os_error(code as i32));
    }
    let result = (|| {
        if owner.is_null() || unsafe { EqualSid(owner, current) } == 0 || dacl.is_null() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "private state directory owner/DACL does not match the current principal",
            ));
        }
        let mut acl_info = unsafe { std::mem::zeroed::<ACL_SIZE_INFORMATION>() };
        if unsafe {
            GetAclInformation(
                dacl.cast(),
                (&mut acl_info as *mut ACL_SIZE_INFORMATION).cast(),
                std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let mut current_ok = false;
        let mut system_ok = false;
        for index in 0..acl_info.AceCount {
            let mut raw_ace: *mut c_void = ptr::null_mut();
            if unsafe { GetAce(dacl.cast(), index, &mut raw_ace) } == 0 || raw_ace.is_null() {
                return Err(io::Error::last_os_error());
            }
            let header = unsafe { &*(raw_ace as *const ACE_HEADER) };
            if header.AceType != ACCESS_ALLOWED_ACE_TYPE {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "private state DACL contains a non-allow ACE",
                ));
            }
            let ace = unsafe { &*(raw_ace as *const ACCESS_ALLOWED_ACE) };
            let ace_sid = (&ace.SidStart as *const u32).cast_mut().cast::<c_void>();
            if unsafe { IsValidSid(ace_sid) } == 0 || (ace.Mask & FILE_ALL_ACCESS) != FILE_ALL_ACCESS
            {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "private state DACL contains an invalid or incomplete allow ACE",
                ));
            }
            if unsafe { EqualSid(ace_sid, current) } != 0 {
                current_ok = true;
            } else if unsafe { EqualSid(ace_sid, system) } != 0 {
                system_ok = true;
            } else {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "private state DACL grants access to an unexpected principal",
                ));
            }
        }
        if !current_ok || !system_ok {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "private state DACL lacks current-user or SYSTEM full control",
            ));
        }
        Ok(())
    })();
    if !descriptor.is_null() {
        unsafe {
            LocalFree(descriptor as HLOCAL);
        }
    }
    result
}

struct OwnedAcl(*mut ACL);

impl OwnedAcl {
    fn new(current: *mut c_void, system: *mut c_void, mask: u32) -> io::Result<Self> {
        let inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
        let entries = [
            explicit_access(current, mask, inheritance),
            explicit_access(system, mask, inheritance),
        ];
        let mut acl: *mut ACL = ptr::null_mut();
        let code = unsafe {
            SetEntriesInAclW(
                entries.len() as u32,
                entries.as_ptr(),
                ptr::null_mut(),
                &mut acl,
            )
        };
        if code != ERROR_SUCCESS || acl.is_null() {
            return Err(io::Error::from_raw_os_error(code as i32));
        }
        Ok(Self(acl))
    }

    fn as_ptr(&self) -> *mut ACL {
        self.0
    }
}

impl Drop for OwnedAcl {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                LocalFree(self.0 as HLOCAL);
            }
        }
    }
}

fn explicit_access(sid: *mut c_void, mask: u32, inheritance: u32) -> EXPLICIT_ACCESS_W {
    EXPLICIT_ACCESS_W {
        grfAccessPermissions: mask,
        grfAccessMode: SET_ACCESS,
        grfInheritance: inheritance,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: sid.cast(),
        },
    }
}

fn current_user_sid() -> io::Result<Vec<u8>> {
    let mut token: HANDLE = 0;
    #[link(name = "advapi32")]
    unsafe extern "system" {
        fn OpenProcessToken(
            process_handle: HANDLE,
            desired_access: u32,
            token_handle: *mut HANDLE,
        ) -> i32;
    }
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let result = (|| {
        let mut needed = 0_u32;
        unsafe {
            GetTokenInformation(token, TokenUser, ptr::null_mut(), 0, &mut needed);
        }
        if needed == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut buffer = vec![0_u8; needed as usize];
        if unsafe {
            GetTokenInformation(
                token,
                TokenUser,
                buffer.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let token_user = unsafe { &*(buffer.as_ptr() as *const TOKEN_USER) };
        let sid = token_user.User.Sid;
        let length = unsafe { GetLengthSid(sid) };
        if length == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut copy = vec![0_u8; length as usize];
        if unsafe { CopySid(length, copy.as_mut_ptr().cast(), sid) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(copy)
    })();
    unsafe {
        CloseHandle(token);
    }
    result
}

fn local_system_sid() -> io::Result<LocalSid> {
    #[link(name = "advapi32")]
    unsafe extern "system" {
        fn ConvertStringSidToSidW(value: *const u16, sid: *mut *mut c_void) -> i32;
    }
    let wide = wide_string("S-1-5-18")?;
    let mut sid = ptr::null_mut();
    if unsafe { ConvertStringSidToSidW(wide.as_ptr(), &mut sid) } == 0 || sid.is_null() {
        return Err(io::Error::last_os_error());
    }
    Ok(LocalSid(sid))
}

fn sid_ptr(bytes: &[u8]) -> *mut c_void {
    bytes.as_ptr().cast_mut().cast()
}

fn validate_name(name: &str) -> io::Result<()> {
    if name.is_empty()
        || name.len() > 128
        || name == "."
        || name == ".."
        || name.bytes().any(|byte| {
            byte == 0 || matches!(byte, b'/' | b'\\' | b':' | b'*' | b'?' | b'"' | b'<' | b'>' | b'|')
        })
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "private state entry name is invalid",
        ));
    }
    Ok(())
}

fn wide_string(value: &str) -> io::Result<Vec<u16>> {
    wide_os(std::ffi::OsStr::new(value))
}

fn wide_path(path: &Path) -> io::Result<Vec<u16>> {
    wide_os(path.as_os_str())
}

fn wide_os(value: &std::ffi::OsStr) -> io::Result<Vec<u16>> {
    let mut result = Vec::new();
    for unit in value.encode_wide() {
        if unit == 0 || result.len() >= 32_766 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Windows private-state path contains NUL or is too long",
            ));
        }
        result.push(unit);
    }
    result.push(0);
    Ok(result)
}
