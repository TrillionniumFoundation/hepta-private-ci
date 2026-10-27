//! Bind the verifier to the effective caller and the real child process token.

use std::fs::File;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::*;
use windows_sys::Win32::System::Threading::*;

#[derive(Debug, Eq, PartialEq)]
pub(super) struct TokenIdentity {
    user: Vec<u8>,
    owner: Vec<u8>,
}

impl TokenIdentity {
    pub(super) fn effective() -> io::Result<Self> {
        let mut handle = 0;
        if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut handle) } == 0 {
            let error = io::Error::last_os_error();
            if error.raw_os_error() != Some(ERROR_NO_TOKEN as i32) {
                return Err(error);
            }
            if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut handle) } == 0 {
                return Err(io::Error::last_os_error());
            }
        }
        Self::from_owned_token(unsafe { OwnedHandle::from_raw_handle(handle as _) })
    }

    pub(super) fn process(process: &impl AsRawHandle) -> io::Result<Self> {
        let mut handle = 0;
        if unsafe { OpenProcessToken(process.as_raw_handle() as _, TOKEN_QUERY, &mut handle) } == 0
        {
            return Err(io::Error::last_os_error());
        }
        Self::from_owned_token(unsafe { OwnedHandle::from_raw_handle(handle as _) })
    }

    fn from_owned_token(token: OwnedHandle) -> io::Result<Self> {
        Ok(Self {
            user: token_sid(token.as_raw_handle() as _, TokenSid::User)?,
            owner: token_sid(token.as_raw_handle() as _, TokenSid::Owner)?,
        })
    }
}

enum TokenSid {
    User,
    Owner,
}

fn token_sid(token: HANDLE, field: TokenSid) -> io::Result<Vec<u8>> {
    let class = match field {
        TokenSid::User => TokenUser,
        TokenSid::Owner => TokenOwner,
    };
    let mut length = 0;
    unsafe { GetTokenInformation(token, class, std::ptr::null_mut(), 0, &mut length) };
    if length == 0 || length > 128 * 1024 {
        return Err(io::Error::last_os_error());
    }
    let mut buffer = vec![0usize; (length as usize).div_ceil(std::mem::size_of::<usize>())];
    if unsafe {
        GetTokenInformation(
            token,
            class,
            buffer.as_mut_ptr().cast(),
            length,
            &mut length,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if length as usize > buffer.len() * std::mem::size_of::<usize>()
        || (length as usize)
            < match field {
                TokenSid::User => std::mem::size_of::<TOKEN_USER>(),
                TokenSid::Owner => std::mem::size_of::<TOKEN_OWNER>(),
            }
    {
        return Err(io::Error::other("truncated verifier token information"));
    }
    let sid = unsafe {
        match field {
            TokenSid::User => (*buffer.as_ptr().cast::<TOKEN_USER>()).User.Sid,
            TokenSid::Owner => (*buffer.as_ptr().cast::<TOKEN_OWNER>()).Owner,
        }
    };
    let base = buffer.as_ptr() as usize;
    let end = base
        .checked_add(length as usize)
        .ok_or_else(|| io::Error::other("verifier token bound overflow"))?;
    let pointer = sid as usize;
    if sid.is_null()
        || pointer < base
        || pointer > end
        || end - pointer < 8
        || 8 + 4 * unsafe { *sid.cast::<u8>().add(1) } as usize > end - pointer
        || unsafe { IsValidSid(sid) } == 0
    {
        return Err(io::Error::other("invalid native verifier token SID"));
    }
    let count = unsafe { GetLengthSid(sid) } as usize;
    if count == 0 || count > 256 {
        return Err(io::Error::other("native verifier token SID exceeds bound"));
    }
    Ok(unsafe { std::slice::from_raw_parts(sid.cast::<u8>(), count) }.to_vec())
}

pub(super) fn same_file(left: &File, right: &File) -> io::Result<bool> {
    Ok(codex_utils_path::WindowsFileId::inspect(left)?
        == codex_utils_path::WindowsFileId::inspect(right)?)
}
