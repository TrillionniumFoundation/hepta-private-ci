//! Native access-check experiments on owned temporary objects, never a launcher.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use std::ffi::c_void;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::ConvertStringSidToSidW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::DISABLE_MAX_PRIVILEGE;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetSecurityDescriptorSacl;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::IsTokenRestricted;
use windows_sys::Win32::Security::LABEL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::LUA_TOKEN;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::SetTokenInformation;
use windows_sys::Win32::Security::TOKEN_ADJUST_DEFAULT;
use windows_sys::Win32::Security::TOKEN_DUPLICATE;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TokenIntegrityLevel;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::WRITE_RESTRICTED;
use windows_sys::Win32::Storage::FileSystem::DeleteFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::RemoveDirectoryW;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;
use windows_sys::Win32::System::SystemServices::SE_GROUP_INTEGRITY;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::OpenThreadToken;

pub const CAPABILITY: &str = "S-1-5-21-197-263-389-487";

fn wide(value: impl AsRef<std::ffi::OsStr>) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    value.as_ref().encode_wide().chain(Some(0)).collect()
}

struct Allocation(*mut c_void);

impl Drop for Allocation {
    fn drop(&mut self) {
        unsafe { LocalFree(self.0) };
    }
}

fn sid(value: &str) -> Result<Allocation> {
    let mut value_sid = std::ptr::null_mut();
    ensure!(
        unsafe { ConvertStringSidToSidW(wide(value).as_ptr(), &mut value_sid) } != 0,
        "parse fixture SID: {}",
        std::io::Error::last_os_error()
    );
    Ok(Allocation(value_sid))
}

fn descriptor(sddl: &str) -> Result<Allocation> {
    let mut result = std::ptr::null_mut();
    ensure!(
        unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                wide(sddl).as_ptr(),
                SDDL_REVISION_1,
                &mut result,
                std::ptr::null_mut(),
            )
        } != 0,
        "parse fixture security descriptor: {}",
        std::io::Error::last_os_error()
    );
    Ok(Allocation(result))
}

#[derive(Clone, Copy, Debug)]
pub enum Restriction {
    WriteOnly,
    Full,
}

pub struct RestrictedToken(OwnedHandle);

impl RestrictedToken {
    pub fn new(mode: Restriction) -> Result<Self> {
        let mut base = 0;
        ensure!(
            unsafe {
                OpenProcessToken(
                    GetCurrentProcess(),
                    TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT,
                    &mut base,
                )
            } != 0,
            "open fixture base token: {}",
            std::io::Error::last_os_error()
        );
        let base = unsafe { OwnedHandle::from_raw_handle(base as _) };
        ensure!(
            unsafe { IsTokenRestricted(base.as_raw_handle() as _) } == 0,
            "the experiment requires an unrestricted original process token"
        );
        let cap = sid(CAPABILITY)?;
        let restriction = SID_AND_ATTRIBUTES {
            Sid: cap.0,
            Attributes: 0,
        };
        let flags = DISABLE_MAX_PRIVILEGE
            | LUA_TOKEN
            | match mode {
                Restriction::WriteOnly => WRITE_RESTRICTED,
                Restriction::Full => 0,
            };
        let mut token = 0;
        ensure!(
            unsafe {
                CreateRestrictedToken(
                    base.as_raw_handle() as _,
                    flags,
                    /*disablesidcount*/ 0,
                    std::ptr::null(),
                    /*deleteprivilegecount*/ 0,
                    std::ptr::null(),
                    /*restrictedsidcount*/ 1,
                    &restriction,
                    &mut token,
                )
            } != 0,
            "create experimental token: {}",
            std::io::Error::last_os_error()
        );
        let token = Self(unsafe { OwnedHandle::from_raw_handle(token as _) });
        let group_data = token.information(TokenRestrictedSids)?;
        ensure!(
            group_data.len() * std::mem::size_of::<usize>() >= std::mem::size_of::<TOKEN_GROUPS>()
        );
        let groups = unsafe { &*group_data.as_ptr().cast::<TOKEN_GROUPS>() };
        ensure!(
            groups.GroupCount == 1,
            "expected exactly one restricting SID"
        );
        ensure!(
            unsafe { EqualSid(groups.Groups[0].Sid, cap.0) } != 0,
            "the restricting SID must be the fixture capability, not a user/group identity"
        );
        Ok(token)
    }

