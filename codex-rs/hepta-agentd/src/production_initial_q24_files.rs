//! Existing private descriptors for one first-A invocation. The same tracker
//! follows late Ledger assembly so no writer can alias an earlier model/read FD.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;

use crate::AgentdError;

#[derive(Clone, Copy, Eq, PartialEq)]
enum Access {
    Read,
    Write,
    Append,
}

pub(super) struct OriginalFiles {
    owner: u32,
    opened: BTreeMap<(u64, u64), Access>,
}

impl OriginalFiles {
    pub(super) fn new() -> Result<Self, AgentdError> {
        // SAFETY: geteuid only reads this process's actual kernel credential.
        let owner = unsafe { libc::geteuid() };
        if owner == 0 {
            return Err(invalid("Initial A requires its actual non-Root owner"));
        }
        Ok(Self {
            owner,
            opened: BTreeMap::new(),
        })
    }

    pub(super) fn read(&mut self, path: &Path) -> Result<File, AgentdError> {
        self.open(path, Access::Read)
    }

    pub(super) fn write(&mut self, path: &Path) -> Result<File, AgentdError> {
        self.open(path, Access::Write)
    }

    pub(super) fn append(&mut self, path: &Path) -> Result<File, AgentdError> {
        self.open(path, Access::Append)
    }

    fn open(&mut self, path: &Path, access: Access) -> Result<File, AgentdError> {
        if !path.is_absolute()
            || path.as_os_str().as_encoded_bytes().len() > 4096
            || path
                .components()
                .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
            || path.file_name().is_none()
        {
            return Err(invalid("bounded absolute original path required"));
        }
        let parent = path
            .parent()
            .ok_or_else(|| invalid("original parent absent"))?;
        if parent.canonicalize()? != parent {
            return Err(invalid("original parent is not canonical"));
        }
        let file = OpenOptions::new()
            .read(true)
            .write(access != Access::Read)
            .append(access == Access::Append)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(path)?;
        let physical = file.metadata()?;
        let named = std::fs::symlink_metadata(path)?;
        if !physical.is_file()
            || !named.is_file()
            || physical.nlink() != 1
            || named.nlink() != 1
            || !matches!(physical.mode() & 0o7777, 0o400 | 0o600)
            || physical.mode() != named.mode()
            || physical.uid() != named.uid()
            || (physical.dev(), physical.ino()) != (named.dev(), named.ino())
            || parent.canonicalize()? != parent
            || (physical.uid() != self.owner && (access != Access::Read || physical.uid() != 0))
        {
            return Err(invalid("original private descriptor custody differs"));
        }
        let identity = (physical.dev(), physical.ino());
        if self
            .opened
            .get(&identity)
            .is_some_and(|previous| *previous != Access::Read || access != Access::Read)
        {
            return Err(invalid("an original writer aliases another retained file"));
        }
        self.opened.insert(identity, access);
        Ok(file)
    }
}

pub(super) fn require_unwritten(file: &File) -> Result<(), AgentdError> {
    if file.metadata()?.len() != 0 {
        return Err(invalid("first-A owner file already contains history"));
    }
    Ok(())
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(format!("original Initial Q24 file: {message}"))
}

#[cfg(test)]
#[path = "production_initial_q24_files_tests.rs"]
mod tests;
