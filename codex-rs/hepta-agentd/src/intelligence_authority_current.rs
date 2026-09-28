//! Secure currentness-manifest reader for the canonical intelligence runner.
//!
//! The signed manifest remains the authority owner's fact. This reader adds no
//! replacement authority store: it only persists the highest already-accepted
//! signed epoch/digest as an anti-rollback floor beside the host-owned manifest.
//! Reads use one opened handle with bounded I/O and verify that the path and
//! handle identify the same regular file.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde::Deserialize;
use serde::Serialize;

use super::*;

const AUTHORITY_ANCHOR_SCHEMA_VERSION: u32 = 1;
const MAX_AUTHORITY_ANCHOR_BYTES: u64 = 4 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct IntelligenceAuthorityAnchorV1 {
    schema_version: u32,
    authority_epoch: u64,
    manifest_digest: String,
}

pub(super) struct SecureFileBackedFreshnessOracleV1 {
    path: PathBuf,
    verifier: IntelligenceAuthorityVerifierV1,
    telemetry: Option<Arc<crate::AgentdIntelligenceTelemetryV1>>,
}

impl SecureFileBackedFreshnessOracleV1 {
    pub(super) fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {
        Self {
            path,
            verifier,
            telemetry: None,
        }
    }

    pub(super) fn new_observed(
        path: PathBuf,
        verifier: IntelligenceAuthorityVerifierV1,
        telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    ) -> Self {
        Self {
            path,
            verifier,
            telemetry: Some(telemetry),
        }
    }

