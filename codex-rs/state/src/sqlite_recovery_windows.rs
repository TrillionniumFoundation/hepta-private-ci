//! Read-only Windows identities and bounded recovery copies under a private root.

use std::fs::File;
use std::io;
use std::io::Write;
use std::os::windows::fs::FileExt;
use std::path::Path;
use std::path::PathBuf;

use codex_utils_path::normalize_for_native_workdir;
use codex_utils_path::windows_private_fs::FileSnapshot;
use codex_utils_path::windows_private_fs::PrivateDirectory;
use codex_utils_path::windows_private_fs::snapshot_private_file;

use super::SqliteRecoveryError;
use super::indeterminate;

const MAX_FILE_BYTES: u64 = 128 * 1024 * 1024;
const MAX_BUNDLE_BYTES: u64 = 256 * 1024 * 1024;
const SIDECAR_SUFFIXES: [&str; 3] = ["-wal", "-shm", "-journal"];

#[derive(Debug)]
pub(super) struct RetainedDatabase {
    parent_path: PathBuf,
    parent: PrivateDirectory,
    parent_snapshot: FileSnapshot,
    database: RetainedFile,
    sidecars: [Option<RetainedFile>; 3],
}

#[derive(Debug)]
struct RetainedFile {
    name: String,
    descriptor: File,
    snapshot: FileSnapshot,
}

impl RetainedFile {
    fn bind(parent: &PrivateDirectory, name: String) -> Result<Self, io::Error> {
        let descriptor = parent.open_read(&name)?;
        let snapshot = snapshot_private_file(&descriptor)?;
        Ok(Self {
            name,
            descriptor,
            snapshot,
        })
    }

    fn revalidate(&self, parent: &PrivateDirectory) -> Result<(), SqliteRecoveryError> {
        let current = parent.open_read(&self.name).map_err(indeterminate)?;
        if snapshot_private_file(&current).map_err(indeterminate)? != self.snapshot
            || snapshot_private_file(&self.descriptor).map_err(indeterminate)? != self.snapshot
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(())
    }

    fn read_bytes(&self, minimum: u64) -> Result<Vec<u8>, SqliteRecoveryError> {
        let length = self.snapshot.len();
        if !(minimum..=MAX_FILE_BYTES).contains(&length) {
            return Err(SqliteRecoveryError::Unavailable);
        }
        let length = usize::try_from(length).map_err(|_| SqliteRecoveryError::Unavailable)?;
        let mut bytes = vec![0; length];
        let mut position = 0;
        while position < bytes.len() {
            let count = self
                .descriptor
                .seek_read(&mut bytes[position..], position as u64)
                .map_err(indeterminate)?;
            if count == 0 {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            position += count;
        }
        Ok(bytes)
    }
}

impl RetainedDatabase {
    pub(super) fn bind(path: &Path) -> Result<Self, SqliteRecoveryError> {
        let parent_path = path.parent().ok_or(SqliteRecoveryError::Indeterminate)?;
        let canonical = parent_path.canonicalize().map_err(indeterminate)?;
        if normalize_for_native_workdir(&canonical) != normalize_for_native_workdir(parent_path) {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let name = path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        let parent =
            PrivateDirectory::open_existing_read_only(parent_path).map_err(indeterminate)?;
        let parent_snapshot = snapshot_private_file(parent.as_file()).map_err(indeterminate)?;
        let database = RetainedFile::bind(&parent, name.to_owned()).map_err(indeterminate)?;
        let mut sidecars = [None, None, None];
        for (slot, suffix) in sidecars.iter_mut().zip(SIDECAR_SUFFIXES) {
            *slot = match RetainedFile::bind(&parent, format!("{name}{suffix}")) {
                Ok(file) => Some(file),
                Err(error) if error.kind() == io::ErrorKind::NotFound => None,
                Err(_) => return Err(SqliteRecoveryError::Indeterminate),
            };
        }
        Ok(Self {
            parent_path: parent_path.to_path_buf(),
            parent,
            parent_snapshot,
            database,
            sidecars,
        })
    }

    pub(super) fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        let current =
            PrivateDirectory::open_existing_read_only(&self.parent_path).map_err(indeterminate)?;
        if snapshot_private_file(current.as_file()).map_err(indeterminate)? != self.parent_snapshot
            || snapshot_private_file(self.parent.as_file()).map_err(indeterminate)?
                != self.parent_snapshot
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        self.database.revalidate(&self.parent)?;
        for (sidecar, suffix) in self.sidecars.iter().zip(SIDECAR_SUFFIXES) {
            match sidecar {
                Some(file) => file.revalidate(&self.parent)?,
                None => {
                    let name = format!("{}{suffix}", self.database.name);
                    if self.parent.entry_exists(&name).map_err(indeterminate)? {
                        return Err(SqliteRecoveryError::Indeterminate);
                    }
                }
            }
        }
        Ok(())
    }

