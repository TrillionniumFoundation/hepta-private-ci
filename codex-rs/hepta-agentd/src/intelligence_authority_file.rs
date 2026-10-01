//! Descriptor-bound, size-bounded reads of the signed intelligence authority file.
//!
//! Path and handle versions are checked before and after reading. Unix retains
//! the existing non-symlink regular-file and no group/world write policy. Stable
//! canonical aliases remain supported; a changed canonical destination fails.
//! The Unix immediate parent must be controlled by the file owner or root and
//! prohibit group/world writes; this excludes other users from the final entry.
//! Canonical ancestors obey the same ownership boundary, with trusted sticky
//! directories permitted above the immediate parent for private /tmp layouts.
//! This is a read-time currentness fence, not a lock on later authority updates.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::Metadata;
use std::io;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_intelligence::CanonicalFreshnessOracleV1;
use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_intelligence::CurrentOwnerStateV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::IntelligenceAuthorityFileV1;
use super::IntelligenceAuthorityVerifierV1;
use super::verify_authority_file;
#[cfg(unix)]
use crate::operator_namespace::OperatorNamespace;

const MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES: u64 = 64 * 1024;

pub(super) struct FileBackedFreshnessOracleV1 {
    path: PathBuf,
    verifier: IntelligenceAuthorityVerifierV1,
}

impl FileBackedFreshnessOracleV1 {
    pub(super) fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {
        Self { path, verifier }
    }

    fn read(
        &self,
        requested: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        let bytes = ValidatedAuthorityFile::open(&self.path)
            .and_then(ValidatedAuthorityFile::read)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let file: IntelligenceAuthorityFileV1 = serde_json::from_slice(&bytes)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        verify_authority_file(&file, &self.verifier, requested)?;
        if file.schema_version != 1 || file.authority_epoch == 0 {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        let frontier = Digest32::from_str(&file.revocation_frontier_digest)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        if frontier.is_zero() {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        let mut seen = BTreeMap::new();
        for owner in file.owners {
            let owner_id = StableId::new(owner.owner_id.clone())
                .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
            if seen.insert(owner_id.clone(), owner).is_some() {
                return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                    requested.clone(),
                ));
            }
        }
        let owner = seen
            .remove(requested)
            .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let generation = Generation::new(owner.generation)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let implementation_digest = Digest32::from_str(&owner.implementation_digest)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let key_digest = Digest32::from_str(&owner.key_digest)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        if implementation_digest.is_zero() || key_digest.is_zero() || owner.key_epoch == 0 {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        Ok(CurrentOwnerStateV1 {
            owner_id: requested.clone(),
            generation,
            implementation_digest,
            key_digest,
            key_epoch: owner.key_epoch,
            authority_epoch: file.authority_epoch,
            revocation_frontier_digest: frontier,
        })
    }
}

impl CanonicalFreshnessOracleV1 for FileBackedFreshnessOracleV1 {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        self.read(owner_id)
    }
}

struct ValidatedAuthorityFile {
    path: PathBuf,
    canonical_path: PathBuf,
    metadata: Metadata,
    #[cfg(unix)]
    namespace: OperatorNamespace,
    file: File,
}

impl ValidatedAuthorityFile {
    fn open(path: &Path) -> io::Result<Self> {
        let canonical_path = path.canonicalize()?;
        let metadata = validate_authority_file_path(path)?;
        #[cfg(unix)]
        let namespace = OperatorNamespace::capture(&canonical_path, &metadata)?;
        // Open the captured canonical destination so a redirecting alias cannot
        // choose a different entry between the checks and the open.
        let file = File::open(&canonical_path)?;
        let opened = file.metadata()?;
        validate_authority_file_metadata(&opened)?;
        if !same_authority_file_version(&metadata, &opened) {
            return Err(io::Error::other("authority file changed while opening"));
        }
        Ok(Self {
            path: path.to_path_buf(),
            canonical_path,
            metadata,
            #[cfg(unix)]
            namespace,
            file,
        })
    }

    fn read(mut self) -> io::Result<Vec<u8>> {
        let bytes = read_bounded_authority_file(&mut self.file)?;
        let after = validate_authority_file_path(&self.path)?;
        let opened_after = self.file.metadata()?;
        validate_authority_file_metadata(&opened_after)?;
        #[cfg(unix)]
        self.namespace.verify(&self.canonical_path, &after)?;
        if self.path.canonicalize()? != self.canonical_path
            || !same_authority_file_version(&self.metadata, &after)
            || !same_authority_file_version(&self.metadata, &opened_after)
            || bytes.len() as u64 != self.metadata.len()
        {
            return Err(io::Error::other("authority file changed while reading"));
        }
        Ok(bytes)
    }
}

fn read_bounded_authority_file(reader: impl Read) -> io::Result<Vec<u8>> {
    // Allocate only the fixed cap plus its overflow sentinel, even if the file
    // grows or is replaced after metadata validation.
    let mut bytes = Vec::with_capacity(MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES as usize + 1);
    reader
        .take(MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() as u64 > MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES {
        return Err(io::Error::other("authority file exceeds its byte bounds"));
    }
    Ok(bytes)
}

fn validate_authority_file_path(path: &Path) -> io::Result<Metadata> {
    #[cfg(unix)]
    let metadata = std::fs::symlink_metadata(path)?;
    #[cfg(not(unix))]
    let metadata = std::fs::metadata(path)?;
    validate_authority_file_metadata(&metadata)?;
    Ok(metadata)
}

fn validate_authority_file_metadata(metadata: &Metadata) -> io::Result<()> {
    if !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES
    {
        return Err(io::Error::other(
            "authority file must be a bounded regular file",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        if metadata.file_type().is_symlink() || metadata.permissions().mode() & 0o022 != 0 {
            return Err(io::Error::other("authority file permits untrusted writes"));
        }
    }
    Ok(())
}

#[cfg(unix)]
fn same_authority_file_version(before: &Metadata, after: &Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;

    let version = |metadata: &Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.uid(),
            metadata.mode(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    version(before) == version(after)
}

#[cfg(not(unix))]
fn same_authority_file_version(before: &Metadata, after: &Metadata) -> bool {
    // std does not expose a stable cross-platform inode identity. Keep the
    // existing non-Unix regular-file support and compare the available version
    // metadata; descriptor-bound bytes and the read cap hold on every platform.
    before.len() == after.len()
        && before.modified().ok() == after.modified().ok()
        && before.created().ok() == after.created().ok()
        && before.permissions().readonly() == after.permissions().readonly()
}

#[cfg(test)]
#[path = "intelligence_authority_file_tests.rs"]
mod tests;