    fn read(
        &self,
        requested: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        let bytes = read_bounded_regular_file(
            &self.path,
            MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES,
            requested,
        )?;
        let file: IntelligenceAuthorityFileV1 = serde_json::from_slice(&bytes)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        verify_authority_file(&file, &self.verifier, requested)?;
        if file.schema_version != 1 || file.authority_epoch == 0 {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        check_and_update_anchor(
            &self.path,
            file.authority_epoch,
            Digest32::of_bytes(&bytes),
            requested,
        )?;
        if let Some(telemetry) = self.telemetry.as_ref() {
            telemetry.record_authority_manifest(file.authority_epoch);
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

impl CanonicalFreshnessOracleV1 for SecureFileBackedFreshnessOracleV1 {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        self.read(owner_id)
    }
}

fn read_bounded_regular_file(
    path: &Path,
    maximum: u64,
    requested: &StableId,
) -> Result<Vec<u8>, CanonicalIntelligenceError> {
    validate_private_parent(path, requested)?;
    let path_metadata = std::fs::symlink_metadata(path)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    if path_metadata.file_type().is_symlink() || !path_metadata.is_file() {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    let file = OpenOptions::new()
        .read(true)
        .open(path)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    let opened_metadata = file
        .metadata()
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    validate_opened_identity(&path_metadata, &opened_metadata, requested)?;
    if opened_metadata.len() == 0 || opened_metadata.len() > maximum {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    let mut bytes = Vec::with_capacity(usize::try_from(opened_metadata.len()).unwrap_or(0));
    file.take(maximum.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    if bytes.is_empty() || u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn validate_private_parent(
    path: &Path,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    use std::os::unix::fs::PermissionsExt;

    let parent = path
        .parent()
        .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    let metadata = std::fs::symlink_metadata(parent)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || metadata.permissions().mode() & 0o022 != 0
    {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_private_parent(
    path: &Path,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    let parent = path
        .parent()
        .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    let metadata = std::fs::symlink_metadata(parent)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn validate_opened_identity(
    path: &std::fs::Metadata,
    opened: &std::fs::Metadata,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    if !opened.is_file()
        || opened.permissions().mode() & 0o022 != 0
        || path.dev() != opened.dev()
        || path.ino() != opened.ino()
    {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_opened_identity(
    _path: &std::fs::Metadata,
    opened: &std::fs::Metadata,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    if !opened.is_file() {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(())
}

fn check_and_update_anchor(
    manifest_path: &Path,
    authority_epoch: u64,
    manifest_digest: Digest32,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    let anchor_path = authority_anchor_path(manifest_path, requested)?;
    match load_anchor(&anchor_path, requested)? {
        Some(anchor) => match compare_anchor(&anchor, authority_epoch, manifest_digest, requested)? {
            AnchorDisposition::Current => return Ok(()),
            AnchorDisposition::Advance => {}
        },
        None => {}
    }

    let lock = AnchorDirectoryLock::acquire(&anchor_path, requested)?;
    match load_anchor(&anchor_path, requested)? {
        Some(anchor) => match compare_anchor(&anchor, authority_epoch, manifest_digest, requested)? {
            AnchorDisposition::Current => return Ok(()),
            AnchorDisposition::Advance => {}
        },
        None => {}
    }
    persist_anchor(
        &anchor_path,
        &IntelligenceAuthorityAnchorV1 {
            schema_version: AUTHORITY_ANCHOR_SCHEMA_VERSION,
            authority_epoch,
            manifest_digest: manifest_digest.to_string(),
        },
        requested,
    )?;
    drop(lock);
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AnchorDisposition {
    Current,
    Advance,
}

fn compare_anchor(
    anchor: &IntelligenceAuthorityAnchorV1,
    authority_epoch: u64,
    manifest_digest: Digest32,
    requested: &StableId,
) -> Result<AnchorDisposition, CanonicalIntelligenceError> {
    if anchor.schema_version != AUTHORITY_ANCHOR_SCHEMA_VERSION || anchor.authority_epoch == 0 {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    let anchored_digest = Digest32::from_str(&anchor.manifest_digest)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    if authority_epoch < anchor.authority_epoch
        || (authority_epoch == anchor.authority_epoch && manifest_digest != anchored_digest)
    {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(if authority_epoch == anchor.authority_epoch {
        AnchorDisposition::Current
    } else {
        AnchorDisposition::Advance
    })
}

fn authority_anchor_path(
    manifest_path: &Path,
    requested: &StableId,
) -> Result<PathBuf, CanonicalIntelligenceError> {
    let parent = manifest_path
        .parent()
        .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    let file_name = manifest_path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    Ok(parent.join(format!("{file_name}.anti-rollback.json")))
}

fn load_anchor(
    path: &Path,
    requested: &StableId,
) -> Result<Option<IntelligenceAuthorityAnchorV1>, CanonicalIntelligenceError> {
    if !path.exists() {
        return Ok(None);
    }
    let bytes = read_bounded_regular_file(path, MAX_AUTHORITY_ANCHOR_BYTES, requested)?;
    serde_json::from_slice(&bytes)
        .map(Some)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))
}

fn persist_anchor(
    path: &Path,
    anchor: &IntelligenceAuthorityAnchorV1,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    let bytes = serde_json::to_vec(anchor)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    if bytes.is_empty() || bytes.len() > MAX_AUTHORITY_ANCHOR_BYTES as usize {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?
        .as_nanos();
    let temporary = parent.join(format!(
        ".intelligence-authority-anchor-{}-{stamp}",
        std::process::id()
    ));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(&temporary)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    let result = file
        .write_all(&bytes)
        .and_then(|()| file.sync_all())
        .and_then(|()| std::fs::rename(&temporary, path))
        .and_then(|()| File::open(parent)?.sync_all());
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(())
}

struct AnchorDirectoryLock {
    path: PathBuf,
}

impl AnchorDirectoryLock {
    fn acquire(
        anchor_path: &Path,
        requested: &StableId,
    ) -> Result<Self, CanonicalIntelligenceError> {
        let parent = anchor_path
            .parent()
            .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let file_name = anchor_path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let path = parent.join(format!(".{file_name}.lock"));
        std::fs::create_dir(&path)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700))
                .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        }
        Ok(Self { path })
    }
}

impl Drop for AnchorDirectoryLock {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir(&self.path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn requested() -> StableId {
        StableId::new("objective.compiler").expect("owner id")
    }

    #[test]
    fn anti_rollback_anchor_rejects_older_epoch_and_same_epoch_substitution() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let manifest = directory.path().join("authority.json");
        std::fs::write(&manifest, b"placeholder").expect("manifest fixture");
        let owner = requested();
        let newer = Digest32::of_bytes(b"newer");
        check_and_update_anchor(&manifest, 9, newer, &owner).expect("anchor newer epoch");
        assert!(check_and_update_anchor(
            &manifest,
            8,
            Digest32::of_bytes(b"older"),
            &owner
        )
        .is_err());
        assert!(check_and_update_anchor(
            &manifest,
            9,
            Digest32::of_bytes(b"substituted"),
            &owner
        )
        .is_err());
        check_and_update_anchor(&manifest, 10, Digest32::of_bytes(b"next"), &owner)
            .expect("advance anchor");
    }

    #[cfg(unix)]
    #[test]
    fn bounded_reader_rejects_symlink_target() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().expect("temporary directory");
        let target = directory.path().join("target.json");
        let link = directory.path().join("authority.json");
        std::fs::write(&target, b"{}").expect("target");
        symlink(&target, &link).expect("symlink");
        assert!(read_bounded_regular_file(&link, 64, &requested()).is_err());
    }
}
