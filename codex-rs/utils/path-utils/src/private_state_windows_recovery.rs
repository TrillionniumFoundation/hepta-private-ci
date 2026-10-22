//! Existing-only retained identities for private Windows recovery inputs.
//!
//! This owns filesystem identity, not recovery authority or database policy.
//! Source handles deny write/delete sharing. All child acquisition is relative
//! to the retained no-reparse directory; no source is created or repaired.

use super::CurrentUser;
use super::HandleKind;
use super::dacl_grants_untrusted_access;
use super::directory;
use super::final_path;
use super::unsafe_state;
use super::validate_handle;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::fs::FileExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SE_SELF_RELATIVE;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_BASIC_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_DISPOSITION_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FileBasicInfo;
use windows_sys::Win32::Storage::FileSystem::FileDispositionInfo;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::SetFileInformationByHandle;

/// An existing private directory retained without creation or permission repair.
/// The owner must validate currentness separately before trusting copied data.
#[derive(Debug)]
pub struct RetainedPrivateStateDirectory {
    descriptor: File,
    path: PathBuf,
    snapshot: Snapshot,
}

/// One existing private, single-link file opened through its retained directory.
/// This handle cannot write and excludes ordinary writer/delete handles.
#[derive(Debug)]
pub struct RetainedPrivateStateFile {
    descriptor: File,
    name: OsString,
    snapshot: Snapshot,
}

impl RetainedPrivateStateDirectory {
    /// Open only an existing directory. Missing and redirected paths fail.
    pub fn open_existing(path: &Path) -> io::Result<Self> {
        let descriptor = directory::open_existing(path)?;
        let snapshot = Snapshot::capture(&descriptor, HandleKind::Directory)?;
        let path = final_path(&descriptor)?;
        Ok(Self { descriptor, path, snapshot })
    }

    /// Retain a read-only child. Absence is distinct from any acquisition error.
    pub fn retain_file(&self, name: &OsStr) -> io::Result<Option<RetainedPrivateStateFile>> {
        let descriptor = match directory::recovery_child(
            &self.descriptor, name, directory::RecoveryChildAccess::RetainReadOnly,
        ) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        let snapshot = Snapshot::capture(&descriptor, HandleKind::File)?;
        Ok(Some(RetainedPrivateStateFile { descriptor, name: name.to_os_string(), snapshot }))
    }

    /// Verify both the retained directory and its original namespace identity.
    pub fn verify_unchanged(&self) -> io::Result<()> {
        let reopened = directory::open_existing(&self.path)?;
        if final_path(&self.descriptor)? != self.path
            || Snapshot::capture(&self.descriptor, HandleKind::Directory)? != self.snapshot
            || Snapshot::capture(&reopened, HandleKind::Directory)? != self.snapshot
        {
            return Err(unsafe_state("retained private directory changed"));
        }
        Ok(())
    }

    /// Verify the same name still denotes the same unchanged retained file.
    pub fn verify_file_unchanged(&self, file: &RetainedPrivateStateFile) -> io::Result<()> {
        let reopened = self.retain_file(&file.name)?
            .ok_or_else(|| unsafe_state("retained private file disappeared"))?;
        if Snapshot::capture(&file.descriptor, HandleKind::File)? != file.snapshot
            || reopened.snapshot != file.snapshot
        {
            return Err(unsafe_state("retained private file changed"));
        }
        Ok(())
    }

    /// Create a new private recovery output. Existing names are never reopened.
    /// This intentionally changes the directory snapshot, so callers must first
    /// finish reading and validating the complete immutable source bundle.
    pub fn create_new_file(&self, name: &OsStr) -> io::Result<File> {
        validate_handle(&self.descriptor, HandleKind::Directory)?;
        let file = directory::recovery_child(
            &self.descriptor, name, directory::RecoveryChildAccess::CreateNew,
        )?;
        validate_handle(&file, HandleKind::File)?;
        Ok(file)
    }

    /// Discard a failed new output through its owned handle, without looking up
    /// or deleting a pathname that could now denote a different object. Only
    /// output creation grants DELETE access; retained inputs never receive it.
    pub fn discard_created_file(&self, file: File) -> io::Result<()> {
        validate_handle(&file, HandleKind::File)?;
        if final_path(&file)?.parent() != Some(final_path(&self.descriptor)?.as_path()) {
            return Err(unsafe_state("new output is outside its retained directory"));
        }
        let disposition = FILE_DISPOSITION_INFO { DeleteFile: 1 };
        // SAFETY: the owned file and correctly sized Win32 input live through
        // this call. A successful deletion disposition takes effect on close.
        if unsafe {
            SetFileInformationByHandle(file.as_raw_handle() as HANDLE, FileDispositionInfo,
                (&disposition as *const FILE_DISPOSITION_INFO).cast(),
                size_of::<FILE_DISPOSITION_INFO>() as u32)
        } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}

impl RetainedPrivateStateFile {
    /// Length captured from this exact retained handle, before any copying.
    pub fn len(&self) -> u64 {
        self.snapshot.length
    }

