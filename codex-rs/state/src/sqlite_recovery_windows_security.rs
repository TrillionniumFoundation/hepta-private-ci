//! Read-only compatibility bridge; the canonical policy lives in utils-path.

use super::SqliteRecoveryError;
use codex_utils_path::PrivateSecurityIdentity;
use std::fs::File;

pub(super) fn private_security(file: &File) -> Result<Vec<u8>, SqliteRecoveryError> {
    PrivateSecurityIdentity::inspect(file)
        .map(|identity| identity.descriptor_bytes().to_vec())
        .map_err(|_| SqliteRecoveryError::Indeterminate)
}
