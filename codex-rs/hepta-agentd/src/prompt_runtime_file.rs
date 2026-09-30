//! Filesystem boundaries for the mutable prompt runtime store.
//!
//! Opening an existing store never follows a final-component symlink or
//! truncates a file before its descriptor and protected namespace are checked.
//! Unix trusts the directory owner and root, excluding equivalent-UID attackers.

use std::fs;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io;
use std::path::Path;
use std::path::PathBuf;

use super::AgentdPromptRuntimeError;

pub(super) struct PromptDirectory {
    path: PathBuf,
    before: Metadata,
    #[cfg(unix)]
    handle: File,
    #[cfg(unix)]
    namespace: crate::operator_namespace::OperatorNamespace,
}

pub(super) struct PromptFile {
    pub(super) file: File,
    path: PathBuf,
    before: Metadata,
}

impl PromptDirectory {
    pub(super) fn open(path: &Path) -> Result<Self, AgentdPromptRuntimeError> {
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        if let Err(error) = builder.create(path)
            && error.kind() != io::ErrorKind::AlreadyExists
        {
            return Err(AgentdPromptRuntimeError::Unavailable);
        }
        let before = fs::symlink_metadata(path).map_err(unavailable)?;
        validate_directory(&before)?;
        let physical = path.canonicalize().map_err(unavailable)?;
        if !same_identity(
            &before,
            &fs::symlink_metadata(&physical).map_err(unavailable)?,
        ) {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        #[cfg(unix)]
        let (handle, before, namespace) = {
            use std::os::unix::fs::PermissionsExt;
            let probe = physical.join(super::LOCK_FILE);
            let namespace = crate::operator_namespace::OperatorNamespace::capture(&probe, &before)
                .map_err(corrupt)?;
            let handle = File::open(&physical).map_err(unavailable)?;
            let opened = handle.metadata().map_err(unavailable)?;
            validate_directory(&opened)?;
            if !same_identity(&before, &opened) {
                return Err(AgentdPromptRuntimeError::CorruptState);
            }
            namespace.verify(&probe, &opened).map_err(corrupt)?;
            handle
                .set_permissions(fs::Permissions::from_mode(0o700))
                .map_err(unavailable)?;
            let after = handle.metadata().map_err(unavailable)?;
            validate_directory(&after)?;
            if !same_inode_owner(&before, &after)
                || !same_identity(
                    &after,
                    &fs::symlink_metadata(&physical).map_err(unavailable)?,
                )
            {
                return Err(AgentdPromptRuntimeError::CorruptState);
            }
            let namespace = crate::operator_namespace::OperatorNamespace::capture(&probe, &after)
                .map_err(corrupt)?;
            (handle, after, namespace)
        };
        let directory = Self {
            path: physical,
            before,
            #[cfg(unix)]
            handle,
            #[cfg(unix)]
            namespace,
        };
        directory.verify()?;
        Ok(directory)
    }

    fn verify(&self) -> Result<(), AgentdPromptRuntimeError> {
        let after = fs::symlink_metadata(&self.path).map_err(unavailable)?;
        validate_directory(&after)?;
        if !same_identity(&self.before, &after) {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        #[cfg(unix)]
        {
            if !same_identity(&self.before, &self.handle.metadata().map_err(unavailable)?) {
                return Err(AgentdPromptRuntimeError::CorruptState);
            }
            self.namespace
                .verify(&self.path.join(super::LOCK_FILE), &after)
                .map_err(corrupt)?;
        }
        Ok(())
    }

    pub(super) fn open_existing(
        &self,
        name: &str,
    ) -> Result<Option<PromptFile>, AgentdPromptRuntimeError> {
        self.verify()?;
        let path = self.path.join(name);
        let before = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(unavailable(error)),
        };
        validate_file(&before, &self.before)?;
        let file = File::open(&path).map_err(unavailable)?;
        self.finish_open(path, file, Some(before)).map(Some)
    }

    pub(super) fn open_mutable(&self, name: &str) -> Result<PromptFile, AgentdPromptRuntimeError> {
        self.verify()?;
        let path = self.path.join(name);
        let before = match fs::symlink_metadata(&path) {
            Ok(metadata) => {
                validate_file(&metadata, &self.before)?;
                Some(metadata)
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => None,
            Err(error) => return Err(unavailable(error)),
        };
        let mut options = OpenOptions::new();
        options.read(true).write(true);
        if before.is_none() {
            options.create_new(true);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = options.open(&path).map_err(unavailable)?;
        self.finish_open(path, file, before)
    }

    fn finish_open(
        &self,
        path: PathBuf,
        file: File,
        before: Option<Metadata>,
    ) -> Result<PromptFile, AgentdPromptRuntimeError> {
        let opened = file.metadata().map_err(unavailable)?;
        validate_file(&opened, &self.before)?;
        if before
            .as_ref()
            .is_some_and(|before| !same_identity(before, &opened))
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        let result = PromptFile {
            file,
            path,
            before: opened,
        };
        result.verify(self)?;
        Ok(result)
    }

    pub(super) fn publish(
        &self,
        next: &PromptFile,
        destination: &str,
    ) -> Result<(), AgentdPromptRuntimeError> {
        next.verify(self)?;
        let destination = self.path.join(destination);
        match fs::symlink_metadata(&destination) {
            Ok(metadata) => validate_file(&metadata, &self.before)?,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(unavailable(error)),
        }
        fs::rename(&next.path, &destination).map_err(unavailable)?;
        let after = fs::symlink_metadata(&destination)
            .map_err(|_| AgentdPromptRuntimeError::IndeterminateDurability)?;
        if self.verify().is_err()
            || validate_file(&after, &self.before).is_err()
            || !same_identity(&next.before, &after)
        {
            return Err(AgentdPromptRuntimeError::IndeterminateDurability);
        }
        Ok(())
    }

    pub(super) fn sync_all(&self) -> Result<(), AgentdPromptRuntimeError> {
        self.verify()
            .map_err(|_| AgentdPromptRuntimeError::IndeterminateDurability)?;
        #[cfg(unix)]
        self.handle
            .sync_all()
            .map_err(|_| AgentdPromptRuntimeError::IndeterminateDurability)?;
        Ok(())
    }
}

impl PromptFile {
    pub(super) fn verify(
        &self,
        directory: &PromptDirectory,
    ) -> Result<(), AgentdPromptRuntimeError> {
        directory.verify()?;
        let opened = self.file.metadata().map_err(unavailable)?;
        let after = fs::symlink_metadata(&self.path).map_err(unavailable)?;
        validate_file(&opened, &directory.before)?;
        validate_file(&after, &directory.before)?;
        if !same_identity(&self.before, &opened) || !same_identity(&self.before, &after) {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        Ok(())
    }

    pub(super) fn verify_read_snapshot(
        &self,
        directory: &PromptDirectory,
    ) -> Result<(), AgentdPromptRuntimeError> {
        self.verify(directory)?;
        if !same_version(&self.before, &self.file.metadata().map_err(unavailable)?)
            || !same_version(
                &self.before,
                &fs::symlink_metadata(&self.path).map_err(unavailable)?,
            )
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        Ok(())
    }
}

fn validate_directory(metadata: &Metadata) -> Result<(), AgentdPromptRuntimeError> {
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(AgentdPromptRuntimeError::CorruptState);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o022 != 0 {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
    }
    Ok(())
}

fn validate_file(
    metadata: &Metadata,
    directory: &Metadata,
) -> Result<(), AgentdPromptRuntimeError> {
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(AgentdPromptRuntimeError::CorruptState);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != directory.uid()
            || metadata.nlink() != 1
            || metadata.mode() & 0o077 != 0
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
    }
    #[cfg(not(unix))]
    let _ = directory;
    Ok(())
}

fn same_inode_owner(before: &Metadata, after: &Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        (before.dev(), before.ino(), before.uid()) == (after.dev(), after.ino(), after.uid())
    }
    #[cfg(not(unix))]
    {
        before.file_type() == after.file_type()
    }
}

fn same_identity(before: &Metadata, after: &Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        same_inode_owner(before, after)
            && before.mode() == after.mode()
            && before.nlink() == after.nlink()
    }
    #[cfg(not(unix))]
    {
        same_inode_owner(before, after)
    }
}

fn same_version(before: &Metadata, after: &Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        same_identity(before, after)
            && (
                before.len(),
                before.mtime(),
                before.mtime_nsec(),
                before.ctime(),
                before.ctime_nsec(),
            ) == (
                after.len(),
                after.mtime(),
                after.mtime_nsec(),
                after.ctime(),
                after.ctime_nsec(),
            )
    }
    #[cfg(not(unix))]
    {
        same_identity(before, after)
            && before.len() == after.len()
            && before.modified().ok() == after.modified().ok()
    }
}

fn unavailable(_error: io::Error) -> AgentdPromptRuntimeError {
    AgentdPromptRuntimeError::Unavailable
}

fn corrupt(_error: io::Error) -> AgentdPromptRuntimeError {
    AgentdPromptRuntimeError::CorruptState
}

#[cfg(test)]
#[path = "prompt_runtime_file_tests.rs"]
mod tests;