    fn information(&self, class: TOKEN_INFORMATION_CLASS) -> Result<Vec<usize>> {
        let mut needed = 0;
        unsafe {
            GetTokenInformation(
                self.0.as_raw_handle() as _,
                class,
                std::ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut needed,
            )
        };
        ensure!(
            needed > 0 && needed <= 64 * 1024,
            "invalid token information length {needed}"
        );
        let mut data = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
        ensure!(
            unsafe {
                GetTokenInformation(
                    self.0.as_raw_handle() as _,
                    class,
                    data.as_mut_ptr().cast(),
                    needed,
                    &mut needed,
                )
            } != 0,
            "read experimental token: {}",
            std::io::Error::last_os_error()
        );
        Ok(data)
    }

    pub fn lower_integrity(&self) -> Result<()> {
        let low = sid("S-1-16-4096")?;
        let sid_len = unsafe { GetLengthSid(low.0) } as usize;
        let byte_len = std::mem::size_of::<TOKEN_MANDATORY_LABEL>() + sid_len;
        let mut storage = vec![0usize; byte_len.div_ceil(std::mem::size_of::<usize>())];
        let label = storage.as_mut_ptr().cast::<TOKEN_MANDATORY_LABEL>();
        let copied_sid = unsafe {
            storage
                .as_mut_ptr()
                .cast::<u8>()
                .add(std::mem::size_of::<TOKEN_MANDATORY_LABEL>())
        }
        .cast::<c_void>();
        ensure!(
            unsafe { CopySid(sid_len as u32, copied_sid, low.0) } != 0,
            "copy fixture integrity SID: {}",
            std::io::Error::last_os_error()
        );
        unsafe {
            label.write(TOKEN_MANDATORY_LABEL {
                Label: SID_AND_ATTRIBUTES {
                    Sid: copied_sid,
                    Attributes: SE_GROUP_INTEGRITY as u32,
                },
            })
        };
        ensure!(
            unsafe {
                SetTokenInformation(
                    self.0.as_raw_handle() as _,
                    TokenIntegrityLevel,
                    storage.as_ptr().cast(),
                    byte_len as u32,
                )
            } != 0,
            "lower experimental token integrity: {}",
            std::io::Error::last_os_error()
        );
        let observed_data = self.information(TokenIntegrityLevel)?;
        ensure!(
            observed_data.len() * std::mem::size_of::<usize>()
                >= std::mem::size_of::<TOKEN_MANDATORY_LABEL>()
        );
        let observed = unsafe { &*observed_data.as_ptr().cast::<TOKEN_MANDATORY_LABEL>() };
        ensure!(
            unsafe { EqualSid(observed.Label.Sid, low.0) } != 0,
            "low integrity readback differs"
        );
        Ok(())
    }

    pub fn run<T>(&self, operation: impl FnOnce() -> T) -> Result<T> {
        ensure_unimpersonated()?;
        ensure!(
            unsafe { ImpersonateLoggedOnUser(self.0.as_raw_handle() as _) } != 0,
            "impersonate experimental token: {}",
            std::io::Error::last_os_error()
        );
        struct Revert;
        impl Drop for Revert {
            fn drop(&mut self) {
                if unsafe { RevertToSelf() } == 0 {
                    std::process::abort();
                }
            }
        }
        let result = {
            let _revert = Revert;
            operation()
        };
        ensure_unimpersonated().context("verify original thread identity after operation")?;
        Ok(result)
    }
}

pub fn ensure_unimpersonated() -> Result<()> {
    let mut previous = 0;
    let has_previous = unsafe {
        OpenThreadToken(
            GetCurrentThread(),
            TOKEN_QUERY,
            /*openasself*/ 1,
            &mut previous,
        )
    };
    if has_previous != 0 {
        unsafe { CloseHandle(previous) };
        anyhow::bail!("expected the original thread without an impersonation token");
    }
    let error = unsafe { GetLastError() };
    ensure!(error == ERROR_NO_TOKEN, "inspect thread token: {error}");
    Ok(())
}

#[derive(Clone, Copy)]
pub enum Dacl {
    Identity(u32),
    Capability(u32),
    InheritableCapability(u32),
    Null,
}

fn acl_bytes(acl: *const ACL) -> Option<Vec<u8>> {
    if acl.is_null() {
        None
    } else {
        // The pointer comes from a successful Windows descriptor parser/query.
        Some(
            unsafe { std::slice::from_raw_parts(acl.cast::<u8>(), (*acl).AclSize as usize) }
                .to_vec(),
        )
    }
}

