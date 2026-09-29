//! Create-only publication request identity beneath the existing owner fence.
//!
//! A durable publication checkpoint is meaningful only for one canonical request.
//! This sidecar binds that request before the first checkpoint is written, so a
//! terminal retry, crash recovery, or result replay cannot silently substitute a
//! different payload, admission, predecessor, or signed CURRENT witness.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAGIC: &str = "HEPTA-ARTIFACT-REQUEST-IDENTITY-V1";
const MAX_RECORD_BYTES: u64 = 4096;

#[derive(Debug)]
pub(super) enum DurableRequestIdentityError {
    Missing,
    Conflict,
    PersistenceUnknown(io::Error),
    Io(io::Error),
}

impl fmt::Display for DurableRequestIdentityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Missing => formatter.write_str("publication request identity is missing"),
            Self::Conflict => formatter.write_str("publication request identity conflicts"),
            Self::PersistenceUnknown(error) => {
                write!(formatter, "publication request identity persistence is unknown: {error}")
            }
            Self::Io(error) => write!(formatter, "publication request identity I/O failed: {error}"),
        }
    }
}

impl StdError for DurableRequestIdentityError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::PersistenceUnknown(error) | Self::Io(error) => Some(error),
            Self::Missing | Self::Conflict => None,
        }
    }
}

#[derive(Debug)]
pub(super) struct DurableRequestIdentity {
    directory: PathBuf,
    registry_id: StableId,
    scope: Digest32,
    binding: Digest32,
}

impl DurableRequestIdentity {
    pub(super) fn new(
        root: &Path,
        registry_id: &StableId,
        scope: Digest32,
        binding: Digest32,
    ) -> Self {
        Self {
            directory: root.join("writer").join("request-identities-v1"),
            registry_id: registry_id.clone(),
            scope,
            binding,
        }
    }

    fn path(&self, operation_id: &StableId) -> PathBuf {
        let name = Digest32::of_bytes(operation_id.as_str().as_bytes());
        self.directory.join(format!("{name}.v1"))
    }

    fn expected(&self, operation_id: &StableId, request_digest: Digest32) -> Vec<u8> {
        format!(
            "{MAGIC}\n{}\n{}\n{}\n{operation_id}\n{request_digest}\n",
            self.registry_id, self.scope, self.binding
        )
        .into_bytes()
    }

    fn validate_file(
        &self,
        operation_id: &StableId,
        request_digest: Digest32,
    ) -> Result<File, DurableRequestIdentityError> {
        let path = self.path(operation_id);
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return Err(DurableRequestIdentityError::Missing);
            }
            Err(error) => return Err(DurableRequestIdentityError::Io(error)),
        };
        if metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() > MAX_RECORD_BYTES
        {
            return Err(DurableRequestIdentityError::Conflict);
        }
        let mut file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .map_err(DurableRequestIdentityError::Io)?;
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_RECORD_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(DurableRequestIdentityError::Io)?;
        if bytes != self.expected(operation_id, request_digest) {
            return Err(DurableRequestIdentityError::Conflict);
        }
        Ok(file)
    }

    pub(super) fn verify(
        &self,
        operation_id: &StableId,
        request_digest: Digest32,
    ) -> Result<(), DurableRequestIdentityError> {
        self.validate_file(operation_id, request_digest).map(drop)
    }

    /// Persist the canonical identity before the first publication checkpoint.
    /// An exact retry re-synchronizes the same validated file. A conflicting or
    /// damaged record is never overwritten, repaired, or interpreted as a retry.
    pub(super) fn bind(
        &self,
        operation_id: &StableId,
        request_digest: Digest32,
    ) -> Result<(), DurableRequestIdentityError> {
        #[cfg(not(unix))]
        {
            let _ = (operation_id, request_digest);
            return Err(DurableRequestIdentityError::Io(io::Error::new(
                io::ErrorKind::Unsupported,
                "request identity directory durability is not qualified",
            )));
        }

        #[cfg(unix)]
        {
            let parent = self
                .directory
                .parent()
                .ok_or_else(|| DurableRequestIdentityError::Conflict)?;
            let parent_metadata = fs::symlink_metadata(parent)
                .map_err(DurableRequestIdentityError::Io)?;
            if parent_metadata.file_type().is_symlink() || !parent_metadata.is_dir() {
                return Err(DurableRequestIdentityError::Conflict);
            }
            let mut created_directory = false;
            match fs::DirBuilder::new().mode(0o700).create(&self.directory) {
                Ok(()) => created_directory = true,
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(DurableRequestIdentityError::Io(error)),
            }
            let directory_metadata = fs::symlink_metadata(&self.directory)
                .map_err(DurableRequestIdentityError::Io)?;
            if directory_metadata.file_type().is_symlink() || !directory_metadata.is_dir() {
                return Err(DurableRequestIdentityError::Conflict);
            }
            if created_directory {
                File::open(parent)
                    .and_then(|directory| directory.sync_all())
                    .map_err(DurableRequestIdentityError::PersistenceUnknown)?;
            }

            let expected = self.expected(operation_id, request_digest);
            let path = self.path(operation_id);
            let mut options = OpenOptions::new();
            options.write(true).create_new(true).mode(0o600);
            match options.open(path) {
                Ok(mut file) => {
                    file.write_all(&expected)
                        .and_then(|()| file.sync_all())
                        .map_err(DurableRequestIdentityError::PersistenceUnknown)?;
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    self.validate_file(operation_id, request_digest)?
                        .sync_all()
                        .map_err(DurableRequestIdentityError::PersistenceUnknown)?;
                }
                Err(error) => return Err(DurableRequestIdentityError::Io(error)),
            }
            File::open(&self.directory)
                .and_then(|directory| directory.sync_all())
                .map_err(DurableRequestIdentityError::PersistenceUnknown)
        }
    }
}
