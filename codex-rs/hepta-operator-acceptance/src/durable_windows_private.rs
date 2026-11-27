//! Retain the original private Windows directory across sidecar operations.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_utils_path::PrivateFileAccess;
use codex_utils_path::create_private_state_child;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_private_state_child;
use codex_utils_path::replace_private_state_child;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;

use super::FILE_ATTRIBUTE_DIRECTORY;
use super::FILE_ATTRIBUTE_REPARSE_POINT;
use super::FILE_FLAG_OPEN_REPARSE_POINT;
use super::FileSnapshot;
use super::invalid;
use crate::AcceptanceError;

#[derive(Clone, Copy, Eq, PartialEq)]
struct DirectoryIdentity {
    volume: u64,
    index: u64,
}

impl DirectoryIdentity {
    fn capture(directory: &File) -> Result<Self, AcceptanceError> {
        let info = winapi_util::file::information(directory)?;
        let attributes = info.file_attributes();
        if attributes & FILE_ATTRIBUTE_DIRECTORY == 0
            || attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        {
            return Err(invalid("sidecar parent is not a retained real directory"));
        }
        Ok(Self {
            volume: info.volume_serial_number(),
            index: info.file_index(),
        })
    }
}

#[derive(Clone, Copy)]
pub(in crate::durable) enum LockOpen {
    CreateOrOpen,
    Existing,
}

pub(in crate::durable) struct ParentPin {
    directory: File,
    path: PathBuf,
    identity: DirectoryIdentity,
}

impl ParentPin {
    pub(in crate::durable) fn open(path: &Path) -> Result<Self, AcceptanceError> {
        let directory = open_existing_private_state_directory(path)?;
        let identity = DirectoryIdentity::capture(&directory)?;
        Ok(Self {
            directory,
            path: path.to_path_buf(),
            identity,
        })
    }

    pub(in crate::durable) fn for_file(path: &Path) -> Result<Self, AcceptanceError> {
        let parent = path
            .parent()
            .ok_or_else(|| invalid("sidecar artifact has no parent"))?;
        Self::open(parent)
    }

    fn child_name<'a>(&self, path: &'a Path) -> Result<&'a str, AcceptanceError> {
        if path.parent() != Some(self.path.as_path()) {
            return Err(invalid(
                "sidecar artifact is not a child of the retained parent",
            ));
        }
        path.file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| invalid("sidecar artifact name is not one UTF-8 component"))
    }

    pub(in crate::durable) fn read(&self, path: &Path) -> Result<File, AcceptanceError> {
        self.revalidate()?;
        Ok(open_private_state_child(
            &self.directory,
            self.child_name(path)?,
            PrivateFileAccess::Read,
        )?)
    }

    pub(in crate::durable) fn create_new(&self, path: &Path) -> Result<File, AcceptanceError> {
        self.revalidate()?;
        Ok(create_private_state_child(
            &self.directory,
            self.child_name(path)?,
        )?)
    }

    pub(in crate::durable) fn verify(
        &self,
        file: &File,
        path: &Path,
        before: &FileSnapshot,
        label: &str,
    ) -> Result<(), AcceptanceError> {
        // Retain the original FileId, link-count, size and mutation checks.
        super::verify_unchanged(file, path, before, label)?;
        let current = self.read(path)?;
        if FileSnapshot::capture(&current, label)? != *before {
            return Err(invalid(format!("{label} private child identity changed")));
        }
        self.revalidate()
    }

    pub(in crate::durable) fn replace(
        &self,
        source: &Path,
        destination: &Path,
    ) -> Result<(), AcceptanceError> {
        self.revalidate()?;
        replace_private_state_child(
            &self.directory,
            self.child_name(source)?,
            self.child_name(destination)?,
        )?;
        Ok(())
    }

    pub(in crate::durable) fn open_lock(
        &self,
        path: &Path,
        mode: LockOpen,
    ) -> Result<File, AcceptanceError> {
        self.revalidate()?;
        let access = match mode {
            LockOpen::CreateOrOpen => PrivateFileAccess::Create,
            LockOpen::Existing => PrivateFileAccess::Write,
        };
        let original = open_private_state_child(&self.directory, self.child_name(path)?, access)
            .map_err(|error| {
                if matches!(mode, LockOpen::Existing)
                    && error.kind() == std::io::ErrorKind::NotFound
                {
                    invalid("read-only receipt verification requires the existing sidecar lock")
                } else {
                    error.into()
                }
            })?;
        let before = FileSnapshot::capture(&original, "sidecar lock")?;
        // Keep other openers compatible with the nonblocking whole-file lock,
        // while refusing deletion or replacement of this exact lock object.
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(path)?;
        self.verify(&file, path, &before, "sidecar lock")?;
        Ok(file)
    }

    pub(in crate::durable) fn revalidate(&self) -> Result<(), AcceptanceError> {
        let current = open_existing_private_state_directory(&self.path)?;
        if DirectoryIdentity::capture(&self.directory)? != self.identity
            || DirectoryIdentity::capture(&current)? != self.identity
        {
            return Err(invalid("sidecar parent identity changed"));
        }
        Ok(())
    }

    pub(in crate::durable) fn sync(&self) -> Result<(), AcceptanceError> {
        self.revalidate()?;
        // This retained handle has write access. Every actual directory flush
        // error remains a failure; no fallback or durability acknowledgement.
        self.directory.sync_all()?;
        self.revalidate()
    }
}