    /// Whether the retained input was empty at acquisition.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Read exact bytes from the retained handle without reopening its path.
    pub fn read_exact_at(&self, mut output: &mut [u8], mut offset: u64) -> io::Result<()> {
        while !output.is_empty() {
            match self.descriptor.seek_read(output, offset) {
                Ok(0) => return Err(io::Error::from(io::ErrorKind::UnexpectedEof)),
                Ok(read) => {
                    offset = offset.checked_add(read as u64)
                        .ok_or_else(|| io::Error::from(io::ErrorKind::InvalidInput))?;
                    output = &mut output[read..];
                }
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(error) => return Err(error),
            }
        }
        Ok(())
    }
}

#[derive(Debug, Eq, PartialEq)]
struct Snapshot {
    volume: u64,
    file_id: [u8; 16],
    length: u64,
    links: u32,
    attributes: u32,
    created: i64,
    modified: i64,
    changed: i64,
    security: Vec<u8>,
}

impl Snapshot {
    fn capture(file: &File, kind: HandleKind) -> io::Result<Self> {
        validate_handle(file, kind)?;
        let handle = file.as_raw_handle() as HANDLE;
        // SAFETY: these Win32 POD outputs are zero-initialized, correctly sized
        // and remain live through their synchronous information queries.
        let mut id: FILE_ID_INFO = unsafe { std::mem::zeroed() };
        let mut basic: FILE_BASIC_INFO = unsafe { std::mem::zeroed() };
        let mut standard: FILE_STANDARD_INFO = unsafe { std::mem::zeroed() };
        if unsafe {
            GetFileInformationByHandleEx(handle, FileIdInfo,
                (&mut id as *mut FILE_ID_INFO).cast(), size_of::<FILE_ID_INFO>() as u32)
        } == 0 || unsafe {
            GetFileInformationByHandleEx(handle, FileBasicInfo,
                (&mut basic as *mut FILE_BASIC_INFO).cast(), size_of::<FILE_BASIC_INFO>() as u32)
        } == 0 || unsafe {
            GetFileInformationByHandleEx(handle, FileStandardInfo,
                (&mut standard as *mut FILE_STANDARD_INFO).cast(), size_of::<FILE_STANDARD_INFO>() as u32)
        } == 0 {
            return Err(io::Error::last_os_error());
        }
        let directory = matches!(kind, HandleKind::Directory);
        if standard.EndOfFile < 0 || standard.DeletePending != 0
            || (standard.Directory != 0) != directory
            || (basic.FileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0) != directory
            || basic.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || !directory && standard.NumberOfLinks != 1
        {
            return Err(unsafe_state("invalid retained recovery file type"));
        }
        Ok(Self {
            volume: id.VolumeSerialNumber,
            file_id: id.FileId.Identifier,
            length: standard.EndOfFile as u64,
            links: standard.NumberOfLinks,
            attributes: basic.FileAttributes,
            created: basic.CreationTime,
            modified: basic.LastWriteTime,
            changed: basic.ChangeTime,
            security: security_snapshot(file)?,
        })
    }
}

fn security_snapshot(file: &File) -> io::Result<Vec<u8>> {
    let user = CurrentUser::read()?;
    let mut owner = ptr::null_mut();
    let mut dacl: *mut ACL = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    // SAFETY: GetSecurityInfo allocates the self-relative descriptor. All
    // returned pointers are used only before the single LocalFree below.
    let status = unsafe { GetSecurityInfo(file.as_raw_handle() as HANDLE,
        1, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
        &mut owner, ptr::null_mut(), &mut dacl, ptr::null_mut(), &mut descriptor) };
    let result = (|| {
        if status != ERROR_SUCCESS || descriptor.is_null() || owner.is_null() || dacl.is_null() {
            return Err(unsafe_state("incomplete recovery security descriptor"));
        }
        let mut control = 0;
        let mut revision = 0;
        let valid = unsafe {
            IsValidSecurityDescriptor(descriptor) != 0
                && GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) != 0
                && control & SE_SELF_RELATIVE != 0
                && EqualSid(owner, user.sid()) != 0
                && !dacl_grants_untrusted_access(dacl, user.sid())
        };
        if !valid {
            return Err(unsafe_state("unsafe recovery owner or DACL"));
        }
        let length = unsafe { GetSecurityDescriptorLength(descriptor) } as usize;
        if !(20..=1024 * 1024).contains(&length) {
            return Err(unsafe_state("recovery security descriptor exceeds bound"));
        }
        // SAFETY: Win32 validated the self-relative descriptor and returned its
        // allocation length. Copy before releasing the owning allocation.
        Ok(unsafe { std::slice::from_raw_parts(descriptor.cast::<u8>(), length) }.to_vec())
    })();
    if !descriptor.is_null() {
        unsafe { LocalFree(descriptor as HLOCAL) };
    }
    result
}

#[cfg(test)]
#[path = "private_state_windows_recovery_tests.rs"]
mod tests;
