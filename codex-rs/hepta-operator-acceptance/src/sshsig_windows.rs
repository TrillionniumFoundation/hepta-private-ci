use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Write;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::ffi::OsStringExt;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;

use codex_utils_path::windows_private_fs::FileSnapshot;
use codex_utils_path::windows_private_fs::PrivateDirectory;
use codex_utils_path::windows_private_fs::snapshot_private_file;
use codex_utils_path::windows_security::DescriptorInheritance;
use codex_utils_path::windows_security::OwnerSecurityDescriptor;
use codex_utils_path::windows_security::current_user_sid;
use windows_sys::Win32::Foundation::GENERIC_READ;
use windows_sys::Win32::Foundation::GENERIC_WRITE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::CREATE_NEW;
use windows_sys::Win32::Storage::FileSystem::CreateDirectoryW;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_TEMPORARY;
use windows_sys::Win32::Storage::FileSystem::FILE_DISPOSITION_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FileDispositionInfo;
use windows_sys::Win32::Storage::FileSystem::SetFileInformationByHandle;
use windows_sys::Win32::System::Com::CoTaskMemFree;
use windows_sys::Win32::System::SystemInformation::GetSystemDirectoryW;
use windows_sys::Win32::System::SystemInformation::GetWindowsDirectoryW;
use windows_sys::Win32::UI::Shell::FOLDERID_ProgramData;
use windows_sys::Win32::UI::Shell::SHGetKnownFolderPath;

use crate::AcceptanceError;
use crate::ceremony::random_hex;

pub(super) fn system_directory() -> io::Result<PathBuf> {
    system_path(GetSystemDirectoryW)
}

pub(super) fn windows_directory() -> io::Result<PathBuf> {
    system_path(GetWindowsDirectoryW)
}

pub(super) fn program_data_directory() -> io::Result<PathBuf> {
    // Win32-OpenSSH requires ProgramData during initialization, before its
    // standard streams exist. Obtain the machine path from Windows, never
    // from an inherited environment variable or a path search.
    let mut pointer = ptr::null_mut();
    // SAFETY: the known-folder identifier and output pointer are live. Windows
    // returns a NUL-terminated allocation that must be freed with CoTaskMemFree.
    let status = unsafe {
        SHGetKnownFolderPath(
            &FOLDERID_ProgramData,
            /*dwflags*/ 0,
            ptr::null_mut(),
            &mut pointer,
        )
    };
    let result = if status < 0 || pointer.is_null() {
        Err(io::Error::other(format!(
            "Windows ProgramData query failed with HRESULT {status:#010x}"
        )))
    } else {
        let mut length = 0;
        // SAFETY: successful SHGetKnownFolderPath returns a valid NUL-terminated
        // UTF-16 string; the bound also rejects an unsupported oversized path.
        while length < 32_768 && unsafe { *pointer.add(length) } != 0 {
            length += 1;
        }
        if length == 0 || length == 32_768 {
            Err(io::Error::other(
                "Windows ProgramData path is out of bounds",
            ))
        } else {
            // SAFETY: the preceding scan established these initialized units.
            let units = unsafe { std::slice::from_raw_parts(pointer, length) };
            Ok(PathBuf::from(OsString::from_wide(units)))
        }
    };
    // SAFETY: the API requires freeing this allocation even on failure; NULL
    // is explicitly accepted by CoTaskMemFree.
    unsafe { CoTaskMemFree(pointer.cast()) };
    result
}

fn system_path(query: unsafe extern "system" fn(*mut u16, u32) -> u32) -> io::Result<PathBuf> {
    let mut buffer = vec![0_u16; 260];
    loop {
        // SAFETY: the buffer has exactly the writable capacity supplied to the OS.
        let length = unsafe { query(buffer.as_mut_ptr(), buffer.len() as u32) } as usize;
        if length == 0 {
            return Err(io::Error::last_os_error());
        }
        if length < buffer.len() {
            return Ok(PathBuf::from(OsString::from_wide(&buffer[..length])));
        }
        if length > 32_768 {
            return Err(io::Error::other(
                "Windows system directory exceeds its path bound",
            ));
        }
        buffer.resize(length + 1, 0);
    }
}

struct PinnedInput {
    name: &'static str,
    file: Option<File>,
    snapshot: FileSnapshot,
}

/// Exact verification bytes kept immutable until the trusted verifier exits.
pub(crate) struct VerificationInputs {
    allowed_signers_path: PathBuf,
    signature_path: PathBuf,
    inputs: Vec<PinnedInput>,
    directory: PrivateDirectory,
    root: File,
    _ancestors: Vec<File>,
}

