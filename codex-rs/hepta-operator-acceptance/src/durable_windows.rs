use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;

use super::invalid;
use crate::AcceptanceError;

// Windows SDK file flags. Keep the final path component as a reparse point so
// its own handle attributes can reject it instead of inspecting its target.
const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const FILE_ATTRIBUTE_DIRECTORY: u64 = 0x0010;
const FILE_ATTRIBUTE_REPARSE_POINT: u64 = 0x0400;

pub(super) fn configure_open(options: &mut OpenOptions) {
    options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct FileSnapshot {
    attributes: u64,
    creation_time: Option<u64>,
    file_index: u64,
    last_write_time: Option<u64>,
    number_of_links: u64,
    size: u64,
    volume_serial_number: u64,
}

impl FileSnapshot {
    pub(super) fn capture(file: &File, label: &str) -> Result<Self, AcceptanceError> {
        // The safe wrapper queries GetFileInformationByHandle on this exact
        // borrowed handle; a separate pathname lookup cannot validate its links.
        let information = winapi_util::file::information(file)?;
        let attributes = information.file_attributes();
        if attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT) != 0 {
            return Err(invalid(format!(
                "{label} must be a regular file without reparse points"
            )));
        }
        if information.number_of_links() != 1 {
            return Err(invalid(format!("{label} must have exactly one hard link")));
        }
        Ok(Self {
            attributes,
            creation_time: information.creation_time(),
            file_index: information.file_index(),
            last_write_time: information.last_write_time(),
            number_of_links: information.number_of_links(),
            size: information.file_size(),
            volume_serial_number: information.volume_serial_number(),
        })
    }
}

pub(super) fn verify_unchanged(
    file: &File,
    path: &Path,
    before: &FileSnapshot,
    label: &str,
) -> Result<(), AcceptanceError> {
    let after_handle = FileSnapshot::capture(file, label)?;
    let current_path = open_without_following(path)?;
    let after_path = FileSnapshot::capture(&current_path, label)?;
    if before != &after_handle || before != &after_path {
        return Err(invalid(format!(
            "{label} handle or path changed during verification"
        )));
    }
    Ok(())
}

pub(super) fn verify_path(path: &Path, label: &str) -> Result<(), AcceptanceError> {
    let file = open_without_following(path)?;
    verify_private_acl_handle(&file, label)?;
    let before = FileSnapshot::capture(&file, label)?;
    verify_unchanged(&file, path, &before, label)
}

fn open_without_following(path: &Path) -> Result<File, AcceptanceError> {
    let mut options = OpenOptions::new();
    options.read(true);
    configure_open(&mut options);
    Ok(options.open(path)?)
}

#[cfg(test)]
#[path = "durable_windows_tests.rs"]
mod tests;

// A Windows file mode/read-only bit is not a confidentiality policy. The
// effective owner SID and every allow ACE must be checked on the open handle,
// not by looking up an untrusted pathname after the file has been read.
use std::ffi::c_void;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Foundation::PSID;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::CreateWellKnownSid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Security::WinBuiltinAdministratorsSid;
use windows_sys::Win32::Security::WinLocalSystemSid;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;

const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const ACCESS_DENIED_ACE_TYPE: u8 = 1;
const ALLOWED_SID_CAPACITY: usize = 96;

struct OwnedToken(isize);
impl Drop for OwnedToken {
    fn drop(&mut self) {
        // SAFETY: This exact token was returned by OpenProcessToken.
        unsafe { CloseHandle(self.0) };
    }
}

struct OwnedDescriptor(*mut c_void);
impl Drop for OwnedDescriptor {
    fn drop(&mut self) {
        // SAFETY: The descriptor was returned by GetSecurityInfo and must
        // outlive all pointers to its owner SID and ACL.
        unsafe { LocalFree(self.0) };
    }
}

fn current_user_sid<T>(
    action: impl FnOnce(PSID) -> Result<T, AcceptanceError>,
) -> Result<T, AcceptanceError> {
    let mut raw_token = 0;
    // SAFETY: Pseudo-process handle and a writable output handle slot.
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw_token) } == 0 {
        return Err(invalid("Windows owner token unavailable"));
    }
    let _token = OwnedToken(raw_token);
    let mut needed = 0_u32;
    // SAFETY: Deliberate length probe; no memory is dereferenced.
    let probe =
        unsafe { GetTokenInformation(raw_token, TokenUser, std::ptr::null_mut(), 0, &mut needed) };
    if probe != 0 || needed < size_of::<TOKEN_USER>() as u32 || needed > 65536 {
        return Err(invalid("invalid Windows token user length"));
    }
    // usize words keep TOKEN_USER naturally aligned.
    let mut storage = vec![0_usize; (needed as usize).div_ceil(size_of::<usize>())];
    // SAFETY: Storage is writable, aligned and sized to the probed token data.
    if unsafe {
        GetTokenInformation(
            raw_token,
            TokenUser,
            storage.as_mut_ptr().cast(),
            needed,
            &mut needed,
        )
    } == 0
    {
        return Err(invalid("Windows token user query failed"));
    }
    // SAFETY: Successful TokenUser returned a complete TOKEN_USER in aligned storage.
    let sid = unsafe { (*(storage.as_ptr().cast::<TOKEN_USER>())).User.Sid };
    if sid.is_null() || unsafe { IsValidSid(sid) } == 0 {
        return Err(invalid("Windows owner token SID missing or invalid"));
    }
    action(sid)
}

