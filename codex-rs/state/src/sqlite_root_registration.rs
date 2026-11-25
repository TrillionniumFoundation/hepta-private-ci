//! Persistent descriptor identity for a trusted Root source registration.

use super::SqliteConfig;
use super::SqliteRecoveryError;
use super::root_material::RootSqliteMaterialSource;
use std::path::Path;
use std::path::PathBuf;

/// Read-only registration evidence. These values identify files, not a Current
/// cut or write authority. Root persists them in its existing registration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RootSqliteMaterialIdentity {
    database_path: PathBuf,
    database_device: u64,
    database_inode: u64,
    directory_device: u64,
    directory_inode: u64,
}

impl RootSqliteMaterialIdentity {
    pub fn database_path(&self) -> &Path {
        &self.database_path
    }

    pub fn database_device(&self) -> u64 {
        self.database_device
    }

    pub fn database_inode(&self) -> u64 {
        self.database_inode
    }

    pub fn directory_device(&self) -> u64 {
        self.directory_device
    }

    pub fn directory_inode(&self) -> u64 {
        self.directory_inode
    }
}

/// Retains the original directory/database descriptors across publications.
/// The source may change its contents under the caller's original owner
/// transaction, but neither inode may change. Each capture gets a fresh full
/// metadata/sidecar snapshot and keeps all original byte limits. This type has
/// no automatic re-registration or authority/recovery operation.
#[derive(Debug)]
pub struct RootSqliteMaterialRegistration {
    identity: RootSqliteMaterialIdentity,
    #[cfg(unix)]
    retained: super::ExistingSqliteRecoveryGuard,
    #[cfg(unix)]
    registered_uid: u32,
}

impl RootSqliteMaterialRegistration {
    /// Check actual Root and the non-Root source UID before any source-path I/O.
    /// This is only a caller precondition, not registration or Current evidence.
    pub fn verify_caller(registered_uid: u32) -> Result<(), SqliteRecoveryError> {
        #[cfg(unix)]
        {
            super::OwnerRule::RegisteredRootSource(registered_uid)
                .expected_uid()
                .map(|_| ())
        }
        #[cfg(not(unix))]
        {
            let _ = registered_uid;
            Err(SqliteRecoveryError::Unavailable)
        }
    }

    /// Call only with the launcher's fixed source layout and registered UID,
    /// after the original factory has returned the sole recovered owner.
    pub fn bind_registered(
        config: &SqliteConfig,
        database: &Path,
        registered_uid: u32,
    ) -> Result<Self, SqliteRecoveryError> {
        Self::verify_caller(registered_uid)?;
        #[cfg(unix)]
        {
            if database.parent() != Some(config.home()) {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let retained = super::ExistingSqliteRecoveryGuard::bind_for_owner(
                database,
                super::OwnerRule::RegisteredRootSource(registered_uid),
            )?;
            let inner = &retained.inner;
            let identity = RootSqliteMaterialIdentity {
                database_path: database.to_path_buf(),
                database_device: inner.database.snapshot.device,
                database_inode: inner.database.snapshot.inode,
                directory_device: inner.parent.snapshot.device,
                directory_inode: inner.parent.snapshot.inode,
            };
            Ok(Self {
                identity,
                retained,
                registered_uid,
            })
        }
        #[cfg(not(unix))]
        {
            let _ = (config, database, registered_uid);
            Err(SqliteRecoveryError::Unavailable)
        }
    }

    pub fn identity(&self) -> &RootSqliteMaterialIdentity {
        &self.identity
    }

    /// Recheck path AND retained descriptor identities. Content/timestamps are
    /// intentionally sampled afresh for each subsequent bounded capture.
    pub fn verify_registered(&self) -> Result<(), SqliteRecoveryError> {
        #[cfg(unix)]
        {
            for object in [&self.retained.inner.parent, &self.retained.inner.database] {
                let expected = (object.snapshot.device, object.snapshot.inode);
                for metadata in [
                    std::fs::symlink_metadata(&object.path).map_err(super::indeterminate)?,
                    object.descriptor.metadata().map_err(super::indeterminate)?,
                ] {
                    let observed =
                        super::FileSnapshot::validated(&metadata, object.kind, object.owner_rule)?;
                    if (observed.device, observed.inode) != expected {
                        return Err(SqliteRecoveryError::Indeterminate);
                    }
                }
            }
            let parent = self
                .retained
                .inner
                .database_path
                .parent()
                .ok_or(SqliteRecoveryError::Indeterminate)?;
            if parent.canonicalize().map_err(super::indeterminate)? != parent {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            Ok(())
        }
        #[cfg(not(unix))]
        {
            Err(SqliteRecoveryError::Unavailable)
        }
    }

    /// Bind one fresh attempt to the retained generation. A pathname lookup
    /// may not silently select a new inode; the old descriptors remain held
    /// during both comparison and materialization, preventing inode reuse.
    pub fn bind_capture(
        &self,
        destination: &SqliteConfig,
    ) -> Result<RootSqliteMaterialSource, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            self.verify_registered()?;
            let source = SqliteConfig::from_sqlite_home(
                codex_utils_absolute_path::AbsolutePathBuf::try_from(
                    self.retained.inner.parent.path.clone(),
                )
                .map_err(super::indeterminate)?,
            );
            let capture = RootSqliteMaterialSource::bind_registered(
                &source,
                &self.identity.database_path,
                self.registered_uid,
                destination,
            )?;
            self.verify_registered()?;
            let observed = &capture.source.inner;
            if (
                observed.database.snapshot.device,
                observed.database.snapshot.inode,
            ) != (self.identity.database_device, self.identity.database_inode)
                || (
                    observed.parent.snapshot.device,
                    observed.parent.snapshot.inode,
                ) != (
                    self.identity.directory_device,
                    self.identity.directory_inode,
                )
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            Ok(capture)
        }
        #[cfg(not(unix))]
        {
            let _ = destination;
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}
