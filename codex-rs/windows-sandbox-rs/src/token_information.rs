use anyhow::Result;
use anyhow::bail;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;

/// Owns an aligned buffer whose interior pointers remain valid for the query result.
pub(crate) struct TokenInformation {
    storage: Vec<usize>,
    bytes: usize,
}

impl TokenInformation {
    /// # Safety
    /// The token must be a valid handle with query access.
    pub(crate) unsafe fn query(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<Self> {
        let mut needed = 0;
        unsafe {
            GetTokenInformation(
                token,
                class,
                std::ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut needed,
            );
        }
        if needed == 0 {
            bail!("GetTokenInformation({class}) size failed: {}", unsafe {
                GetLastError()
            });
        }
        let words = (needed as usize).div_ceil(std::mem::size_of::<usize>());
        let mut storage = Vec::new();
        storage.try_reserve_exact(words)?;
        storage.resize(words, 0usize);
        let mut actual = needed;
        if unsafe {
            GetTokenInformation(
                token,
                class,
                storage.as_mut_ptr().cast(),
                needed,
                &mut actual,
            )
        } == 0
        {
            bail!("GetTokenInformation({class}) failed: {}", unsafe {
                GetLastError()
            });
        }
        anyhow::ensure!(actual <= needed, "token information grew during query");
        Ok(Self {
            storage,
            bytes: actual as usize,
        })
    }

    pub(crate) fn as_ptr<T>(&self) -> Result<*const T> {
        anyhow::ensure!(
            self.bytes >= std::mem::size_of::<T>()
                && std::mem::align_of::<T>() <= std::mem::align_of::<usize>(),
            "token information has an invalid layout"
        );
        Ok(self.storage.as_ptr().cast())
    }

    /// # Safety
    /// The information class must be TokenGroups or TokenRestrictedSids.
    pub(crate) unsafe fn group_sids(&self) -> Result<Vec<Vec<u8>>> {
        let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
        anyhow::ensure!(self.bytes >= offset, "token SID header is truncated");
        let groups = self.storage.as_ptr().cast::<TOKEN_GROUPS>();
        let count = unsafe { (*groups).GroupCount } as usize;
        let required = count
            .checked_mul(std::mem::size_of::<SID_AND_ATTRIBUTES>())
            .and_then(|length| offset.checked_add(length))
            .ok_or_else(|| anyhow::anyhow!("token SID array length overflow"))?;
        anyhow::ensure!(required <= self.bytes, "token SID array is truncated");
        let entries = unsafe {
            std::slice::from_raw_parts(
                self.storage
                    .as_ptr()
                    .cast::<u8>()
                    .add(offset)
                    .cast::<SID_AND_ATTRIBUTES>(),
                count,
            )
        };
        entries
            .iter()
            .map(|entry| {
                let length = unsafe { GetLengthSid(entry.Sid) };
                anyhow::ensure!(length != 0, "token contains an invalid SID");
                let mut sid = vec![0_u8; length as usize];
                if unsafe { CopySid(length, sid.as_mut_ptr().cast(), entry.Sid) } == 0 {
                    bail!("copy token SID failed: {}", unsafe { GetLastError() });
                }
                Ok(sid)
            })
            .collect()
    }
}