fn well_known_sid(
    kind: i32,
) -> Result<([usize; ALLOWED_SID_CAPACITY / size_of::<usize>()], u32), AcceptanceError> {
    let mut words = [0_usize; ALLOWED_SID_CAPACITY / size_of::<usize>()];
    let mut len = ALLOWED_SID_CAPACITY as u32;
    // SAFETY: Mutable aligned buffer is at least the Win32 maximum SID size.
    if unsafe {
        CreateWellKnownSid(
            kind,
            std::ptr::null_mut(),
            words.as_mut_ptr().cast(),
            &mut len,
        )
    } == 0
    {
        return Err(invalid("unable to construct expected Windows trusted SID"));
    }
    Ok((words, len))
}

fn checked_allow_list(acl: *mut ACL, owner_sid: PSID) -> Result<(), AcceptanceError> {
    if acl.is_null() {
        return Err(invalid("NULL Windows DACL is never private"));
    }
    let (system, _) = well_known_sid(WinLocalSystemSid)?;
    let (admins, _) = well_known_sid(WinBuiltinAdministratorsSid)?;
    let mut information: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: ACL is owned by the live descriptor, output is fully writable.
    if unsafe {
        GetAclInformation(
            acl,
            (&raw mut information).cast(),
            size_of::<ACL_SIZE_INFORMATION>() as u32,
            AclSizeInformation,
        )
    } == 0
    {
        return Err(invalid("invalid Windows ACL size information"));
    }
    if information.AceCount == 0 || information.AceCount > 2048 {
        return Err(invalid("missing or oversized Windows ACL"));
    }
    let mut owner_allow = false;
    for index in 0..information.AceCount {
        let mut entry: *mut c_void = std::ptr::null_mut();
        // SAFETY: ACL is live for the duration of enumeration.
        if unsafe { GetAce(acl, index, &mut entry) } == 0 || entry.is_null() {
            return Err(invalid("unreadable Windows ACL entry"));
        }
        // SAFETY: GetAce supplied a valid pointer to an ACE header.
        let header = unsafe { &*(entry.cast::<ACE_HEADER>()) };
        match header.AceType {
            ACCESS_DENIED_ACE_TYPE => continue,
            ACCESS_ALLOWED_ACE_TYPE => {
                // SidStart begins at byte 8; a valid SID requires another 8
                // bytes plus four bytes for each subauthority. Check the ACE
                // extent BEFORE calling the Win32 SID parser so an attacker-
                // controlled, truncated DACL cannot cause an out-of-bounds read.
                let sid_offset = size_of::<ACE_HEADER>() + size_of::<u32>();
                if (header.AceSize as usize) < sid_offset + 8 {
                    return Err(invalid("truncated Windows allow ACE SID"));
                }
                // SAFETY: GetAce returned a standard ACE with at least eight
                // SID header bytes validated above.
                let sid = unsafe {
                    (&raw const (*(entry.cast::<ACCESS_ALLOWED_ACE>())).SidStart)
                        .cast_mut()
                        .cast()
                };
                let sub_authority_count = unsafe { *((sid as *const u8).add(1)) } as usize;
                let sid_size = 8 + 4 * sub_authority_count;
                if sub_authority_count > 15
                    || sid_size > (header.AceSize as usize) - sid_offset
                    || unsafe { IsValidSid(sid) } == 0
                    || unsafe { GetLengthSid(sid) } as usize != sid_size
                {
                    return Err(invalid("invalid or truncated Windows allow SID"));
                }
                let owner = unsafe { EqualSid(sid, owner_sid) != 0 };
                let system_sid = unsafe { EqualSid(sid, system.as_ptr().cast_mut().cast()) != 0 };
                let admin_sid = unsafe { EqualSid(sid, admins.as_ptr().cast_mut().cast()) != 0 };
                if !(owner || system_sid || admin_sid) {
                    return Err(invalid(
                        "Windows DACL grants access outside owner/system/admin",
                    ));
                }
                owner_allow |= owner;
            }
            _ => return Err(invalid("unsupported Windows ACE type in private state")),
        }
    }
    if !owner_allow {
        return Err(invalid("private Windows file lacks owner allow ACE"));
    }
    Ok(())
}

