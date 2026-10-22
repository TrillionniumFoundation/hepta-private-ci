//! Windows backing for the existing descriptor-bound SQLite recovery guard.
//! All input bytes come from retained private handles. SQLite still sees only
//! the new candidate, and the original owner still authenticates the exact cut.

use super::SqliteRecoveryError;
use codex_utils_path::RetainedPrivateStateDirectory;
use codex_utils_path::RetainedPrivateStateFile;
use std::ffi::OsString;
use std::io::Write;
use std::path::Path;

#[derive(Debug)]
pub(super) struct RetainedBundle {
    directory: RetainedPrivateStateDirectory,
    database: RetainedPrivateStateFile,
    sidecars: [(OsString, Option<RetainedPrivateStateFile>); 3],
}

impl RetainedBundle {
    pub(super) fn bind(path: &Path) -> Result<Self, SqliteRecoveryError> {
        let parent = path.parent().ok_or(SqliteRecoveryError::Indeterminate)?;
        let name = path.file_name().ok_or(SqliteRecoveryError::Indeterminate)?;
        let directory =
            RetainedPrivateStateDirectory::open_existing(parent).map_err(super::indeterminate)?;
        let database = directory
            .retain_file(name)
            .map_err(super::indeterminate)?
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        let mut sidecars = Vec::new();
        for suffix in ["-wal", "-shm", "-journal"] {
            let mut sidecar = name.to_os_string();
            sidecar.push(suffix);
            let retained = directory
                .retain_file(&sidecar)
                .map_err(super::indeterminate)?;
            sidecars.push((sidecar, retained));
        }
        let result = Self {
            directory,
            database,
            sidecars: sidecars
                .try_into()
                .map_err(|_| SqliteRecoveryError::Indeterminate)?,
        };
        result.revalidate()?;
        Ok(result)
    }

    pub(super) fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        self.directory
            .verify_unchanged()
            .map_err(super::indeterminate)?;
        self.directory
            .verify_file_unchanged(&self.database)
            .map_err(super::indeterminate)?;
        for (name, file) in &self.sidecars {
            match file {
                Some(file) => self
                    .directory
                    .verify_file_unchanged(file)
                    .map_err(super::indeterminate)?,
                None => {
                    if self
                        .directory
                        .retain_file(name)
                        .map_err(super::indeterminate)?
                        .is_some()
                    {
                        return Err(SqliteRecoveryError::Indeterminate);
                    }
                }
            }
        }
        self.directory
            .verify_unchanged()
            .map_err(super::indeterminate)
    }

    pub(super) fn cold_bytes(&self) -> Result<Vec<u8>, SqliteRecoveryError> {
        self.revalidate()?;
        if self.sidecars.iter().any(|(_, file)| file.is_some())
            || !(100..=128 * 1024 * 1024).contains(&self.database.len())
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let bytes = retained_bytes(&self.database)?;
        self.revalidate()?;
        Ok(bytes)
    }

    pub(super) fn materialize(&self, target: &Path) -> Result<(), SqliteRecoveryError> {
        const MAX_FILE_BYTES: u64 = 128 * 1024 * 1024;
        const MAX_BUNDLE_BYTES: u64 = 256 * 1024 * 1024;
        self.revalidate()?;
        let wal = self.sidecars[0].1.as_ref();
        let journal = self.sidecars[2].1.as_ref();
        let inputs = [Some(&self.database), wal, journal];
        let mut total = 0_u64;
        for file in inputs.into_iter().flatten() {
            if file.len() > MAX_FILE_BYTES {
                return Err(SqliteRecoveryError::Unavailable);
            }
            total = total
                .checked_add(file.len())
                .ok_or(SqliteRecoveryError::Unavailable)?;
        }
        if self.database.is_empty() || total > MAX_BUNDLE_BYTES {
            return Err(SqliteRecoveryError::Unavailable);
        }
        let database = retained_bytes(&self.database)?;
        let wal = wal.map(retained_bytes).transpose()?;
        let journal = journal.map(retained_bytes).transpose()?;
        self.revalidate()?;

        let name = target
            .file_name()
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        let output_names = ["", "-wal", "-shm", "-journal"].map(|suffix| {
            let mut name = name.to_os_string();
            name.push(suffix);
            name
        });
        for name in &output_names {
            if self
                .directory
                .retain_file(name)
                .map_err(super::indeterminate)?
                .is_some()
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
        }
        let output = [
            (&output_names[0], Some(database.as_slice())),
            (&output_names[1], wal.as_deref()),
            (&output_names[3], journal.as_deref()),
        ];
        let mut created = Vec::new();
        let result = (|| {
            for (name, bytes) in output {
                let Some(bytes) = bytes else { continue };
                let file = self
                    .directory
                    .create_new_file(name)
                    .map_err(super::indeterminate)?;
                // Record creation before the first fallible write so a partial
                // new output is included in failure cleanup. Never touch inputs.
                let index = created.len();
                created.push(file);
                let file = &mut created[index];
                file.write_all(bytes).map_err(super::indeterminate)?;
                file.sync_all().map_err(super::indeterminate)?;
            }
            Ok(())
        })();
        if result.is_err() {
            for file in created.into_iter().rev() {
                let _ = self.directory.discard_created_file(file);
            }
        }
        // Windows does not provide the Unix directory-fsync contract. Each new
        // file is flushed; the owner performs its existing publication/sync
        // transaction and retains any indeterminate post-publication result.
        result
    }
}

fn retained_bytes(file: &RetainedPrivateStateFile) -> Result<Vec<u8>, SqliteRecoveryError> {
    let length = usize::try_from(file.len()).map_err(|_| SqliteRecoveryError::Unavailable)?;
    let mut bytes = vec![0; length];
    file.read_exact_at(&mut bytes, 0)
        .map_err(super::indeterminate)?;
    Ok(bytes)
}

#[cfg(test)]
#[path = "sqlite_recovery_windows_tests.rs"]
mod tests;