    pub(super) fn cold_bytes(&self) -> Result<Vec<u8>, SqliteRecoveryError> {
        if self.sidecars.iter().any(Option::is_some)
            || !(100..=MAX_FILE_BYTES).contains(&self.database.snapshot.len())
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        self.database.read_bytes(/*minimum*/ 100)
    }

    pub(super) fn materialize(&self, target: &Path) -> Result<(), SqliteRecoveryError> {
        let name = target
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        if target.parent() != Some(self.parent_path.as_path()) || name == self.database.name {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        self.revalidate()?;
        // SQLite may open every sidecar by the candidate's name, including SHM
        // that we never copy. A fresh generation requires the entire name set
        // to be absent, even when the source has no corresponding sidecar.
        for suffix in ["", "-wal", "-shm", "-journal"] {
            if self
                .parent
                .entry_exists(&format!("{name}{suffix}"))
                .map_err(indeterminate)?
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
        }
        // Check the aggregate before allocating any buffers. SHM is retained
        // for identity validation, but SQLite must rebuild it in the new copy.
        let total = [
            Some(&self.database),
            self.sidecars[0].as_ref(),
            self.sidecars[2].as_ref(),
        ]
        .into_iter()
        .flatten()
        .try_fold(0_u64, |total, file| total.checked_add(file.snapshot.len()))
        .ok_or(SqliteRecoveryError::Unavailable)?;
        if total > MAX_BUNDLE_BYTES {
            return Err(SqliteRecoveryError::Unavailable);
        }
        let database = self.database.read_bytes(/*minimum*/ 1)?;
        let wal = self.sidecars[0]
            .as_ref()
            .map(|file| file.read_bytes(/*minimum*/ 0))
            .transpose()?;
        let journal = self.sidecars[2]
            .as_ref()
            .map(|file| file.read_bytes(/*minimum*/ 0))
            .transpose()?;
        self.revalidate()?;
        let directory =
            PrivateDirectory::open_existing(&self.parent_path).map_err(indeterminate)?;
        if snapshot_private_file(directory.as_file()).map_err(indeterminate)?
            != self.parent_snapshot
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let mut created = Vec::new();
        let result = (|| {
            write_private(&directory, name, &database, &mut created)?;
            if let Some(bytes) = wal.as_deref() {
                write_private(&directory, &format!("{name}-wal"), bytes, &mut created)?;
            }
            if let Some(bytes) = journal.as_deref() {
                write_private(&directory, &format!("{name}-journal"), bytes, &mut created)?;
            }
            for suffix in ["", "-wal", "-shm", "-journal"] {
                let entry = format!("{name}{suffix}");
                let expected = created
                    .iter()
                    .find(|(created_name, _)| *created_name == entry);
                match (expected, directory.open_read(&entry)) {
                    (Some((_, retained)), Ok(current)) => {
                        if snapshot_private_file(&current).map_err(indeterminate)?
                            != snapshot_private_file(retained).map_err(indeterminate)?
                        {
                            return Err(SqliteRecoveryError::Indeterminate);
                        }
                    }
                    (None, Err(error)) if error.kind() == io::ErrorKind::NotFound => {}
                    _ => return Err(SqliteRecoveryError::Indeterminate),
                }
            }
            directory.sync_all().map_err(indeterminate)?;
            let current = PrivateDirectory::open_existing_read_only(&self.parent_path)
                .map_err(indeterminate)?;
            if !snapshot_private_file(current.as_file())
                .map_err(indeterminate)?
                .same_file(&self.parent_snapshot)
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            Ok(())
        })();
        if result.is_err() {
            for (name, file) in created.into_iter().rev() {
                if let Ok(snapshot) = snapshot_private_file(&file) {
                    let _ = directory.remove_if_unchanged(&name, &snapshot);
                }
            }
            let _ = directory.sync_all();
        }
        result
    }
}

fn write_private(
    directory: &PrivateDirectory,
    name: &str,
    bytes: &[u8],
    created: &mut Vec<(String, File)>,
) -> Result<(), SqliteRecoveryError> {
    let file = directory.create_new(name).map_err(indeterminate)?;
    let position = created.len();
    created.push((name.to_owned(), file));
    let file = &mut created[position].1;
    file.write_all(bytes).map_err(indeterminate)?;
    file.sync_all().map_err(indeterminate)
}

#[cfg(test)]
#[path = "sqlite_recovery_windows_tests.rs"]
mod tests;