impl VerificationInputs {
    pub(crate) fn new(allowed_signers: &[u8], signature: &[u8]) -> Result<Self, AcceptanceError> {
        // Both callers have already bounded these public, validated SSHSIG inputs.
        // This transport never executes a tool found through PATH or an environment variable.
        let parent = std::fs::canonicalize(std::env::temp_dir())?;
        let ancestors = pin_ancestors(&parent)?;
        let root_path = parent.join(format!("codex-sshsig-{}", random_hex::<16>()?));
        let user = current_user_sid()?;
        let descriptor =
            OwnerSecurityDescriptor::new(&user, DescriptorInheritance::ContainersAndObjects)?;
        let attributes = security_attributes(&descriptor);
        let name = wide_path(&root_path);
        // SAFETY: both the NUL-terminated path and the owned descriptor are live.
        // CREATE_DIRECTORY fails if any entry already exists; none is reused.
        if unsafe { CreateDirectoryW(name.as_ptr(), &attributes) } == 0 {
            return Err(io::Error::last_os_error().into());
        }
        let root = OpenOptions::new()
            .access_mode(GENERIC_READ | DELETE)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&root_path)?;
        let directory = match PrivateDirectory::open_existing(&root_path) {
            Ok(directory) => directory,
            Err(error) => {
                remove_empty_directory(&root);
                return Err(error.into());
            }
        };
        let mut inputs = Self {
            allowed_signers_path: root_path.join("allowed-signers"),
            signature_path: root_path.join("signature"),
            inputs: Vec::new(),
            directory,
            root,
            _ancestors: ancestors,
        };
        inputs.add("allowed-signers", allowed_signers)?;
        inputs.add("signature", signature)?;
        Ok(inputs)
    }

    pub(crate) fn allowed_signers_path(&self) -> &Path {
        &self.allowed_signers_path
    }

    pub(crate) fn signature_path(&self) -> &Path {
        &self.signature_path
    }

    fn add(&mut self, name: &'static str, bytes: &[u8]) -> Result<(), AcceptanceError> {
        let path = self
            .allowed_signers_path
            .parent()
            .ok_or_else(|| io::Error::other("verification directory is missing"))?
            .join(name);
        let descriptor =
            OwnerSecurityDescriptor::new(&current_user_sid()?, DescriptorInheritance::ObjectOnly)?;
        let attributes = security_attributes(&descriptor);
        let wide = wide_path(&path);
        // SAFETY: the buffers remain live for this synchronous CREATE_NEW. Only
        // readers may share the file; other writers and deletions are excluded.
        let raw = unsafe {
            CreateFileW(
                wide.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ,
                &attributes,
                CREATE_NEW,
                FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_OPEN_REPARSE_POINT,
                ptr::null_mut(),
            )
        };
        if raw == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error().into());
        }
        // SAFETY: successful CreateFileW transferred one newly owned handle.
        let file = File::from(unsafe { OwnedHandle::from_raw_handle(raw) });
        let snapshot = snapshot_private_file(&file)?;
        self.inputs.push(PinnedInput {
            name,
            file: Some(file),
            snapshot,
        });
        let input = self
            .inputs
            .last_mut()
            .ok_or_else(|| io::Error::other("verification input is missing"))?;
        let writer = input
            .file
            .as_mut()
            .ok_or_else(|| io::Error::other("verification writer is missing"))?;
        writer.write_all(bytes)?;
        input.snapshot = snapshot_private_file(writer)?;
        drop(input.file.take());

        // OpenSSH's read-only CRT stream must share with a read-only guard.
        // Reopening can race, so validate identity AND the entire exact byte
        // sequence after acquiring the guard that denies writes and deletion.
        let mut reader = OpenOptions::new()
            .read(true)
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&path)?;
        let snapshot = snapshot_private_file(&reader)?;
        if !snapshot.same_file(&input.snapshot) {
            return Err(
                io::Error::other("verification input changed during readonly handoff").into(),
            );
        }
        let mut actual = Vec::new();
        (&mut reader)
            .take((bytes.len() as u64).saturating_add(1))
            .read_to_end(&mut actual)?;
        if actual != bytes {
            return Err(io::Error::other(
                "verification input bytes changed during readonly handoff",
            )
            .into());
        }
        input.snapshot = snapshot;
        input.file = Some(reader);
        Ok(())
    }
}

impl Drop for VerificationInputs {
    fn drop(&mut self) {
        for mut input in self.inputs.drain(..) {
            if let Some(file) = input.file.take() {
                if let Ok(snapshot) = snapshot_private_file(&file)
                    && snapshot.same_file(&input.snapshot)
                {
                    input.snapshot = snapshot;
                }
                drop(file);
            }
            // The relative cleanup retains the validated root and removes only
            // our captured file identity. Unknown replacements remain untouched.
            let _ = self
                .directory
                .remove_if_unchanged(input.name, &input.snapshot);
        }
        remove_empty_directory(&self.root);
    }
}

fn pin_ancestors(path: &Path) -> io::Result<Vec<File>> {
    let ancestors = path.ancestors().collect::<Vec<_>>();
    let mut retained = Vec::with_capacity(ancestors.len());
    for ancestor in ancestors.into_iter().rev() {
        let file = OpenOptions::new()
            .read(true)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(ancestor)?;
        let metadata = file.metadata()?;
        if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "verification path contains a non-directory or reparse point",
            ));
        }
        retained.push(file);
    }
    Ok(retained)
}

fn security_attributes(descriptor: &OwnerSecurityDescriptor) -> SECURITY_ATTRIBUTES {
    SECURITY_ATTRIBUTES {
        nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: descriptor.as_ptr().cast_mut(),
        bInheritHandle: 0,
    }
}

fn wide_path(path: &Path) -> Vec<u16> {
    path.as_os_str().encode_wide().chain(Some(0)).collect()
}

fn remove_empty_directory(directory: &File) {
    let disposition = FILE_DISPOSITION_INFO { DeleteFile: true };
    // SAFETY: this owned handle was opened with DELETE access. The OS refuses
    // to remove a nonempty directory; no pathname is reopened for cleanup.
    let _ = unsafe {
        SetFileInformationByHandle(
            directory.as_raw_handle(),
            FileDispositionInfo,
            (&raw const disposition).cast(),
            size_of::<FILE_DISPOSITION_INFO>() as u32,
        )
    };
}

#[cfg(test)]
#[path = "sshsig_windows_tests.rs"]
mod tests;
