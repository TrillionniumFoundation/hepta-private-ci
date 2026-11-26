//! Qualification-first hardening contracts for the NDU production boundary.
//!
//! These types deliberately separate a source-complete contract from external
//! deployment evidence.  In particular, a durable artifact binding is not an
//! assertion that a production artifact store has been qualified: the caller
//! must obtain it from the capability port selected by the production owner.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;
use crate::SubjectClass;

const MAX_HIERARCHY_DEPTH: usize = 4;
const MAX_IDENTIFIER_BYTES: usize = 256;
const MAX_LOCATOR_BYTES: usize = 512;
const MAX_CATALOG_RECORDS: usize = 4096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduHardeningError {
    EmptyDigest(&'static str),
    EmptyIdentifier(&'static str),
    IdentifierTooLong(&'static str),
    InvalidImmutableLocator,
    EmptyArtifact,
    InvalidSchemaRevision,
    InvalidRetentionEpoch,
    InvalidHierarchyDepth,
    InvalidHierarchyPath,
    HierarchySnapshotMismatch,
    HierarchyConflict {
        generation: u64,
        ancestor: String,
        descendant: String,
    },
    ConflictingStagedArtifact {
        generation: u64,
        subject: String,
    },
    RecordLimitExceeded,
    IdentityConflict,
    ProjectionNotPublished,
    ProjectionRevoked,
    AmbiguousLegacyProjection,
    LegacyArtifactMismatch,
    InvalidTrainingDataBinding,
    InvalidFiltrationContract,
    InvalidPromotionPolicy,
    CapabilityUnavailable(&'static str),
}

impl fmt::Display for NduHardeningError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduHardeningError {}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NduProjectionArtifactKindV2 {
    Preference,
    Utility,
    Coefficient,
}

impl NduProjectionArtifactKindV2 {
    const fn tag(self) -> u8 {
        match self {
            Self::Preference => 0,
            Self::Utility => 1,
            Self::Coefficient => 2,
        }
    }
}

/// Immutable, content-addressed artifact binding required by the V2 catalog.
/// Fields are private so callers cannot fabricate a validated binding with a
/// struct literal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduDurableProjectionArtifactV2 {
    projection_kind: NduProjectionArtifactKindV2,
    projection_digest: Digest32,
    immutable_locator: String,
    size_bytes: u64,
    schema_revision: u32,
    policy_digest: Digest32,
    provenance_digest: Digest32,
    retention_epoch: u64,
    binding_digest: Digest32,
}

impl NduDurableProjectionArtifactV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        projection_kind: NduProjectionArtifactKindV2,
        projection_digest: Digest32,
        immutable_locator: String,
        size_bytes: u64,
        schema_revision: u32,
        policy_digest: Digest32,
        provenance_digest: Digest32,
        retention_epoch: u64,
    ) -> Result<Self, NduHardeningError> {
        require_digest(projection_digest, "projection")?;
        require_digest(policy_digest, "policy")?;
        require_digest(provenance_digest, "provenance")?;
        if size_bytes == 0 {
            return Err(NduHardeningError::EmptyArtifact);
        }
        if schema_revision == 0 {
            return Err(NduHardeningError::InvalidSchemaRevision);
        }
        if retention_epoch == 0 {
            return Err(NduHardeningError::InvalidRetentionEpoch);
        }
        if immutable_locator.is_empty()
            || immutable_locator.len() > MAX_LOCATOR_BYTES
            || !immutable_locator.contains("://")
            || !immutable_locator.bytes().all(|byte| byte.is_ascii_graphic())
        {
            return Err(NduHardeningError::InvalidImmutableLocator);
        }
        let binding_digest = digest_artifact_binding(
            projection_kind,
            projection_digest,
            &immutable_locator,
            size_bytes,
            schema_revision,
            policy_digest,
            provenance_digest,
            retention_epoch,
        );
        Ok(Self {
            projection_kind,
            projection_digest,
            immutable_locator,
            size_bytes,
            schema_revision,
            policy_digest,
            provenance_digest,
            retention_epoch,
            binding_digest,
        })
    }

    #[must_use]
    pub const fn projection_kind(&self) -> NduProjectionArtifactKindV2 {
        self.projection_kind
    }

    #[must_use]
    pub const fn projection_digest(&self) -> Digest32 {
        self.projection_digest
    }

    #[must_use]
    pub fn immutable_locator(&self) -> &str {
        &self.immutable_locator
    }

    #[must_use]
    pub const fn size_bytes(&self) -> u64 {
        self.size_bytes
    }

    #[must_use]
    pub const fn schema_revision(&self) -> u32 {
        self.schema_revision
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub const fn provenance_digest(&self) -> Digest32 {
        self.provenance_digest
    }

    #[must_use]
    pub const fn retention_epoch(&self) -> u64 {
        self.retention_epoch
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    pub fn validate(&self) -> Result<(), NduHardeningError> {
        let rebuilt = Self::new(
            self.projection_kind,
            self.projection_digest,
            self.immutable_locator.clone(),
            self.size_bytes,
            self.schema_revision,
            self.policy_digest,
            self.provenance_digest,
            self.retention_epoch,
        )?;
        if rebuilt.binding_digest != self.binding_digest {
            return Err(NduHardeningError::LegacyArtifactMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduHierarchySnapshotProofV1 {
    hierarchy_id: String,
    canonical_path: Vec<String>,
    snapshot_digest: Digest32,
    proof_digest: Digest32,
}

impl NduHierarchySnapshotProofV1 {
    pub fn new(
        hierarchy_id: String,
        canonical_path: Vec<String>,
        snapshot_digest: Digest32,
    ) -> Result<Self, NduHardeningError> {
        validate_identifier(&hierarchy_id, "hierarchy id")?;
        require_digest(snapshot_digest, "hierarchy snapshot")?;
        if canonical_path.is_empty() || canonical_path.len() > MAX_HIERARCHY_DEPTH {
            return Err(NduHardeningError::InvalidHierarchyDepth);
        }
        let mut seen = BTreeSet::new();
        for node in &canonical_path {
            validate_identifier(node, "hierarchy path node")?;
            if !seen.insert(node) {
                return Err(NduHardeningError::InvalidHierarchyPath);
            }
        }
        let proof_digest = digest_hierarchy_proof(&hierarchy_id, &canonical_path, snapshot_digest);
        Ok(Self {
            hierarchy_id,
            canonical_path,
            snapshot_digest,
            proof_digest,
        })
    }

    #[must_use]
    pub fn hierarchy_id(&self) -> &str {
        &self.hierarchy_id
    }

    #[must_use]
    pub fn canonical_path(&self) -> &[String] {
        &self.canonical_path
    }

    #[must_use]
    pub const fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }

    pub fn validate_subject(
        &self,
        subject_id: &StableId,
        parent_subject_id: Option<&StableId>,
        subject_class: SubjectClass,
    ) -> Result<(), NduHardeningError> {
        let expected_depth = match subject_class {
            SubjectClass::System => 1,
            SubjectClass::Domain => 2,
            SubjectClass::Agent => 3,
            SubjectClass::Episode => 4,
        };
        if self.canonical_path.len() != expected_depth
            || self.canonical_path.last().map(String::as_str) != Some(subject_id.as_str())
        {
            return Err(NduHardeningError::InvalidHierarchyPath);
        }
        let expected_parent = self
            .canonical_path
            .len()
            .checked_sub(2)
            .and_then(|index| self.canonical_path.get(index))
            .map(String::as_str);
        if expected_parent != parent_subject_id.map(StableId::as_str) {
            return Err(NduHardeningError::InvalidHierarchyPath);
        }
        let expected = digest_hierarchy_proof(
            &self.hierarchy_id,
            &self.canonical_path,
            self.snapshot_digest,
        );
        if expected != self.proof_digest {
            return Err(NduHardeningError::InvalidHierarchyPath);
        }
        Ok(())
    }

    fn is_ancestor_of(&self, other: &Self) -> bool {
        self.hierarchy_id == other.hierarchy_id
            && self.snapshot_digest == other.snapshot_digest
            && self.canonical_path.len() < other.canonical_path.len()
            && other.canonical_path.starts_with(&self.canonical_path)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduAuthoritativeUpdateV1 {
    generation: Generation,
    subject_id: StableId,
    parent_subject_id: Option<StableId>,
    subject_class: SubjectClass,
    artifact_id: StableId,
    hierarchy: NduHierarchySnapshotProofV1,
}

impl NduAuthoritativeUpdateV1 {
    pub fn new(
        generation: Generation,
        subject_id: StableId,
        parent_subject_id: Option<StableId>,
        subject_class: SubjectClass,
        artifact_id: StableId,
        hierarchy: NduHierarchySnapshotProofV1,
    ) -> Result<Self, NduHardeningError> {
        hierarchy.validate_subject(&subject_id, parent_subject_id.as_ref(), subject_class)?;
        Ok(Self {
            generation,
            subject_id,
            parent_subject_id,
            subject_class,
            artifact_id,
            hierarchy,
        })
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn subject_id(&self) -> &StableId {
        &self.subject_id
    }

    #[must_use]
    pub fn parent_subject_id(&self) -> Option<&StableId> {
        self.parent_subject_id.as_ref()
    }

    #[must_use]
    pub const fn subject_class(&self) -> SubjectClass {
        self.subject_class
    }

    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.artifact_id
    }

    #[must_use]
    pub fn hierarchy(&self) -> &NduHierarchySnapshotProofV1 {
        &self.hierarchy
    }
}

/// Validates all ancestor/descendant relations against one authoritative path
/// proof.  Unlike the V1 helper, this rejects grandparent/grandchild updates in
/// the same generation even when the intermediate parent is absent.
pub fn validate_authoritative_staged_updates(
    updates: &[NduAuthoritativeUpdateV1],
) -> Result<(), NduHardeningError> {
    let mut subjects: BTreeMap<(u64, String), &NduAuthoritativeUpdateV1> = BTreeMap::new();
    for update in updates {
        update.hierarchy.validate_subject(
            &update.subject_id,
            update.parent_subject_id.as_ref(),
            update.subject_class,
        )?;
        let key = (update.generation.get(), update.subject_id.to_string());
        if let Some(existing) = subjects.get(&key) {
            if existing.artifact_id != update.artifact_id
                || existing.subject_class != update.subject_class
                || existing.parent_subject_id != update.parent_subject_id
                || existing.hierarchy.proof_digest != update.hierarchy.proof_digest
            {
                return Err(NduHardeningError::ConflictingStagedArtifact {
                    generation: update.generation.get(),
                    subject: update.subject_id.to_string(),
                });
            }
            continue;
        }
        subjects.insert(key, update);
    }

    for (index, left) in updates.iter().enumerate() {
        for right in updates.iter().skip(index + 1) {
            if left.generation != right.generation {
                continue;
            }
            if left.hierarchy.hierarchy_id == right.hierarchy.hierarchy_id
                && left.hierarchy.snapshot_digest != right.hierarchy.snapshot_digest
            {
                return Err(NduHardeningError::HierarchySnapshotMismatch);
            }
            let conflict = if left.hierarchy.is_ancestor_of(&right.hierarchy) {
                Some((&left.subject_id, &right.subject_id))
            } else if right.hierarchy.is_ancestor_of(&left.hierarchy) {
                Some((&right.subject_id, &left.subject_id))
            } else {
                None
            };
            if let Some((ancestor, descendant)) = conflict {
                return Err(NduHardeningError::HierarchyConflict {
                    generation: left.generation.get(),
                    ancestor: ancestor.to_string(),
                    descendant: descendant.to_string(),
                });
            }
        }
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionCatalogActionV2 {
    Publish,
    Select,
    Revoke,
}

impl NduProjectionCatalogActionV2 {
    const fn tag(self) -> u8 {
        match self {
            Self::Publish => 0,
            Self::Select => 1,
            Self::Revoke => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionCatalogEntryV2 {
    sequence: u64,
    action: NduProjectionCatalogActionV2,
    identity_digest: Digest32,
    objective_digest: Digest32,
    subject_digest: Digest32,
    projection_kind: NduProjectionArtifactKindV2,
    projection_digest: Digest32,
    artifact_binding_digest: Digest32,
    semantic_digest: Digest32,
    predecessor_entry_digest: Digest32,
    entry_digest: Digest32,
}

impl NduProjectionCatalogEntryV2 {
    #[must_use]
    pub const fn sequence(&self) -> u64 {
        self.sequence
    }

    #[must_use]
    pub const fn action(&self) -> NduProjectionCatalogActionV2 {
        self.action
    }

    #[must_use]
    pub const fn identity_digest(&self) -> Digest32 {
        self.identity_digest
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn subject_digest(&self) -> Digest32 {
        self.subject_digest
    }

    #[must_use]
    pub const fn projection_kind(&self) -> NduProjectionArtifactKindV2 {
        self.projection_kind
    }

    #[must_use]
    pub const fn projection_digest(&self) -> Digest32 {
        self.projection_digest
    }

    #[must_use]
    pub const fn artifact_binding_digest(&self) -> Digest32 {
        self.artifact_binding_digest
    }

    #[must_use]
    pub const fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }

    #[must_use]
    pub const fn predecessor_entry_digest(&self) -> Digest32 {
        self.predecessor_entry_digest
    }

    #[must_use]
    pub const fn entry_digest(&self) -> Digest32 {
        self.entry_digest
    }
}

type ProjectionKey = (
    Digest32,
    Digest32,
    NduProjectionArtifactKindV2,
    Digest32,
);
type SelectionKey = (Digest32, Digest32, NduProjectionArtifactKindV2);

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct NduProjectionCatalogV2 {
    entries: Vec<NduProjectionCatalogEntryV2>,
    identities: BTreeMap<Digest32, (Digest32, usize)>,
    artifacts: BTreeMap<ProjectionKey, NduDurableProjectionArtifactV2>,
    selected: BTreeMap<SelectionKey, Digest32>,
    revoked: BTreeSet<ProjectionKey>,
}

impl NduProjectionCatalogV2 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[must_use]
    pub fn entries(&self) -> &[NduProjectionCatalogEntryV2] {
        &self.entries
    }

    pub fn publish(
        &mut self,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        artifact: NduDurableProjectionArtifactV2,
    ) -> Result<NduProjectionCatalogEntryV2, NduHardeningError> {
        artifact.validate()?;
        let semantic = digest_catalog_semantics(
            NduProjectionCatalogActionV2::Publish,
            objective_digest,
            subject_digest,
            artifact.projection_kind,
            artifact.projection_digest,
            artifact.binding_digest,
        );
        if let Some(replay) = self.replay(identity_digest, semantic)? {
            return Ok(replay);
        }
        self.require_operation_digests(identity_digest, objective_digest, subject_digest)?;
        let key = (
            objective_digest,
            subject_digest,
            artifact.projection_kind,
            artifact.projection_digest,
        );
        if let Some(existing) = self.artifacts.get(&key) {
            if existing != &artifact {
                return Err(NduHardeningError::LegacyArtifactMismatch);
            }
        }
        let entry = self.append_entry(
            NduProjectionCatalogActionV2::Publish,
            identity_digest,
            objective_digest,
            subject_digest,
            artifact.projection_kind,
            artifact.projection_digest,
            artifact.binding_digest,
            semantic,
        )?;
        self.artifacts.insert(key, artifact);
        Ok(entry)
    }

    pub fn select(
        &mut self,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_kind: NduProjectionArtifactKindV2,
        projection_digest: Digest32,
    ) -> Result<NduProjectionCatalogEntryV2, NduHardeningError> {
        let key = (objective_digest, subject_digest, projection_kind, projection_digest);
        let binding_digest = self
            .artifacts
            .get(&key)
            .map(NduDurableProjectionArtifactV2::binding_digest)
            .unwrap_or(Digest32::ZERO);
        let semantic = digest_catalog_semantics(
            NduProjectionCatalogActionV2::Select,
            objective_digest,
            subject_digest,
            projection_kind,
            projection_digest,
            binding_digest,
        );
        if let Some(replay) = self.replay(identity_digest, semantic)? {
            return Ok(replay);
        }
        self.require_operation_digests(identity_digest, objective_digest, subject_digest)?;
        require_digest(projection_digest, "projection")?;
        if binding_digest.is_zero() {
            return Err(NduHardeningError::ProjectionNotPublished);
        }
        if self.revoked.contains(&key) {
            return Err(NduHardeningError::ProjectionRevoked);
        }
        let entry = self.append_entry(
            NduProjectionCatalogActionV2::Select,
            identity_digest,
            objective_digest,
            subject_digest,
            projection_kind,
            projection_digest,
            binding_digest,
            semantic,
        )?;
        self.selected.insert(
            (objective_digest, subject_digest, projection_kind),
            projection_digest,
        );
        Ok(entry)
    }

    pub fn revoke(
        &mut self,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_kind: NduProjectionArtifactKindV2,
        projection_digest: Digest32,
    ) -> Result<NduProjectionCatalogEntryV2, NduHardeningError> {
        let key = (objective_digest, subject_digest, projection_kind, projection_digest);
        let binding_digest = self
            .artifacts
            .get(&key)
            .map(NduDurableProjectionArtifactV2::binding_digest)
            .unwrap_or(Digest32::ZERO);
        let semantic = digest_catalog_semantics(
            NduProjectionCatalogActionV2::Revoke,
            objective_digest,
            subject_digest,
            projection_kind,
            projection_digest,
            binding_digest,
        );
        if let Some(replay) = self.replay(identity_digest, semantic)? {
            return Ok(replay);
        }
        self.require_operation_digests(identity_digest, objective_digest, subject_digest)?;
        require_digest(projection_digest, "projection")?;
        if binding_digest.is_zero() {
            return Err(NduHardeningError::ProjectionNotPublished);
        }
        let entry = self.append_entry(
            NduProjectionCatalogActionV2::Revoke,
            identity_digest,
            objective_digest,
            subject_digest,
            projection_kind,
            projection_digest,
            binding_digest,
            semantic,
        )?;
        self.revoked.insert(key);
        let selected_key = (objective_digest, subject_digest, projection_kind);
        if self.selected.get(&selected_key) == Some(&projection_digest) {
            self.selected.remove(&selected_key);
        }
        Ok(entry)
    }

    #[must_use]
    pub fn selected_artifact(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_kind: NduProjectionArtifactKindV2,
    ) -> Option<&NduDurableProjectionArtifactV2> {
        let digest = self
            .selected
            .get(&(objective_digest, subject_digest, projection_kind))?;
        self.artifacts
            .get(&(objective_digest, subject_digest, projection_kind, *digest))
    }

    pub fn migrate_from_v1<F>(
        legacy: &NduProjectionJournalV1,
        mut resolve_artifact: F,
    ) -> Result<Self, NduHardeningError>
    where
        F: FnMut(
            NduProjectionKindV1,
            Digest32,
            Digest32,
            Digest32,
        ) -> Result<NduDurableProjectionArtifactV2, NduHardeningError>,
    {
        let mut catalog = Self::new();
        for entry in legacy.entries() {
            match entry.kind {
                NduProjectionKindV1::Preference | NduProjectionKindV1::Utility => {
                    let artifact = resolve_artifact(
                        entry.kind,
                        entry.objective_digest,
                        entry.subject_digest,
                        entry.payload_digest,
                    )?;
                    let expected_kind = match entry.kind {
                        NduProjectionKindV1::Preference => {
                            NduProjectionArtifactKindV2::Preference
                        }
                        NduProjectionKindV1::Utility => NduProjectionArtifactKindV2::Utility,
                        NduProjectionKindV1::SelectedProjection
                        | NduProjectionKindV1::Revocation => unreachable!(),
                    };
                    if artifact.projection_kind != expected_kind
                        || artifact.projection_digest != entry.payload_digest
                    {
                        return Err(NduHardeningError::LegacyArtifactMismatch);
                    }
                    catalog.publish(
                        entry.identity_digest,
                        entry.objective_digest,
                        entry.subject_digest,
                        artifact,
                    )?;
                }
                NduProjectionKindV1::SelectedProjection => {
                    let kind = catalog.unique_legacy_kind(entry)?;
                    catalog.select(
                        entry.identity_digest,
                        entry.objective_digest,
                        entry.subject_digest,
                        kind,
                        entry.payload_digest,
                    )?;
                }
                NduProjectionKindV1::Revocation => {
                    let kind = catalog.unique_legacy_kind(entry)?;
                    catalog.revoke(
                        entry.identity_digest,
                        entry.objective_digest,
                        entry.subject_digest,
                        kind,
                        entry.payload_digest,
                    )?;
                }
            }
        }
        Ok(catalog)
    }

    fn unique_legacy_kind(
        &self,
        entry: &NduProjectionEntryV1,
    ) -> Result<NduProjectionArtifactKindV2, NduHardeningError> {
        let matches = [
            NduProjectionArtifactKindV2::Preference,
            NduProjectionArtifactKindV2::Utility,
            NduProjectionArtifactKindV2::Coefficient,
        ]
        .into_iter()
        .filter(|kind| {
            self.artifacts.contains_key(&(
                entry.objective_digest,
                entry.subject_digest,
                *kind,
                entry.payload_digest,
            ))
        })
        .collect::<Vec<_>>();
        match matches.as_slice() {
            [kind] => Ok(*kind),
            [] => Err(NduHardeningError::ProjectionNotPublished),
            _ => Err(NduHardeningError::AmbiguousLegacyProjection),
        }
    }

    fn require_operation_digests(
        &self,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<(), NduHardeningError> {
        require_digest(identity_digest, "operation identity")?;
        require_digest(objective_digest, "objective")?;
        require_digest(subject_digest, "subject")
    }

    fn replay(
        &self,
        identity_digest: Digest32,
        semantic_digest: Digest32,
    ) -> Result<Option<NduProjectionCatalogEntryV2>, NduHardeningError> {
        let Some((existing_semantic, index)) = self.identities.get(&identity_digest) else {
            return Ok(None);
        };
        if *existing_semantic != semantic_digest {
            return Err(NduHardeningError::IdentityConflict);
        }
        self.entries
            .get(*index)
            .cloned()
            .map(Some)
            .ok_or(NduHardeningError::IdentityConflict)
    }

    #[allow(clippy::too_many_arguments)]
    fn append_entry(
        &mut self,
        action: NduProjectionCatalogActionV2,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_kind: NduProjectionArtifactKindV2,
        projection_digest: Digest32,
        artifact_binding_digest: Digest32,
        semantic_digest: Digest32,
    ) -> Result<NduProjectionCatalogEntryV2, NduHardeningError> {
        if self.entries.len() >= MAX_CATALOG_RECORDS {
            return Err(NduHardeningError::RecordLimitExceeded);
        }
        let sequence = u64::try_from(self.entries.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(NduHardeningError::RecordLimitExceeded)?;
        let predecessor_entry_digest = self
            .entries
            .last()
            .map_or(Digest32::ZERO, NduProjectionCatalogEntryV2::entry_digest);
        let entry_digest = digest_catalog_entry(
            sequence,
            action,
            identity_digest,
            semantic_digest,
            predecessor_entry_digest,
        );
        let entry = NduProjectionCatalogEntryV2 {
            sequence,
            action,
            identity_digest,
            objective_digest,
            subject_digest,
            projection_kind,
            projection_digest,
            artifact_binding_digest,
            semantic_digest,
            predecessor_entry_digest,
            entry_digest,
        };
        let index = self.entries.len();
        self.identities
            .insert(identity_digest, (semantic_digest, index));
        self.entries.push(entry.clone());
        Ok(entry)
    }
}

/// Minimal capability port: the owner may request a fresh grant but cannot mint
/// one or enumerate broader authority.
pub trait NduGrantRefreshPort: Send + Sync {
    fn refresh_grant(&self, binding_digest: Digest32) -> Result<Digest32, NduHardeningError>;
}

pub trait NduRevocationPort: Send + Sync {
    fn current_frontier(&self) -> Result<Digest32, NduHardeningError>;
}

pub trait NduTrustedTimePort: Send + Sync {
    fn trusted_time_receipt(&self) -> Result<Digest32, NduHardeningError>;
}

pub trait NduProjectionArtifactPort: Send + Sync {
    fn verify_available(
        &self,
        artifact: &NduDurableProjectionArtifactV2,
    ) -> Result<Digest32, NduHardeningError>;
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct NduAuditMetricsV1 {
    oldest_pending_operation_age_ms: u64,
    journal_utilization_per_mille: u16,
    last_compaction_duration_ms: u64,
    last_replay_duration_ms: u64,
    poisoned_owner_count: u64,
    indeterminate_commit_count: u64,
    revocation_lag_ms: u64,
    artifact_unavailable_count: u64,
    grant_refresh_failure_count: u64,
    restore_monotonicity_failure_count: u64,
}

impl NduAuditMetricsV1 {
    #[must_use]
    pub const fn oldest_pending_operation_age_ms(&self) -> u64 {
        self.oldest_pending_operation_age_ms
    }

    #[must_use]
    pub const fn journal_utilization_per_mille(&self) -> u16 {
        self.journal_utilization_per_mille
    }

    #[must_use]
    pub const fn last_compaction_duration_ms(&self) -> u64 {
        self.last_compaction_duration_ms
    }

    #[must_use]
    pub const fn last_replay_duration_ms(&self) -> u64 {
        self.last_replay_duration_ms
    }

    #[must_use]
    pub const fn poisoned_owner_count(&self) -> u64 {
        self.poisoned_owner_count
    }

    #[must_use]
    pub const fn indeterminate_commit_count(&self) -> u64 {
        self.indeterminate_commit_count
    }

    #[must_use]
    pub const fn revocation_lag_ms(&self) -> u64 {
        self.revocation_lag_ms
    }

    #[must_use]
    pub const fn artifact_unavailable_count(&self) -> u64 {
        self.artifact_unavailable_count
    }

    #[must_use]
    pub const fn grant_refresh_failure_count(&self) -> u64 {
        self.grant_refresh_failure_count
    }

    #[must_use]
    pub const fn restore_monotonicity_failure_count(&self) -> u64 {
        self.restore_monotonicity_failure_count
    }

    pub fn observe_pending_age(&mut self, age_ms: u64) {
        self.oldest_pending_operation_age_ms =
            self.oldest_pending_operation_age_ms.max(age_ms);
    }

    pub fn observe_journal_utilization(&mut self, used: usize, capacity: usize) {
        self.journal_utilization_per_mille = if capacity == 0 {
            1_000
        } else {
            let scaled = used.saturating_mul(1_000) / capacity;
            u16::try_from(scaled.min(1_000)).unwrap_or(1_000)
        };
    }

    pub fn observe_compaction_duration(&mut self, duration_ms: u64) {
        self.last_compaction_duration_ms = duration_ms;
    }

    pub fn observe_replay_duration(&mut self, duration_ms: u64) {
        self.last_replay_duration_ms = duration_ms;
    }

    pub fn observe_revocation_lag(&mut self, lag_ms: u64) {
        self.revocation_lag_ms = lag_ms;
    }

    pub fn increment_poisoned_owner(&mut self) {
        self.poisoned_owner_count = self.poisoned_owner_count.saturating_add(1);
    }

    pub fn increment_indeterminate_commit(&mut self) {
        self.indeterminate_commit_count = self.indeterminate_commit_count.saturating_add(1);
    }

    pub fn increment_artifact_unavailable(&mut self) {
        self.artifact_unavailable_count = self.artifact_unavailable_count.saturating_add(1);
    }

    pub fn increment_grant_refresh_failure(&mut self) {
        self.grant_refresh_failure_count = self.grant_refresh_failure_count.saturating_add(1);
    }

    pub fn increment_restore_monotonicity_failure(&mut self) {
        self.restore_monotonicity_failure_count = self
            .restore_monotonicity_failure_count
            .saturating_add(1);
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduImmutableTrainingDataBindingV1 {
    dataset_digest: Digest32,
    immutable_locator: String,
    provenance_digest: Digest32,
    authorization_digest: Digest32,
    sample_count: u64,
    binding_digest: Digest32,
}

impl NduImmutableTrainingDataBindingV1 {
    pub fn new(
        dataset_digest: Digest32,
        immutable_locator: String,
        provenance_digest: Digest32,
        authorization_digest: Digest32,
        sample_count: u64,
    ) -> Result<Self, NduHardeningError> {
        require_digest(dataset_digest, "dataset")?;
        require_digest(provenance_digest, "dataset provenance")?;
        require_digest(authorization_digest, "dataset authorization")?;
        if sample_count == 0
            || immutable_locator.is_empty()
            || immutable_locator.len() > MAX_LOCATOR_BYTES
            || !immutable_locator.contains("://")
        {
            return Err(NduHardeningError::InvalidTrainingDataBinding);
        }
        let mut bytes = b"hepta.ndu.training-data-binding.v1\0".to_vec();
        bytes.extend_from_slice(dataset_digest.as_array());
        push_string(&mut bytes, &immutable_locator);
        bytes.extend_from_slice(provenance_digest.as_array());
        bytes.extend_from_slice(authorization_digest.as_array());
        bytes.extend_from_slice(&sample_count.to_be_bytes());
        let binding_digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            dataset_digest,
            immutable_locator,
            provenance_digest,
            authorization_digest,
            sample_count,
            binding_digest,
        })
    }

    #[must_use]
    pub const fn dataset_digest(&self) -> Digest32 {
        self.dataset_digest
    }

    #[must_use]
    pub fn immutable_locator(&self) -> &str {
        &self.immutable_locator
    }

    #[must_use]
    pub const fn provenance_digest(&self) -> Digest32 {
        self.provenance_digest
    }

    #[must_use]
    pub const fn authorization_digest(&self) -> Digest32 {
        self.authorization_digest
    }

    #[must_use]
    pub const fn sample_count(&self) -> u64 {
        self.sample_count
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFiltrationContractV1 {
    trusted_time_source_digest: Digest32,
    information_set_digest: Digest32,
    no_future_data_receipt_digest: Digest32,
    cutoff_epoch_millis: u64,
    contract_digest: Digest32,
}

impl NduFiltrationContractV1 {
    pub fn new(
        trusted_time_source_digest: Digest32,
        information_set_digest: Digest32,
        no_future_data_receipt_digest: Digest32,
        cutoff_epoch_millis: u64,
    ) -> Result<Self, NduHardeningError> {
        require_digest(trusted_time_source_digest, "trusted time source")?;
        require_digest(information_set_digest, "information set")?;
        require_digest(no_future_data_receipt_digest, "no future data receipt")?;
        if cutoff_epoch_millis == 0 {
            return Err(NduHardeningError::InvalidFiltrationContract);
        }
        let mut bytes = b"hepta.ndu.filtration-contract.v1\0".to_vec();
        bytes.extend_from_slice(trusted_time_source_digest.as_array());
        bytes.extend_from_slice(information_set_digest.as_array());
        bytes.extend_from_slice(no_future_data_receipt_digest.as_array());
        bytes.extend_from_slice(&cutoff_epoch_millis.to_be_bytes());
        let contract_digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            trusted_time_source_digest,
            information_set_digest,
            no_future_data_receipt_digest,
            cutoff_epoch_millis,
            contract_digest,
        })
    }

    #[must_use]
    pub const fn trusted_time_source_digest(&self) -> Digest32 {
        self.trusted_time_source_digest
    }

    #[must_use]
    pub const fn information_set_digest(&self) -> Digest32 {
        self.information_set_digest
    }

    #[must_use]
    pub const fn no_future_data_receipt_digest(&self) -> Digest32 {
        self.no_future_data_receipt_digest
    }

    #[must_use]
    pub const fn cutoff_epoch_millis(&self) -> u64 {
        self.cutoff_epoch_millis
    }

    #[must_use]
    pub const fn contract_digest(&self) -> Digest32 {
        self.contract_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduShadowPromotionPolicyV1 {
    minimum_shadow_samples: u64,
    minimum_independent_runs: u32,
    require_convergence: bool,
    require_calibration: bool,
    require_utility_improvement: bool,
    require_regression_acceptance: bool,
}

impl NduShadowPromotionPolicyV1 {
    pub fn new(
        minimum_shadow_samples: u64,
        minimum_independent_runs: u32,
    ) -> Result<Self, NduHardeningError> {
        if minimum_shadow_samples == 0 || minimum_independent_runs < 2 {
            return Err(NduHardeningError::InvalidPromotionPolicy);
        }
        Ok(Self {
            minimum_shadow_samples,
            minimum_independent_runs,
            require_convergence: true,
            require_calibration: true,
            require_utility_improvement: true,
            require_regression_acceptance: true,
        })
    }

    #[must_use]
    pub const fn minimum_shadow_samples(&self) -> u64 {
        self.minimum_shadow_samples
    }

    #[must_use]
    pub const fn minimum_independent_runs(&self) -> u32 {
        self.minimum_independent_runs
    }

    #[must_use]
    pub const fn require_convergence(&self) -> bool {
        self.require_convergence
    }

    #[must_use]
    pub const fn require_calibration(&self) -> bool {
        self.require_calibration
    }

    #[must_use]
    pub const fn require_utility_improvement(&self) -> bool {
        self.require_utility_improvement
    }

    #[must_use]
    pub const fn require_regression_acceptance(&self) -> bool {
        self.require_regression_acceptance
    }
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduHardeningError> {
    if value.is_zero() {
        Err(NduHardeningError::EmptyDigest(field))
    } else {
        Ok(())
    }
}

fn validate_identifier(value: &str, field: &'static str) -> Result<(), NduHardeningError> {
    if value.is_empty() {
        return Err(NduHardeningError::EmptyIdentifier(field));
    }
    if value.len() > MAX_IDENTIFIER_BYTES {
        return Err(NduHardeningError::IdentifierTooLong(field));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn digest_artifact_binding(
    projection_kind: NduProjectionArtifactKindV2,
    projection_digest: Digest32,
    immutable_locator: &str,
    size_bytes: u64,
    schema_revision: u32,
    policy_digest: Digest32,
    provenance_digest: Digest32,
    retention_epoch: u64,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.durable-projection-artifact.v2\0".to_vec();
    bytes.push(projection_kind.tag());
    bytes.extend_from_slice(projection_digest.as_array());
    push_string(&mut bytes, immutable_locator);
    bytes.extend_from_slice(&size_bytes.to_be_bytes());
    bytes.extend_from_slice(&schema_revision.to_be_bytes());
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(provenance_digest.as_array());
    bytes.extend_from_slice(&retention_epoch.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_hierarchy_proof(
    hierarchy_id: &str,
    canonical_path: &[String],
    snapshot_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.hierarchy-snapshot-proof.v1\0".to_vec();
    push_string(&mut bytes, hierarchy_id);
    bytes.extend_from_slice(
        &u32::try_from(canonical_path.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for node in canonical_path {
        push_string(&mut bytes, node);
    }
    bytes.extend_from_slice(snapshot_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_catalog_semantics(
    action: NduProjectionCatalogActionV2,
    objective_digest: Digest32,
    subject_digest: Digest32,
    projection_kind: NduProjectionArtifactKindV2,
    projection_digest: Digest32,
    artifact_binding_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.projection-catalog-semantics.v2\0".to_vec();
    bytes.push(action.tag());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(subject_digest.as_array());
    bytes.push(projection_kind.tag());
    bytes.extend_from_slice(projection_digest.as_array());
    bytes.extend_from_slice(artifact_binding_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_catalog_entry(
    sequence: u64,
    action: NduProjectionCatalogActionV2,
    identity_digest: Digest32,
    semantic_digest: Digest32,
    predecessor_entry_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.projection-catalog-entry.v2\0".to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.push(action.tag());
    bytes.extend_from_slice(identity_digest.as_array());
    bytes.extend_from_slice(semantic_digest.as_array());
    bytes.extend_from_slice(predecessor_entry_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid stable id")
    }

    fn artifact(
        kind: NduProjectionArtifactKindV2,
        name: &str,
    ) -> NduDurableProjectionArtifactV2 {
        NduDurableProjectionArtifactV2::new(
            kind,
            digest(name),
            format!("artifact://sha256/{name}"),
            128,
            1,
            digest("policy"),
            digest("provenance"),
            1,
        )
        .expect("valid artifact")
    }

    #[test]
    fn authoritative_hierarchy_rejects_non_adjacent_ancestor_updates() {
        let snapshot = digest("snapshot");
        let generation = Generation::new(7).expect("generation");
        let system = NduAuthoritativeUpdateV1::new(
            generation,
            id("system"),
            None,
            SubjectClass::System,
            id("system-artifact"),
            NduHierarchySnapshotProofV1::new(
                "root".to_string(),
                vec!["system".to_string()],
                snapshot,
            )
            .expect("system proof"),
        )
        .expect("system update");
        let agent = NduAuthoritativeUpdateV1::new(
            generation,
            id("agent"),
            Some(id("domain")),
            SubjectClass::Agent,
            id("agent-artifact"),
            NduHierarchySnapshotProofV1::new(
                "root".to_string(),
                vec![
                    "system".to_string(),
                    "domain".to_string(),
                    "agent".to_string(),
                ],
                snapshot,
            )
            .expect("agent proof"),
        )
        .expect("agent update");

        assert!(matches!(
            validate_authoritative_staged_updates(&[system, agent]),
            Err(NduHardeningError::HierarchyConflict { .. })
        ));
    }

    #[test]
    fn authoritative_hierarchy_allows_siblings_from_one_snapshot() {
        let snapshot = digest("snapshot");
        let generation = Generation::new(9).expect("generation");
        let left = NduAuthoritativeUpdateV1::new(
            generation,
            id("left"),
            Some(id("domain")),
            SubjectClass::Agent,
            id("left-artifact"),
            NduHierarchySnapshotProofV1::new(
                "root".to_string(),
                vec![
                    "system".to_string(),
                    "domain".to_string(),
                    "left".to_string(),
                ],
                snapshot,
            )
            .expect("left proof"),
        )
        .expect("left update");
        let right = NduAuthoritativeUpdateV1::new(
            generation,
            id("right"),
            Some(id("domain")),
            SubjectClass::Agent,
            id("right-artifact"),
            NduHierarchySnapshotProofV1::new(
                "root".to_string(),
                vec![
                    "system".to_string(),
                    "domain".to_string(),
                    "right".to_string(),
                ],
                snapshot,
            )
            .expect("right proof"),
        )
        .expect("right update");

        validate_authoritative_staged_updates(&[left, right]).expect("siblings are independent");
    }

    #[test]
    fn projection_kind_scopes_selection_and_revocation() {
        let objective = digest("objective");
        let subject = digest("subject");
        let preference = artifact(NduProjectionArtifactKindV2::Preference, "preference");
        let utility = artifact(NduProjectionArtifactKindV2::Utility, "utility");
        let coefficient = artifact(NduProjectionArtifactKindV2::Coefficient, "coefficient");
        let mut catalog = NduProjectionCatalogV2::new();
        for (identity, item) in [
            ("publish-preference", preference.clone()),
            ("publish-utility", utility.clone()),
            ("publish-coefficient", coefficient.clone()),
        ] {
            catalog
                .publish(digest(identity), objective, subject, item)
                .expect("publish");
        }
        for (identity, item) in [
            ("select-preference", &preference),
            ("select-utility", &utility),
            ("select-coefficient", &coefficient),
        ] {
            catalog
                .select(
                    digest(identity),
                    objective,
                    subject,
                    item.projection_kind(),
                    item.projection_digest(),
                )
                .expect("select");
        }
        catalog
            .revoke(
                digest("revoke-utility"),
                objective,
                subject,
                NduProjectionArtifactKindV2::Utility,
                utility.projection_digest(),
            )
            .expect("revoke utility");

        assert_eq!(
            catalog
                .selected_artifact(
                    objective,
                    subject,
                    NduProjectionArtifactKindV2::Preference,
                )
                .map(NduDurableProjectionArtifactV2::projection_digest),
            Some(preference.projection_digest())
        );
        assert!(catalog
            .selected_artifact(objective, subject, NduProjectionArtifactKindV2::Utility)
            .is_none());
        assert_eq!(
            catalog
                .selected_artifact(
                    objective,
                    subject,
                    NduProjectionArtifactKindV2::Coefficient,
                )
                .map(NduDurableProjectionArtifactV2::projection_digest),
            Some(coefficient.projection_digest())
        );
    }

    #[test]
    fn catalog_replay_precedes_current_revocation_state() {
        let objective = digest("objective");
        let subject = digest("subject");
        let artifact = artifact(NduProjectionArtifactKindV2::Preference, "projection");
        let mut catalog = NduProjectionCatalogV2::new();
        catalog
            .publish(
                digest("publish"),
                objective,
                subject,
                artifact.clone(),
            )
            .expect("publish");
        let selected = catalog
            .select(
                digest("select"),
                objective,
                subject,
                artifact.projection_kind(),
                artifact.projection_digest(),
            )
            .expect("select");
        catalog
            .revoke(
                digest("revoke"),
                objective,
                subject,
                artifact.projection_kind(),
                artifact.projection_digest(),
            )
            .expect("revoke");
        let replay = catalog
            .select(
                digest("select"),
                objective,
                subject,
                artifact.projection_kind(),
                artifact.projection_digest(),
            )
            .expect("terminal replay");
        assert_eq!(replay, selected);
        assert_eq!(catalog.entries().len(), 3);
        assert_eq!(
            catalog
                .select(
                    digest("new-select"),
                    objective,
                    subject,
                    artifact.projection_kind(),
                    artifact.projection_digest(),
                )
                .expect_err("new operation honors revocation"),
            NduHardeningError::ProjectionRevoked
        );
    }

    #[test]
    fn v1_migration_requires_durable_artifact_resolution() {
        let objective = digest("objective");
        let subject = digest("subject");
        let projection = digest("legacy-preference");
        let mut legacy = NduProjectionJournalV1::new();
        legacy
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("publish"),
                objective,
                subject,
                projection,
            )
            .expect("legacy publish");
        legacy
            .select_projection(digest("select"), objective, subject, projection)
            .expect("legacy select");
        let catalog = NduProjectionCatalogV2::migrate_from_v1(
            &legacy,
            |kind, _objective, _subject, projection_digest| {
                assert_eq!(kind, NduProjectionKindV1::Preference);
                NduDurableProjectionArtifactV2::new(
                    NduProjectionArtifactKindV2::Preference,
                    projection_digest,
                    "artifact://sha256/legacy-preference".to_string(),
                    256,
                    1,
                    digest("policy"),
                    digest("provenance"),
                    1,
                )
            },
        )
        .expect("migration");
        assert_eq!(
            catalog
                .selected_artifact(
                    objective,
                    subject,
                    NduProjectionArtifactKindV2::Preference,
                )
                .map(NduDurableProjectionArtifactV2::projection_digest),
            Some(projection)
        );
    }

    #[test]
    fn learned_promotion_contract_is_explicitly_evidence_gated() {
        let data = NduImmutableTrainingDataBindingV1::new(
            digest("dataset"),
            "artifact://sha256/dataset".to_string(),
            digest("provenance"),
            digest("authorization"),
            10_000,
        )
        .expect("training data binding");
        let filtration = NduFiltrationContractV1::new(
            digest("trusted-time"),
            digest("information-set"),
            digest("no-future-data"),
            1_000,
        )
        .expect("filtration");
        let promotion = NduShadowPromotionPolicyV1::new(10_000, 2).expect("promotion policy");

        assert!(!data.binding_digest().is_zero());
        assert!(!filtration.contract_digest().is_zero());
        assert!(promotion.require_convergence());
        assert!(promotion.require_calibration());
        assert!(promotion.require_utility_improvement());
        assert!(promotion.require_regression_acceptance());
    }
}