pub fn set_dacl(path: &Path, policy: Dacl) -> Result<()> {
    let sddl = match policy {
        Dacl::Identity(mask) => format!("D:P(A;;0x{mask:08x};;;WD)"),
        Dacl::Capability(mask) => format!("D:P(A;;FA;;;WD)(A;;0x{mask:08x};;;{CAPABILITY})"),
        Dacl::InheritableCapability(mask) => {
            format!("D:P(A;OICI;FA;;;WD)(A;OICI;0x{mask:08x};;;{CAPABILITY})")
        }
        Dacl::Null => "D:PNO_ACCESS_CONTROL".to_string(),
    };
    set_dacl_sddl(path, &sddl)
}

/// Install and read back a precise DACL on an owned test fixture.
/// Callers must never pass a live, user-owned or system object.
pub fn set_dacl_sddl(path: &Path, sddl: &str) -> Result<()> {
    ensure_unimpersonated().context("configure owned ACL fixture with original thread identity")?;
    let sd = descriptor(sddl)?;
    let (mut present, mut defaulted, mut dacl) = (0, 0, std::ptr::null_mut());
    ensure!(
        unsafe { GetSecurityDescriptorDacl(sd.0, &mut present, &mut dacl, &mut defaulted) } != 0
            && present != 0,
        "fixture DACL must be explicitly present"
    );
    let expected = acl_bytes(dacl);
    let handle = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .open(path)
        .with_context(|| {
            format!(
                "open owned fixture for exact DACL installation: {}",
                path.display()
            )
        })?;
    let code = unsafe {
        SetSecurityInfo(
            handle.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            dacl,
            std::ptr::null(),
        )
    };
    ensure!(code == ERROR_SUCCESS, "install fixture DACL: {code}");
    let mut actual = std::ptr::null_mut();
    let mut actual_dacl = std::ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            handle.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut actual_dacl,
            std::ptr::null_mut(),
            &mut actual,
        )
    };
    ensure!(code == ERROR_SUCCESS, "read back fixture DACL: {code}");
    let actual = Allocation(actual);
    let (mut control, mut revision) = (0, 0);
    ensure!(
        unsafe { GetSecurityDescriptorControl(actual.0, &mut control, &mut revision) } != 0
            && control & SE_DACL_PROTECTED != 0,
        "fixture DACL protection differs"
    );
    ensure!(
        acl_bytes(actual_dacl) == expected,
        "fixture DACL bytes differ"
    );
    Ok(())
}

pub fn lower_object_integrity(path: &Path) -> Result<()> {
    let sd = descriptor("S:(ML;;NW;;;LW)")?;
    let (mut present, mut defaulted, mut label) = (0, 0, std::ptr::null_mut());
    ensure!(
        unsafe { GetSecurityDescriptorSacl(sd.0, &mut present, &mut label, &mut defaulted) } != 0
            && present != 0
            && !label.is_null(),
        "missing fixture integrity label"
    );
    let expected = acl_bytes(label);
    let handle = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_OWNER)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .open(path)?;
    let code = unsafe {
        SetSecurityInfo(
            handle.as_raw_handle() as _,
            SE_FILE_OBJECT,
            LABEL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null(),
            label,
        )
    };
    ensure!(
        code == ERROR_SUCCESS,
        "lower owned fixture integrity: {code}"
    );
    let mut actual = std::ptr::null_mut();
    let mut actual_label = std::ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            handle.as_raw_handle() as _,
            SE_FILE_OBJECT,
            LABEL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut actual_label,
            &mut actual,
        )
    };
    ensure!(
        code == ERROR_SUCCESS,
        "read back owned fixture integrity: {code}"
    );
    let _actual = Allocation(actual);
    ensure!(
        acl_bytes(actual_label) == expected,
        "fixture integrity label bytes differ"
    );
    Ok(())
}

#[derive(Clone, Copy, Debug)]
pub enum Kind {
    File,
    Directory,
}

pub fn create_target(path: &Path, kind: Kind) -> Result<()> {
    match kind {
        Kind::File => std::fs::write(path, b"unchanged")?,
        Kind::Directory => std::fs::create_dir(path)?,
    }
    ensure!(
        !std::fs::metadata(path)?.permissions().readonly(),
        "read-only target would confound delete authorization"
    );
    if matches!(kind, Kind::Directory) {
        ensure!(
            std::fs::read_dir(path)?.next().is_none(),
            "directory must be empty"
        );
    }
    Ok(())
}

pub fn delete(path: &Path, kind: Kind) -> std::io::Result<()> {
    let path = wide(path);
    let ok = unsafe {
        match kind {
            Kind::File => DeleteFileW(path.as_ptr()),
            Kind::Directory => RemoveDirectoryW(path.as_ptr()),
        }
    };
    if ok == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}
