//! Retain the OS-selected image and refuse non-system writers before spawning.

use super::pipe::native_error;
use codex_utils_path::WindowsFileId;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Foundation::PSID;
use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;
use windows_sys::Win32::Security::*;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::SystemInformation::GetSystemDirectoryW;
use windows_sys::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;
use windows_sys::Win32::System::SystemServices::ACCESS_DENIED_ACE_TYPE;

pub(super) struct SystemImage {
    pub(super) path: PathBuf,
    pub(super) file: File,
    identity: WindowsFileId,
    security: Vec<u8>,
}

impl SystemImage {
    pub(super) fn open() -> io::Result<Self> {
        let mut system = vec![0u16; 32768];
        let count =
            unsafe { GetSystemDirectoryW(system.as_mut_ptr(), system.len() as u32) } as usize;
        if count == 0 || count >= system.len() {
            return Err(native_error("GetSystemDirectoryW"));
        }
        let path = PathBuf::from(String::from_utf16(&system[..count]).map_err(io::Error::other)?)
            .join("OpenSSH")
            .join("ssh-keygen.exe");
        let file = open_held(&path)?;
        let identity = WindowsFileId::inspect(&file)?;
        let security = system_security(&file)?;
        Ok(Self {
            path,
            file,
            identity,
            security,
        })
    }

    pub(super) fn verify(&self) -> io::Result<()> {
        if WindowsFileId::inspect(&self.file)? != self.identity
            || WindowsFileId::inspect(&open_held(&self.path)?)? != self.identity
            || system_security(&self.file)? != self.security
        {
            return Err(io::Error::other(
                "retained System32 OpenSSH image identity/security changed",
            ));
        }
        Ok(())
    }
}

pub(super) fn open_held(path: &Path) -> io::Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    WindowsFileId::inspect(&file)?;
    Ok(file)
}

fn system_security(file: &File) -> io::Result<Vec<u8>> {
    let information = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    let mut length = 0;
    unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            information,
            std::ptr::null_mut(),
            0,
            &mut length,
        )
    };
    if length == 0 || length > 128 * 1024 {
        return Err(native_error(
            "GetKernelObjectSecurity(image descriptor size)",
        ));
    }
    let mut aligned = vec![0usize; (length as usize).div_ceil(std::mem::size_of::<usize>())];
    let descriptor = aligned.as_mut_ptr().cast();
    if unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            information,
            descriptor,
            length,
            &mut length,
        )
    } == 0
    {
        return Err(native_error("GetKernelObjectSecurity(image owner/DACL)"));
    }
    if unsafe { IsValidSecurityDescriptor(descriptor) } == 0 {
        return Err(io::Error::other(
            "invalid native system image security descriptor",
        ));
    }
    let mut owner = std::ptr::null_mut();
    let mut defaulted = 0;
    if unsafe { GetSecurityDescriptorOwner(descriptor, &mut owner, &mut defaulted) } == 0 {
        return Err(native_error("GetSecurityDescriptorOwner(system image)"));
    }
    let base = descriptor as usize;
    let end = base
        .checked_add(length as usize)
        .ok_or_else(|| io::Error::other("image descriptor bound overflow"))?;
    let available = |pointer: usize| {
        if pointer >= base && pointer <= end {
            end - pointer
        } else {
            0
        }
    };
    if !system_sid(owner, available(owner as usize))? {
        return Err(io::Error::other(
            "System32 OpenSSH owner is not a system authority",
        ));
    }
    let mut present = 0;
    let mut dacl = std::ptr::null_mut();
    if unsafe { GetSecurityDescriptorDacl(descriptor, &mut present, &mut dacl, &mut defaulted) }
        == 0
    {
        return Err(native_error("GetSecurityDescriptorDacl(system image)"));
    }
    if present == 0
        || dacl.is_null()
        || available(dacl as usize) < std::mem::size_of::<ACL>()
        || unsafe { (*dacl).AclSize as usize } > available(dacl as usize)
        || unsafe { IsValidAcl(dacl) } == 0
        || unsafe { (*dacl).AceCount } > 128
    {
        return Err(io::Error::other(
            "System32 OpenSSH DACL is absent or indeterminate",
        ));
    }
    for index in 0..unsafe { (*dacl).AceCount } {
        let mut ace = std::ptr::null_mut();
        if unsafe { GetAce(dacl, index as u32, &mut ace) } == 0 {
            return Err(native_error("GetAce(system image DACL)"));
        }
        if ace.is_null() || available(ace as usize) < std::mem::size_of::<ACE_HEADER>() {
            return Err(io::Error::other("null system image ACE"));
        }
        let header = unsafe { &*ace.cast::<ACE_HEADER>() };
        let sid_offset = std::mem::offset_of!(ACCESS_ALLOWED_ACE, SidStart);
        if (header.AceSize as usize) < sid_offset + 8
            || header.AceSize as usize > available(ace as usize)
        {
            return Err(io::Error::other("truncated system image ACE"));
        }
        if header.AceType != ACCESS_ALLOWED_ACE_TYPE as u8
            && header.AceType != ACCESS_DENIED_ACE_TYPE as u8
        {
            return Err(io::Error::other("unsupported system image ACE type"));
        }
        let allowed = unsafe { &*ace.cast::<ACCESS_ALLOWED_ACE>() };
        let sid = std::ptr::addr_of!(allowed.SidStart).cast_mut().cast();
        let trusted = system_sid(sid, header.AceSize as usize - sid_offset)?;
        if header.AceType == ACCESS_DENIED_ACE_TYPE as u8 {
            continue;
        }
        // This is an OS image integrity policy, not private-file admission.
        // Foreign readers/executors are expected; foreign write/control rights
        // and unknown masks are refused. Only OS maintenance authorities write.
        let read_execute = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE | 0x8000_0000 | 0x2000_0000;
        if allowed.Mask & !read_execute != 0 && !trusted {
            return Err(io::Error::other(
                "non-system principal can modify the System32 OpenSSH image",
            ));
        }
    }
    Ok(unsafe { std::slice::from_raw_parts(descriptor.cast::<u8>(), length as usize) }.to_vec())
}

fn system_sid(sid: PSID, available: usize) -> io::Result<bool> {
    if sid.is_null()
        || available < 8
        || 8 + 4 * unsafe { *sid.cast::<u8>().add(1) } as usize > available
        || unsafe { IsValidSid(sid) } == 0
    {
        return Err(io::Error::other("invalid system image SID"));
    }
    let mut text = std::ptr::null_mut();
    if unsafe { ConvertSidToStringSidW(sid, &mut text) } == 0 {
        return Err(native_error("ConvertSidToStringSidW(system image)"));
    }
    if text.is_null() {
        return Err(io::Error::other(
            "system image SID conversion returned null",
        ));
    }
    let result = (0..256)
        .find(|offset| unsafe { *text.add(*offset) } == 0)
        .map(|count| String::from_utf16_lossy(unsafe { std::slice::from_raw_parts(text, count) }))
        .ok_or_else(|| io::Error::other("system image SID exceeds bound"));
    unsafe { LocalFree(text as _) };
    Ok(matches!(
        result?.as_str(),
        "S-1-5-18"
            | "S-1-5-32-544"
            | "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    ))
}
