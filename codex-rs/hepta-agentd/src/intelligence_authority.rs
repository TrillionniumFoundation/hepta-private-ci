//! Signed owner reads: live per stage, one immutable manifest per full fence.

use super::IntelligenceAuthorityFileV1;
use super::IntelligenceAuthorityOwnerFileV1;
use super::IntelligenceAuthorityVerifierV1;
use super::authority_read;
use super::verify_authority_file;
use codex_hepta_intelligence::CanonicalFreshnessOracleV1;
use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_intelligence::CanonicalIntelligenceSnapshotV1;
use codex_hepta_intelligence::CurrentOwnerStateV1;
use codex_hepta_intelligence::validate_current_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::str::FromStr;

pub(super) struct FileBackedFreshnessOracleV1 {
    path: PathBuf,
    verifier: IntelligenceAuthorityVerifierV1,
}

impl FileBackedFreshnessOracleV1 {
    pub(super) fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {
        Self { path, verifier }
    }

    /// Each complete fence reads anew. Worker stage checks continue to use the
    /// live `current` method, including checks after owner work has completed.
    pub(super) fn validate_snapshot(
        &self,
        snapshot: &CanonicalIntelligenceSnapshotV1,
    ) -> Result<(), CanonicalIntelligenceError> {
        validate_current_snapshot(snapshot, &mut self.snapshot_oracle())
    }

    pub(super) fn snapshot_oracle(&self) -> ManifestFreshnessOracleV1<'_> {
        ManifestFreshnessOracleV1 {
            source: self,
            manifest: None,
        }
    }

    fn read_manifest(
        &self,
        requested: &StableId,
    ) -> Result<AuthorityManifestV1, CanonicalIntelligenceError> {
        let unavailable = || CanonicalIntelligenceError::FreshnessUnavailable(requested.clone());
        let bytes = authority_read::read_file(&self.path, requested)?;
        let file: IntelligenceAuthorityFileV1 =
            serde_json::from_slice(&bytes).map_err(|_| unavailable())?;
        verify_authority_file(&file, &self.verifier, requested)?;
        if file.schema_version != 1 || file.authority_epoch == 0 {
            return Err(unavailable());
        }
        let frontier =
            Digest32::from_str(&file.revocation_frontier_digest).map_err(|_| unavailable())?;
        if frontier.is_zero() {
            return Err(unavailable());
        }
        let mut owners = BTreeMap::new();
        for owner in file.owners {
            let owner_id = StableId::new(owner.owner_id.clone()).map_err(|_| unavailable())?;
            if owners.insert(owner_id, owner).is_some() {
                return Err(unavailable());
            }
        }
        Ok(AuthorityManifestV1 {
            authority_epoch: file.authority_epoch,
            frontier,
            owners,
        })
    }
}

impl CanonicalFreshnessOracleV1 for FileBackedFreshnessOracleV1 {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        self.read_manifest(owner_id)?.current(owner_id)
    }
}

pub(super) struct ManifestFreshnessOracleV1<'a> {
    source: &'a FileBackedFreshnessOracleV1,
    manifest: Option<AuthorityManifestV1>,
}

impl CanonicalFreshnessOracleV1 for ManifestFreshnessOracleV1<'_> {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        if self.manifest.is_none() {
            self.manifest = Some(self.source.read_manifest(owner_id)?);
        }
        self.manifest
            .as_ref()
            .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(owner_id.clone()))?
            .current(owner_id)
    }
}

struct AuthorityManifestV1 {
    authority_epoch: u64,
    frontier: Digest32,
    owners: BTreeMap<StableId, IntelligenceAuthorityOwnerFileV1>,
}

impl AuthorityManifestV1 {
    fn current(
        &self,
        requested: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        let unavailable = || CanonicalIntelligenceError::FreshnessUnavailable(requested.clone());
        let owner = self.owners.get(requested).ok_or_else(unavailable)?;
        let generation = Generation::new(owner.generation).map_err(|_| unavailable())?;
        let implementation_digest =
            Digest32::from_str(&owner.implementation_digest).map_err(|_| unavailable())?;
        let key_digest = Digest32::from_str(&owner.key_digest).map_err(|_| unavailable())?;
        if implementation_digest.is_zero() || key_digest.is_zero() || owner.key_epoch == 0 {
            return Err(unavailable());
        }
        Ok(CurrentOwnerStateV1 {
            owner_id: requested.clone(),
            generation,
            implementation_digest,
            key_digest,
            key_epoch: owner.key_epoch,
            authority_epoch: self.authority_epoch,
            revocation_frontier_digest: self.frontier,
        })
    }
}
