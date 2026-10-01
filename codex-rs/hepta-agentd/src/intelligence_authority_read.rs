//! Bound unauthenticated owner input before JSON parsing or signature work.

use super::MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES;
use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_types::StableId;
use std::fs::File;
use std::io::Read;
use std::path::Path;

pub(super) fn read_file(
    path: &Path,
    requested: &StableId,
) -> Result<Vec<u8>, CanonicalIntelligenceError> {
    let unavailable = || CanonicalIntelligenceError::FreshnessUnavailable(requested.clone());
    // Keep the Unix path policy, then validate the handle we actually consume.
    // A concurrent replacement must not make size/type/permission checks refer
    // to one file while the unbounded read opens another file.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let path_metadata = std::fs::symlink_metadata(path).map_err(|_| unavailable())?;
        if !path_metadata.is_file() || path_metadata.permissions().mode() & 0o022 != 0 {
            return Err(unavailable());
        }
    }
    let file = File::open(path).map_err(|_| unavailable())?;
    let metadata = file.metadata().map_err(|_| unavailable())?;
    if !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES
    {
        return Err(unavailable());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        let path_metadata = std::fs::symlink_metadata(path).map_err(|_| unavailable())?;
        if !path_metadata.is_file()
            || metadata.permissions().mode() & 0o022 != 0
            || path_metadata.dev() != metadata.dev()
            || path_metadata.ino() != metadata.ino()
        {
            return Err(unavailable());
        }
    }
    read_bytes(file, requested)
}

fn read_bytes<R: Read>(
    reader: R,
    requested: &StableId,
) -> Result<Vec<u8>, CanonicalIntelligenceError> {
    let mut bytes = Vec::new();
    reader
        .take(MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    // Metadata is only an early check: growth after that check must remain
    // bounded and fail before any deserialization or cryptographic allocation.
    if bytes.is_empty() || bytes.len() as u64 > MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(bytes)
}

#[cfg(test)]
#[path = "intelligence_authority_read_tests.rs"]
mod tests;
