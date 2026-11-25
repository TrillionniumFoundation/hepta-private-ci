//! Keep the original private Windows handles across session reads and publication.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;

use codex_utils_path::PrivateFileAccess;

use crate::MatrixSdkError;
use crate::MatrixSession;
use crate::MatrixSidecarConfigError;
use crate::sdk::MATRIX_SESSION_MAX_BYTES;

const SESSION_NAME: &str = "session.json";
const NEXT_SESSION_NAME: &str = ".session.json.next";
const OWNER_LOCK_NAME: &str = ".session.lock";

pub(crate) struct RetainedSessionDirectories {
    directory: File,
    // These directory pins must outlive every SDK callback using this owner.
    _ancestor_directories: Vec<File>,
    _state: File,
    _cache: File,
}

impl RetainedSessionDirectories {
    pub(crate) fn prepare(root: &Path) -> Result<Self, MatrixSidecarConfigError> {
        let mut current =
            std::path::absolute(root).map_err(|_| MatrixSidecarConfigError::Unavailable)?;
        let mut missing = Vec::new();
        let mut directory = loop {
            match codex_utils_path::open_private_state_directory(&current) {
                Ok(directory) => break directory,
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    missing.push(current.clone());
                    current = current
                        .parent()
                        .ok_or(MatrixSidecarConfigError::Unavailable)?
                        .to_owned();
                }
                Err(_) => return Err(MatrixSidecarConfigError::Unavailable),
            }
        };
        let mut ancestor_directories = Vec::new();
        // Reuse the retained-registry protocol: every native acquisition
        // rejects reparse ancestry and creates with the private descriptor.
        // Existing unsafe state is rejected, never repaired or re-owned.
        for child in missing.into_iter().rev() {
            ancestor_directories.push(directory);
            directory = codex_utils_path::open_private_state_directory(&child)
                .map_err(|_| MatrixSidecarConfigError::Unavailable)?;
        }
        let state = codex_utils_path::open_private_state_directory(&root.join("state"))
            .map_err(|_| MatrixSidecarConfigError::Unavailable)?;
        let cache = codex_utils_path::open_private_state_directory(&root.join("cache"))
            .map_err(|_| MatrixSidecarConfigError::Unavailable)?;
        Ok(Self {
            directory,
            _ancestor_directories: ancestor_directories,
            _state: state,
            _cache: cache,
        })
    }
}

pub(crate) struct RetainedSessionStore {
    // The kernel lock fences independent SDK owners; the Mutex below only
    // serializes refresh callbacks sharing this particular Arc.
    _publication_lock: File,
    directories: RetainedSessionDirectories,
    access: Mutex<()>,
}

impl RetainedSessionStore {
    pub(crate) fn prepare(root: &Path) -> Result<Self, MatrixSidecarConfigError> {
        let directories = RetainedSessionDirectories::prepare(root)?;
        let publication_lock = codex_utils_path::open_private_state_child(
            &directories.directory,
            OWNER_LOCK_NAME,
            PrivateFileAccess::Create,
        )
        .map_err(|_| MatrixSidecarConfigError::Unavailable)?;
        if publication_lock
            .metadata()
            .map_err(|_| MatrixSidecarConfigError::Unavailable)?
            .len()
            != 0
        {
            return Err(MatrixSidecarConfigError::Unavailable);
        }
        // Never wait on another owner or reclaim its lock using a timeout.
        // This fixed private leaf is never renamed, truncated or unlinked.
        publication_lock
            .try_lock()
            .map_err(|_| MatrixSidecarConfigError::Unavailable)?;
        Ok(Self {
            _publication_lock: publication_lock,
            directories,
            access: Mutex::new(()),
        })
    }

    pub(crate) fn load(&self) -> Result<Option<MatrixSession>, MatrixSdkError> {
        let _access = self
            .access
            .lock()
            .map_err(|_| MatrixSdkError::Initialization)?;
        let file = match codex_utils_path::open_private_state_child(
            &self.directories.directory,
            SESSION_NAME,
            PrivateFileAccess::Read,
        ) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(MatrixSdkError::Initialization),
        };
        // Type, link count, owner and DACL were checked on this exact handle.
        let metadata = file
            .metadata()
            .map_err(|_| MatrixSdkError::Initialization)?;
        if metadata.len() == 0 || metadata.len() > MATRIX_SESSION_MAX_BYTES {
            return Err(MatrixSdkError::Initialization);
        }
        let mut bytes = Vec::new();
        file.take(MATRIX_SESSION_MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| MatrixSdkError::Initialization)?;
        if bytes.is_empty() || bytes.len() as u64 > MATRIX_SESSION_MAX_BYTES {
            return Err(MatrixSdkError::Initialization);
        }
        serde_json::from_slice(&bytes)
            .map(Some)
            .map_err(|_| MatrixSdkError::Initialization)
    }

    pub(crate) fn persist(&self, session: &MatrixSession) -> Result<(), MatrixSdkError> {
        let _access = self
            .access
            .lock()
            .map_err(|_| MatrixSdkError::Initialization)?;
        let bytes = serde_json::to_vec(session).map_err(|_| MatrixSdkError::Initialization)?;
        if bytes.is_empty() || bytes.len() as u64 > MATRIX_SESSION_MAX_BYTES {
            return Err(MatrixSdkError::Initialization);
        }
        codex_utils_path::private_state_child_exists(&self.directories.directory, SESSION_NAME)
            .map_err(|_| MatrixSdkError::Initialization)?;
        let mut next = codex_utils_path::open_private_state_child(
            &self.directories.directory,
            NEXT_SESSION_NAME,
            PrivateFileAccess::Create,
        )
        .map_err(|_| MatrixSdkError::Initialization)?;
        // One bounded next file is reused only after the original OS owner
        // verifies its exact handle. Do not truncate or clean up an unsafe leaf.
        next.set_len(/*size*/ 0)
            .and_then(|()| next.write_all(&bytes))
            .and_then(|()| next.sync_all())
            .map_err(|_| MatrixSdkError::Initialization)?;
        codex_utils_path::replace_private_state_child(
            &self.directories.directory,
            NEXT_SESSION_NAME,
            SESSION_NAME,
        )
        .map_err(|_| MatrixSdkError::Initialization)?;
        // The retained native handle has directory write access. Every actual
        // flush error remains an error, including after a successful rename.
        self.directories
            .directory
            .sync_all()
            .map_err(|_| MatrixSdkError::Initialization)
    }
}

#[cfg(test)]
#[path = "sdk_session_windows_tests.rs"]
mod tests;
