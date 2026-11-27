//! Local, administrator-only LSA storage for the sandbox account transaction.
//! This stores account logon secrets, not general application data.
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use windows_sys::Win32::Foundation::STATUS_OBJECT_NAME_NOT_FOUND;
use windows_sys::Win32::Security::Authentication::Identity::LSA_HANDLE;
use windows_sys::Win32::Security::Authentication::Identity::LSA_OBJECT_ATTRIBUTES;
use windows_sys::Win32::Security::Authentication::Identity::LSA_SECRET_MAXIMUM_LENGTH;
use windows_sys::Win32::Security::Authentication::Identity::LSA_UNICODE_STRING;
use windows_sys::Win32::Security::Authentication::Identity::LsaClose;
use windows_sys::Win32::Security::Authentication::Identity::LsaFreeMemory;
use windows_sys::Win32::Security::Authentication::Identity::LsaNtStatusToWinError;
use windows_sys::Win32::Security::Authentication::Identity::LsaOpenPolicy;
use windows_sys::Win32::Security::Authentication::Identity::LsaRetrievePrivateData;
use windows_sys::Win32::Security::Authentication::Identity::LsaStorePrivateData;
use windows_sys::Win32::Security::Authentication::Identity::POLICY_CREATE_SECRET;
use windows_sys::Win32::Security::Authentication::Identity::POLICY_GET_PRIVATE_INFORMATION;

pub(super) struct Store {
    handle: LSA_HANDLE,
    key: Vec<u16>,
}

fn lsa_string(wide: &mut [u16]) -> Result<LSA_UNICODE_STRING> {
    let bytes = u16::try_from(std::mem::size_of_val(wide))
        .context("LSA string exceeds its length field")?;
    Ok(LSA_UNICODE_STRING {
        Length: bytes,
        MaximumLength: bytes,
        Buffer: wide.as_mut_ptr(),
    })
}

fn status_result(status: i32, operation: &'static str) -> Result<()> {
    if status == 0 {
        return Ok(());
    }
    let error = unsafe { LsaNtStatusToWinError(status) };
    Err(std::io::Error::from_raw_os_error(error as i32)).context(operation)
}

struct PrivateData(*mut LSA_UNICODE_STRING);

impl Drop for PrivateData {
    fn drop(&mut self) {
        unsafe {
            if !self.0.is_null() {
                LsaFreeMemory(self.0.cast());
            }
        }
    }
}

impl Store {
    pub(super) fn open(identity_key: &str) -> Result<Self> {
        let mut attributes: LSA_OBJECT_ATTRIBUTES = unsafe { std::mem::zeroed() };
        attributes.Length = std::mem::size_of::<LSA_OBJECT_ATTRIBUTES>() as u32;
        let mut handle = 0;
        status_result(
            unsafe {
                LsaOpenPolicy(
                    std::ptr::null(),
                    &attributes,
                    (POLICY_CREATE_SECRET | POLICY_GET_PRIVATE_INFORMATION) as u32,
                    &mut handle,
                )
            },
            "open local sandbox credential policy",
        )?;
        ensure!(handle != 0, "LSA returned an empty policy handle");
        Ok(Self {
            handle,
            key: format!("L$CodexSandbox.Identity.v1.{identity_key}")
                .encode_utf16()
                .collect(),
        })
    }

    pub(super) fn load(&mut self) -> Result<Option<String>> {
        let key = lsa_string(&mut self.key)?;
        let mut value = std::ptr::null_mut();
        let status = unsafe { LsaRetrievePrivateData(self.handle, &key, &mut value) };
        if status == STATUS_OBJECT_NAME_NOT_FOUND {
            return Ok(None);
        }
        status_result(status, "read local sandbox credential transaction")?;
        let allocation = PrivateData(value);
        ensure!(
            !allocation.0.is_null(),
            "LSA returned an empty credential object"
        );
        let value = unsafe { &*allocation.0 };
        ensure!(
            value.Length != 0
                && value.Length % 2 == 0
                && value.Length <= value.MaximumLength
                && i32::from(value.Length) <= LSA_SECRET_MAXIMUM_LENGTH
                && !value.Buffer.is_null(),
            "invalid local sandbox credential object length"
        );
        let units =
            unsafe { std::slice::from_raw_parts(value.Buffer, usize::from(value.Length) / 2) };
        Ok(Some(
            String::from_utf16(units).context("invalid credential object encoding")?,
        ))
    }

    pub(super) fn save(&mut self, value: &str) -> Result<()> {
        let mut units: Vec<u16> = value.encode_utf16().collect();
        ensure!(
            std::mem::size_of_val(units.as_slice()) <= LSA_SECRET_MAXIMUM_LENGTH as usize,
            "sandbox credential transaction exceeds the LSA secret limit"
        );
        let key = lsa_string(&mut self.key)?;
        let data = lsa_string(&mut units)?;
        status_result(
            unsafe { LsaStorePrivateData(self.handle, &key, &data) },
            "persist local sandbox credential transaction",
        )?;
        ensure!(
            self.load()?.as_deref() == Some(value),
            "sandbox credential transaction did not read back exactly"
        );
        Ok(())
    }

    #[cfg(test)]
    pub(super) fn remove(&mut self) -> Result<()> {
        let key = lsa_string(&mut self.key)?;
        status_result(
            unsafe { LsaStorePrivateData(self.handle, &key, std::ptr::null()) },
            "remove owned test credential transaction",
        )
    }
}

impl Drop for Store {
    fn drop(&mut self) {
        unsafe {
            LsaClose(self.handle);
        }
    }
}
