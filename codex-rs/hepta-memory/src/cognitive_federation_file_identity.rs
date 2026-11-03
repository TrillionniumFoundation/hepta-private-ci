//! Request-local pool reuse requires the same canonical database file.
//! These checks preserve path freshness; they are not a recovery/current-cut witness.

use std::path::Path;

use crate::CognitiveStoreError;
use crate::cognitive_path::canonical_path_without_redirection;
use crate::cognitive_store::unavailable;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct FederationFileIdentity {
    #[cfg(unix)]
    device: u64,
    #[cfg(unix)]
    inode: u64,
}

pub(super) fn capture_file_identity(
    path: &Path,
) -> Result<Option<FederationFileIdentity>, CognitiveStoreError> {
    let metadata = std::fs::metadata(path).map_err(unavailable)?;
    if !metadata.is_file()
        || canonical_path_without_redirection(path)
            .map_err(unavailable)?
            .is_none()
    {
        return Err(CognitiveStoreError::Invalid(
            "federated authority database is not a canonical regular file".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;

        Ok(Some(FederationFileIdentity {
            device: metadata.dev(),
            inode: metadata.ino(),
        }))
    }
    #[cfg(not(unix))]
    {
        Ok(None)
    }
}

pub(super) fn require_file_identity(
    path: &Path,
    expected: Option<FederationFileIdentity>,
) -> Result<(), CognitiveStoreError> {
    if capture_file_identity(path)? != expected {
        return Err(CognitiveStoreError::Unavailable(
            "federated authority database file changed during this request".to_string(),
        ));
    }
    Ok(())
}
