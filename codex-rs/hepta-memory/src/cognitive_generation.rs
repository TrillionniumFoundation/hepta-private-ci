//! Current owner generation read fences. No grants or database facts are owned here.
use super::CognitiveStoreError;
use super::unavailable;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
const COGNITIVE_GENERATION_LOCK_FILENAME: &str = ".cognitive-generation.lock";

/// Locks the owner generation pointer independently from the writer-open fence.
///
/// Ordinary writer handles use `CognitiveStoreOpenGuard`. Federation reads take
/// a shared generation lock only for the bounded read/revalidation operation,
/// while recovery takes this lock exclusively across source capture and active
/// pointer publication. The recovered writer may therefore keep its writer
/// fence exclusive without making current read-only federation unavailable.
#[derive(Debug)]
pub(crate) struct CognitiveStoreGenerationGuard {
    _file: File,
    _path: PathBuf,
}

pub(crate) struct CognitiveStoreReadGeneration {
    pub(super) _guard: CognitiveStoreGenerationGuard,
    pub(super) database_path: PathBuf,
}

impl CognitiveStoreReadGeneration {
    pub(crate) fn database_path(&self) -> &Path {
        &self.database_path
    }
}

impl CognitiveStoreGenerationGuard {
    fn open_lock_file(root: &Path, create: bool) -> Result<(File, PathBuf), CognitiveStoreError> {
        let path = root.join(COGNITIVE_GENERATION_LOCK_FILENAME);
        #[cfg(unix)]
        let file = {
            use std::os::unix::fs::OpenOptionsExt;
            OpenOptions::new()
                .read(true)
                .write(create)
                .create(create)
                .truncate(false)
                .mode(0o600)
                .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
                .open(&path)
                .map_err(unavailable)?
        };
        #[cfg(not(unix))]
        let file = OpenOptions::new()
            .read(true)
            .write(create)
            .create(create)
            .truncate(false)
            .open(&path)
            .map_err(unavailable)?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let metadata = file.metadata().map_err(unavailable)?;
            if !metadata.is_file() || metadata.nlink() != 1 || metadata.mode() & 0o7777 != 0o600 {
                return Err(CognitiveStoreError::Invalid(
                    "cognitive generation lock must be one private regular file".to_string(),
                ));
            }
        }
        Ok((file, path))
    }

    pub(super) fn ensure(root: &Path) -> Result<(), CognitiveStoreError> {
        let _ = Self::open_lock_file(root, true)?;
        Ok(())
    }

    pub(super) fn acquire_shared_existing(root: &Path) -> Result<Self, CognitiveStoreError> {
        let (file, path) = Self::open_lock_file(root, false)?;
        file.try_lock_shared().map_err(|error| {
            CognitiveStoreError::Unavailable(format!(
                "cognitive generation is fenced by recovery: {error}"
            ))
        })?;
        Ok(Self {
            _file: file,
            _path: path,
        })
    }

    pub(crate) fn acquire_exclusive_or_create(root: &Path) -> Result<Self, CognitiveStoreError> {
        let (file, path) = Self::open_lock_file(root, true)?;
        file.try_lock().map_err(|error| {
            CognitiveStoreError::Unavailable(format!(
                "cognitive recovery cannot fence active generation readers: {error}"
            ))
        })?;
        Ok(Self {
            _file: file,
            _path: path,
        })
    }
}