pub(super) fn verify_private_acl_handle(file: &File, label: &str) -> Result<(), AcceptanceError> {
    current_user_sid(|user_sid| {
        let mut owner_sid: PSID = std::ptr::null_mut();
        let mut acl: *mut ACL = std::ptr::null_mut();
        let mut raw_descriptor = std::ptr::null_mut();
        // SAFETY: The handle remains live for the entire query; the descriptor
        // guards all returned pointers until ACL inspection completes.
        let code = unsafe {
            GetSecurityInfo(
                file.as_raw_handle() as isize,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner_sid,
                std::ptr::null_mut(),
                &mut acl,
                std::ptr::null_mut(),
                &mut raw_descriptor,
            )
        };
        if code != 0 || raw_descriptor.is_null() {
            return Err(invalid(format!(
                "{label} Windows security descriptor unavailable: {code}"
            )));
        }
        let _descriptor = OwnedDescriptor(raw_descriptor);
        if owner_sid.is_null() || unsafe { EqualSid(owner_sid, user_sid) } == 0 {
            return Err(invalid(format!(
                "{label} not owned by the current Windows user"
            )));
        }
        checked_allow_list(acl, user_sid)
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct DirectorySnapshot {
    file_index: u64,
    volume_serial_number: u64,
}

impl DirectorySnapshot {
    fn capture(handle: &File, label: &str) -> Result<Self, AcceptanceError> {
        let information = winapi_util::file::information(handle)?;
        if information.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || information.file_attributes() & FILE_ATTRIBUTE_DIRECTORY == 0
        {
            return Err(invalid(format!(
                "{label} is a reparse point or not a directory"
            )));
        }
        verify_private_acl_handle(handle, label)?;
        Ok(Self {
            file_index: information.file_index(),
            volume_serial_number: information.volume_serial_number(),
        })
    }
}

pub(super) fn capture_directory(
    path: &Path,
    label: &str,
) -> Result<DirectorySnapshot, AcceptanceError> {
    let mut options = OpenOptions::new();
    options
        .read(true)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS);
    let handle = options.open(path)?;
    DirectorySnapshot::capture(&handle, label)
}

pub(super) fn verify_directory_unchanged(
    path: &Path,
    before: &DirectorySnapshot,
    label: &str,
) -> Result<(), AcceptanceError> {
    let after = capture_directory(path, label)?;
    if before != &after {
        return Err(invalid(format!("{label} directory identity changed")));
    }
    Ok(())
}

#[cfg(test)]
pub(crate) fn protect_private_test_directory(path: &Path) -> Result<(), AcceptanceError> {
    configure_test_acl(path, /*grant_world*/ false)
}

#[cfg(test)]
pub(crate) fn allow_untrusted_test_principal(path: &Path) -> Result<(), AcceptanceError> {
    configure_test_acl(path, /*grant_world*/ true)
}

#[cfg(test)]
fn configure_test_acl(path: &Path, grant_world: bool) -> Result<(), AcceptanceError> {
    use std::os::windows::fs::OpenOptionsExt;
    use windows_sys::Win32::Security::ACL_REVISION;
    use windows_sys::Win32::Security::AddAccessAllowedAceEx;
    use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
    use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
    use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
    use windows_sys::Win32::Security::InitializeAcl;
    use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
    use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
    let mut options = OpenOptions::new();
    options
        .access_mode(0x0002_0000 | 0x0004_0000 | 0x0008_0000) // READ_CONTROL | WRITE_DAC | WRITE_OWNER
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT);
    let file = options.open(path)?;
    current_user_sid(|owner| {
        let (system, _) = well_known_sid(WinLocalSystemSid)?;
        let (admins, _) = well_known_sid(WinBuiltinAdministratorsSid)?;
        let mut buffer = [0_usize; 128];
        let acl: *mut ACL = buffer.as_mut_ptr().cast();
        // SAFETY: The ACL memory is writable and aligned; each SID remains
        // valid for the duration of AddAccessAllowedAceEx.
        if unsafe { InitializeAcl(acl, size_of::<[usize; 128]>() as u32, ACL_REVISION) } == 0 {
            return Err(invalid("unable to prepare private Windows fixture ACL"));
        }
        let inherit = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
        let mut permitted = vec![
            owner,
            system.as_ptr().cast_mut().cast(),
            admins.as_ptr().cast_mut().cast(),
        ];
        let world = if grant_world {
            Some(well_known_sid(windows_sys::Win32::Security::WinWorldSid)?)
        } else {
            None
        };
        if let Some((sid, _)) = &world {
            permitted.push(sid.as_ptr().cast_mut().cast());
        }
        for sid in permitted {
            // FILE_ALL_ACCESS for the owner and OS administrators, and only in
            // negative tests for WinWorldSid (a deliberately unsafe DACL).
            if unsafe { AddAccessAllowedAceEx(acl, ACL_REVISION, inherit, 0x001f01ff, sid) } == 0 {
                return Err(invalid("unable to configure Windows test ACL entry"));
            }
        }
        // SAFETY: A live handle with WRITE_DAC and a complete ACL. DACL
        // protection removes the inherited broad grants of the temporary root.
        let code = unsafe {
            SetSecurityInfo(
                file.as_raw_handle() as isize,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION
                    | DACL_SECURITY_INFORMATION
                    | PROTECTED_DACL_SECURITY_INFORMATION,
                owner,
                std::ptr::null_mut(),
                acl,
                std::ptr::null_mut(),
            )
        };
        if code != 0 {
            return Err(invalid(format!("set private fixture DACL failed: {code}")));
        }
        Ok(())
    })?;
    if !grant_world {
        capture_directory(path, "private fixture directory")?;
    }
    Ok(())
}
