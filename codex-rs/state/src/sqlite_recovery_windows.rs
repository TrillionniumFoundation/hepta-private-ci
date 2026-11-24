//! Read-only retained objects for native Windows cold recovery inspection.

use std::fs::File;
use std::path::Path;
use std::sync::Arc;

use codex_utils_path::windows_private::Access;
use codex_utils_path::windows_private::PrivateSqliteDirectory;
use codex_utils_path::windows_private::Snapshot;

use super::RecoveryGuardInner;
use super::SqliteRecoveryError;
use super::indeterminate;

#[derive(Debug)]
pub(super) struct RetainedParent {
    pub(super) directory: Arc<PrivateSqliteDirectory>,
    pub(super) snapshot: Snapshot,
}

impl RetainedParent {
    pub(super) fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        self.directory
            .verify_unchanged(self.snapshot)
            .map_err(indeterminate)
    }
}

#[derive(Debug)]
pub(super) struct RetainedObject {
    pub(super) descriptor: File,
    directory: Arc<PrivateSqliteDirectory>,
    name: String,
    snapshot: Snapshot,
}

impl RetainedObject {
    fn bind(
        directory: &Arc<PrivateSqliteDirectory>,
        name: String,
    ) -> Result<Self, SqliteRecoveryError> {
        let descriptor = directory.open(&name, Access::Read).map_err(indeterminate)?;
        let snapshot = directory
            .file_snapshot(&descriptor)
            .map_err(indeterminate)?;
        Ok(Self {
            descriptor,
            directory: Arc::clone(directory),
            name,
            snapshot,
        })
    }

    pub(super) fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        self.directory
            .verify_file(&self.name, &self.descriptor, self.snapshot)
            .map_err(indeterminate)
    }
}

#[derive(Debug)]
pub(super) struct AbsentObject {
    directory: Arc<PrivateSqliteDirectory>,
    name: String,
}

#[derive(Debug)]
pub(super) enum RetainedOptionalObject {
    Absent(AbsentObject),
    Present(RetainedObject),
}

impl RetainedOptionalObject {
    fn bind(
        directory: &Arc<PrivateSqliteDirectory>,
        name: String,
    ) -> Result<Self, SqliteRecoveryError> {
        match directory.open(&name, Access::Read) {
            Ok(descriptor) => {
                let snapshot = directory
                    .file_snapshot(&descriptor)
                    .map_err(indeterminate)?;
                Ok(Self::Present(RetainedObject {
                    descriptor,
                    snapshot,
                    name,
                    directory: Arc::clone(directory),
                }))
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                Ok(Self::Absent(AbsentObject {
                    name,
                    directory: Arc::clone(directory),
                }))
            }
            Err(error) => Err(indeterminate(error)),
        }
    }

    pub(super) fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        match self {
            Self::Present(object) => object.revalidate(),
            Self::Absent(object) => match object.directory.open(&object.name, Access::Read) {
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
                Ok(_) | Err(_) => Err(SqliteRecoveryError::Indeterminate),
            },
        }
    }
}

pub(super) fn bind(path: &Path) -> Result<RecoveryGuardInner, SqliteRecoveryError> {
    let parent_path = path.parent().ok_or(SqliteRecoveryError::Indeterminate)?;
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(SqliteRecoveryError::Indeterminate)?;
    let directory = Arc::new(PrivateSqliteDirectory::inspect(parent_path).map_err(indeterminate)?);
    let snapshot = directory.snapshot().map_err(indeterminate)?;
    let database = RetainedObject::bind(&directory, name.to_string())?;
    let sidecars = ["-wal", "-shm", "-journal"]
        .map(|suffix| RetainedOptionalObject::bind(&directory, format!("{name}{suffix}")));
    let [wal, shm, journal] = sidecars;
    Ok(RecoveryGuardInner {
        database_path: path.to_path_buf(),
        parent: RetainedParent {
            directory,
            snapshot,
        },
        database,
        sidecars: [wal?, shm?, journal?],
    })
}
