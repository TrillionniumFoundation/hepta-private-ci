//! Windows private-owner equivalence: the effective owner/user plus the OS
//! System/Administrators privilege boundary. No null DACL or foreign grant.

use super::SqliteRecoveryError;
use std::fs::File;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::PSID;
use windows_sys::Win32::Security::*;
use windows_sys::Win32::System::Threading::*;

pub(super) fn private_security(file: &File) -> Result<Vec<u8>, SqliteRecoveryError> {
    let token = effective_token()?;
    let user = token_sid(&token, TokenUser)?;
    let owner_identity = token_sid(&token, TokenOwner)?;
    let system = well_known(WinLocalSystemSid)?;
    let administrators = well_known(WinBuiltinAdministratorsSid)?;
    let creator = well_known(WinCreatorOwnerSid)?;
    let mut length = 0;
    let information = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    // SAFETY: this first read obtains the required buffer length only.
    unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            information,
            std::ptr::null_mut(),
            0,
            &mut length,
        )
    };
    let mut buffer = aligned(length)?;
    // SAFETY: the aligned allocation contains at least length initialized bytes.
    let descriptor = buffer.as_mut_ptr().cast();
    if unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            information,
            descriptor,
            length,
            &mut length,
        )
    } == 0
        || unsafe { IsValidSecurityDescriptor(descriptor) } == 0
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let mut owner = std::ptr::null_mut();
    let mut defaulted = 0;
    // SAFETY: the OS validated descriptor owns the returned SID while buffer lives.
    if unsafe { GetSecurityDescriptorOwner(descriptor, &mut owner, &mut defaulted) } == 0
        || !same_sid(owner, &user) && !same_sid(owner, &owner_identity)
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let mut present = 0;
    let mut dacl = std::ptr::null_mut();
    // SAFETY: all outputs are live; the ACL remains owned by buffer.
    if unsafe { GetSecurityDescriptorDacl(descriptor, &mut present, &mut dacl, &mut defaulted) }
        == 0
        || present == 0
        || dacl.is_null()
        || unsafe { IsValidAcl(dacl) } == 0
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    // SAFETY: IsValidAcl and the kernel descriptor validate the ACL/ACE layout.
    for index in 0..unsafe { (*dacl).AceCount } {
        let mut ace = std::ptr::null_mut();
        if unsafe { GetAce(dacl, u32::from(index), &mut ace) } == 0 || ace.is_null() {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let header = unsafe { &*ace.cast::<ACE_HEADER>() };
        match header.AceType {
            1 => continue, // ACCESS_DENIED_ACE_TYPE cannot grant access.
            0 if usize::from(header.AceSize) >= std::mem::size_of::<ACCESS_ALLOWED_ACE>() => {}
            _ => return Err(SqliteRecoveryError::Indeterminate),
        }
        let sid_offset = std::mem::offset_of!(ACCESS_ALLOWED_ACE, SidStart);
        if usize::from(header.AceSize) < sid_offset + 8 {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        // SAFETY: the SID header's eight bytes were bounded by this ACE above.
        let subauthorities = unsafe { *ace.cast::<u8>().add(sid_offset + 1) };
        if usize::from(header.AceSize) < sid_offset + 8 + usize::from(subauthorities) * 4 {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let allowed = unsafe { &*ace.cast::<ACCESS_ALLOWED_ACE>() };
        let sid = std::ptr::from_ref(&allowed.SidStart).cast_mut().cast();
        if allowed.Mask == 0 {
            continue;
        }
        // CREATOR_OWNER is allowed only as an inheritance template, never an
        // effective anonymous/current-object grant. Child files are rechecked.
        let creator_template =
            u32::from(header.AceFlags) & INHERIT_ONLY_ACE != 0 && same_sid(sid, &creator);
        if !creator_template
            && !same_sid(sid, &user)
            && !same_sid(sid, &owner_identity)
            && !same_sid(sid, &system)
            && !same_sid(sid, &administrators)
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
    }
    // SAFETY: buffer has at least length bytes from the successful OS call.
    Ok(
        unsafe { std::slice::from_raw_parts(buffer.as_ptr().cast::<u8>(), length as usize) }
            .to_vec(),
    )
}

fn effective_token() -> Result<OwnedHandle, SqliteRecoveryError> {
    let mut handle = 0;
    // SAFETY: pseudohandles are borrowed; a successful token call creates one
    // owned handle. A thread impersonation token takes precedence, as with euid.
    let thread = unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut handle) };
    if thread == 0
        && (unsafe { GetLastError() } != ERROR_NO_TOKEN
            || unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut handle) } == 0)
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    if handle == 0 {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    // SAFETY: either token API returned exactly one new owned handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(handle as _) })
}

fn token_sid(
    token: &OwnedHandle,
    class: TOKEN_INFORMATION_CLASS,
) -> Result<Vec<usize>, SqliteRecoveryError> {
    let mut length = 0;
    // SAFETY: the first call requests only the required buffer size.
    unsafe {
        GetTokenInformation(
            token.as_raw_handle() as _,
            class,
            std::ptr::null_mut(),
            0,
            &mut length,
        )
    };
    let mut buffer = aligned(length)?;
    if unsafe {
        GetTokenInformation(
            token.as_raw_handle() as _,
            class,
            buffer.as_mut_ptr().cast(),
            length,
            &mut length,
        )
    } == 0
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    // SAFETY: class is only TokenUser/TokenOwner and the OS supplied the matching
    // aligned structure and its SID in this live allocation.
    let sid = unsafe {
        match class {
            value if value == TokenUser => (*buffer.as_ptr().cast::<TOKEN_USER>()).User.Sid,
            value if value == TokenOwner => (*buffer.as_ptr().cast::<TOKEN_OWNER>()).Owner,
            _ => return Err(SqliteRecoveryError::Indeterminate),
        }
    };
    copy_sid(sid)
}

fn copy_sid(sid: PSID) -> Result<Vec<usize>, SqliteRecoveryError> {
    // SAFETY: callers pass OS-owned SIDs valid for the duration of this call.
    if sid.is_null() || unsafe { IsValidSid(sid) } == 0 {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let length = unsafe { GetLengthSid(sid) } as usize;
    let mut copy = aligned(length as u32)?;
    // SAFETY: the copied SID and aligned destination both contain length bytes.
    unsafe {
        std::ptr::copy_nonoverlapping(sid.cast::<u8>(), copy.as_mut_ptr().cast::<u8>(), length)
    };
    Ok(copy)
}

fn same_sid(sid: PSID, bytes: &[usize]) -> bool {
    // SAFETY: bytes are complete copied OS SIDs; sid belongs to a validated SD.
    !sid.is_null()
        && unsafe { IsValidSid(sid) != 0 && EqualSid(sid, bytes.as_ptr().cast_mut().cast()) != 0 }
}

fn well_known(kind: WELL_KNOWN_SID_TYPE) -> Result<Vec<usize>, SqliteRecoveryError> {
    let mut length = 68; // SECURITY_MAX_SID_SIZE from the Windows SDK.
    let mut buffer = aligned(length)?;
    // SAFETY: the aligned buffer is large enough for any well-known SID.
    if unsafe {
        CreateWellKnownSid(
            kind,
            std::ptr::null_mut(),
            buffer.as_mut_ptr().cast(),
            &mut length,
        )
    } == 0
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    copy_sid(buffer.as_mut_ptr().cast())
}

fn aligned(length: u32) -> Result<Vec<usize>, SqliteRecoveryError> {
    if length == 0 || length > 128 * 1024 {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(vec![
        0;
        (length as usize).div_ceil(std::mem::size_of::<usize>())
    ])
}
