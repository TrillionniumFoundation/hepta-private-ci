use super::no_reparse_dir::open_or_create_private_no_reparse;
use super::private_identity_security::handle_descriptor;
use super::private_identity_security::protected_descriptor;
use super::private_identity_security::validate_protection;
use super::sandbox_users::resolve_sid;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_windows_sandbox::sandbox_secrets_dir;
use codex_windows_sandbox::string_from_sid_bytes;
use codex_windows_sandbox::to_wide;
use rand::RngCore;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::GENERIC_READ;
use windows_sys::Win32::Foundation::GENERIC_WRITE;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::CREATE_NEW;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
use windows_sys::Win32::Storage::FileSystem::MoveFileExW;

pub(super) struct PrivateSecrets {
    directory: OwnedHandle,
    path: PathBuf,
    real_user_sid: String,
}

impl PrivateSecrets {
    pub(super) fn prepare(codex_home: &Path, real_user: &str) -> Result<Self> {
        let path = sandbox_secrets_dir(codex_home);
        let real_user_sid =
            string_from_sid_bytes(&resolve_sid(real_user)?).map_err(anyhow::Error::msg)?;
        let desired = protected_descriptor(Some(&real_user_sid), "OICI")?;
        // All ancestors are checked by NtCreateFile's OBJ_DONT_REPARSE. The new
        // directory receives the private descriptor at creation, not afterward.
        let directory = open_or_create_private_no_reparse(&path, desired.0)?;
        // Existing objects must already be private. Narrowing a broad DACL
        // cannot revoke access previously granted to an open directory handle.
        let result = Self {
            directory,
            path,
            real_user_sid,
        };
        result.validate()?;
        Ok(result)
    }

    fn validate(&self) -> Result<()> {
        let actual = handle_descriptor(self.directory.as_raw_handle() as _, SE_FILE_OBJECT)?;
        validate_protection(&actual, Some(&self.real_user_sid), 3, FILE_ALL_ACCESS)
    }

    pub(super) fn publish(&self, bytes: &[u8]) -> Result<()> {
        self.validate()?;
        let nonce = SmallRng::from_entropy().next_u64();
        let path = self.path.join(format!(
            "sandbox-users-{}-{nonce:016x}.tmp",
            std::process::id()
        ));
        let desired = protected_descriptor(Some(&self.real_user_sid), "")?;
        let attributes = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: desired.0,
            bInheritHandle: 0,
        };
        let path_wide = to_wide(path.as_os_str());
        let handle = unsafe {
            CreateFileW(
                path_wide.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                0,
                &attributes,
                CREATE_NEW,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
                0,
            )
        };
        ensure!(
            handle != INVALID_HANDLE_VALUE,
            "create private credential publication: {}",
            unsafe { GetLastError() }
        );
        let mut file = unsafe { File::from_raw_handle(handle as *mut c_void) };
        let mut pending = PendingFile {
            path,
            published: false,
        };
        // The file is protected at creation, independently of the parent.
        // Check the actual handle before any credential bytes are written.
        self.validate_file(&file)?;
        file.write_all(bytes)
            .context("write private credential publication")?;
        file.sync_all()
            .context("flush private credential publication")?;
        self.validate_file(&file)?;
        drop(file);
        let destination = self.path.join("sandbox_users.json");
        let source_wide = to_wide(pending.path.as_os_str());
        let destination_wide = to_wide(destination.as_os_str());
        ensure!(
            unsafe {
                MoveFileExW(
                    source_wide.as_ptr(),
                    destination_wide.as_ptr(),
                    MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
                )
            } != 0,
            "replace private credential publication: {}",
            unsafe { GetLastError() }
        );
        pending.published = true;
        let mut actual = OpenOptions::new()
            .read(true)
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&destination)
            .context("read back private credential publication")?;
        self.validate_file(&actual)?;
        let mut readback = Vec::new();
        actual.read_to_end(&mut readback)?;
        ensure!(
            readback == bytes,
            "credential publication did not read back exactly"
        );
        self.validate_file(&actual)?;
        self.validate()
    }

    fn validate_file(&self, file: &File) -> Result<()> {
        let metadata = file.metadata()?;
        ensure!(
            metadata.is_file() && metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT == 0,
            "credential publication is not an ordinary no-reparse file"
        );
        let actual = handle_descriptor(file.as_raw_handle() as _, SE_FILE_OBJECT)?;
        validate_protection(&actual, Some(&self.real_user_sid), 0, FILE_ALL_ACCESS)
    }
}

struct PendingFile {
    path: PathBuf,
    published: bool,
}

impl Drop for PendingFile {
    fn drop(&mut self) {
        if !self.published {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

#[cfg(test)]
#[path = "private_identity_publication_tests.rs"]
mod tests;
