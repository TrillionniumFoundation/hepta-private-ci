//! Bounded readback from the original native token owner.
#![deny(clippy::all)]
use anyhow::Result;
use std::ffi::c_void;
use std::mem::offset_of;
use std::mem::size_of;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;

// Kernel query memory is aligned, bounded, initialized and never escapes as a pointer.
pub(super) struct TokenBytes {
    words: Vec<usize>,
    pub(super) length: usize,
}

impl TokenBytes {
    pub(super) fn query(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<Self> {
        let mut needed = 0;
        // SAFETY: token is owned by the caller; this first call has no output buffer.
        let first = unsafe {
            GetTokenInformation(
                token,
                class,
                std::ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut needed,
            )
        };
        anyhow::ensure!(first == 0 && unsafe { GetLastError() } == ERROR_INSUFFICIENT_BUFFER);
        anyhow::ensure!((4..=65_536).contains(&needed), "invalid token query size");
        let mut result = Self {
            words: vec![0; (needed as usize).div_ceil(size_of::<usize>())],
            length: needed as usize,
        };
        // SAFETY: the aligned zeroed buffer covers the advertised capacity.
        anyhow::ensure!(
            unsafe {
                GetTokenInformation(
                    token,
                    class,
                    result.words.as_mut_ptr().cast(),
                    needed,
                    &mut needed,
                )
            } != 0,
            "token query failed: {}",
            unsafe { GetLastError() }
        );
        anyhow::ensure!(needed as usize <= result.length && needed >= 4);
        result.length = needed as usize;
        Ok(result)
    }

    pub(super) fn value<T: Copy>(&self, offset: usize) -> Result<T> {
        anyhow::ensure!(
            offset
                .checked_add(size_of::<T>())
                .is_some_and(|end| end <= self.length)
        );
        // SAFETY: checked initialized range; callers use only native integer/pointer structs.
        Ok(
            unsafe {
                std::ptr::read_unaligned(self.words.as_ptr().cast::<u8>().add(offset).cast())
            },
        )
    }

    pub(super) fn pointed_bytes(&self, pointer: *const u8, length: usize) -> Result<Vec<u8>> {
        let start = pointer as usize;
        let base = self.words.as_ptr() as usize;
        anyhow::ensure!(
            start >= base
                && start
                    .checked_add(length)
                    .is_some_and(|end| end <= base + self.length)
        );
        // SAFETY: the complete pointed range belongs to this initialized query buffer.
        Ok(unsafe { std::slice::from_raw_parts(pointer, length) }.to_vec())
    }

    pub(super) fn sid(&self, pointer: *mut c_void) -> Result<Vec<u8>> {
        let header = self.pointed_bytes(pointer.cast(), /*length*/ 8)?;
        anyhow::ensure!(header[0] == 1 && header[1] <= 15, "invalid queried SID");
        self.pointed_bytes(pointer.cast(), 8 + usize::from(header[1]) * 4)
    }

    pub(super) fn groups(&self) -> Result<Vec<Vec<u8>>> {
        let count = self.value::<u32>(/*offset*/ 0)? as usize;
        let offset = offset_of!(TOKEN_GROUPS, Groups);
        anyhow::ensure!(
            count <= self.length.saturating_sub(offset) / size_of::<SID_AND_ATTRIBUTES>()
        );
        let mut result = Vec::new();
        for index in 0..count {
            let entry =
                self.value::<SID_AND_ATTRIBUTES>(offset + index * size_of::<SID_AND_ATTRIBUTES>())?;
            result.push(self.sid(entry.Sid)?);
        }
        result.sort();
        Ok(result)
    }

    pub(super) fn default_dacl(&self) -> Result<Option<Vec<u8>>> {
        let pointer = self.value::<*const u8>(/*offset*/ 0)?;
        if pointer.is_null() {
            return Ok(None); // A token may legitimately have no default DACL.
        }
        let header = self.pointed_bytes(pointer, /*length*/ 8)?;
        let length = usize::from(u16::from_le_bytes([header[2], header[3]]));
        anyhow::ensure!(length >= 8, "invalid default DACL");
        self.pointed_bytes(pointer, length).map(Some)
    }
}
