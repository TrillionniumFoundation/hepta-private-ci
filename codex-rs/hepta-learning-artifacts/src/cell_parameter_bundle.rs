//! Cell parameter bundle contract and owner-side compare-and-swap journal.
//!
//! `CellParameterBundleV1` is the artifact-owner contract used by a DecisionCell
//! successor.  It is deliberately a composition record: tensor bytes and their
//! manifests remain content addressed artifacts, while this record binds the
//! shared base, adapter/head inheritance, child identity, scope and lineage.
//! The owner stores immutable records and exposes no selection, activation or
//! runtime mutation authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

/// Stable contract identifier.  This is a source contract, not a wire alias
/// for `LearningArtifactManifestV2`.
pub const CELL_PARAMETER_BUNDLE_SCHEMA_V1: &str =
    "hepta.learning-artifacts.cell-parameter-bundle.v1";
/// The only authoritative writer for this contract.
pub const CELL_PARAMETER_BUNDLE_OWNER_V1: &str = "learning.artifacts";
const MAX_MANIFEST_ENTRIES: usize = 16;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CellComponentModeV1 {
    /// The child retains the exact parent artifact bytes.
    Cloned,
    /// The child has a fresh artifact and therefore cannot claim inheritance.
    Reinitialized,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct CasArtifactRefV1 {
    pub artifact_id: StableId,
    pub content_digest: Digest32,
    pub manifest_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub encoded_size_bytes: u64,
}

impl CasArtifactRefV1 {
    fn validate(&self, label: &'static str) -> Result<(), CellParameterBundleErrorV1> {
        if self.content_digest.is_zero() {
            return Err(CellParameterBundleErrorV1::EmptyDigest(label));
        }
        if self.manifest_digest.is_zero() {
            return Err(CellParameterBundleErrorV1::EmptyDigest("artifact manifest"));
        }
        if self.compatibility_digest.is_zero() {
            return Err(CellParameterBundleErrorV1::EmptyDigest("compatibility"));
        }
        if self.encoded_size_bytes == 0 {
            return Err(CellParameterBundleErrorV1::InvalidManifest(
                "artifact size must be non-zero",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellArtifactManifestV1 {
    pub manifest_id: StableId,
    pub cas_root_digest: Digest32,
    pub entries: Vec<CasArtifactRefV1>,
    pub manifest_digest: Digest32,
}

impl CellArtifactManifestV1 {
    /// Build and seal a deterministic manifest from the exact CAS entries.
    pub fn from_entries(
        manifest_id: StableId,
        mut entries: Vec<CasArtifactRefV1>,
    ) -> Result<Self, CellParameterBundleErrorV1> {
        entries.sort();
        let mut manifest = Self {
            manifest_id,
            cas_root_digest: Digest32::ZERO,
            entries,
            manifest_digest: Digest32::ZERO,
        };
        manifest.seal()?;
        Ok(manifest)
    }

    pub fn seal(&mut self) -> Result<(), CellParameterBundleErrorV1> {
        self.entries.sort();
        self.validate_shape()?;
        self.cas_root_digest = digest_cas_entries(&self.entries)?;
        self.manifest_digest = digest_manifest(self)?;
        Ok(())
    }

    pub fn validate(&self) -> Result<(), CellParameterBundleErrorV1> {
        self.validate_shape()?;
        if self.cas_root_digest != digest_cas_entries(&self.entries)? {
            return Err(CellParameterBundleErrorV1::DigestMismatch("CAS root"));
        }
        if self.manifest_digest != digest_manifest(self)? {
            return Err(CellParameterBundleErrorV1::DigestMismatch("manifest"));
        }
        Ok(())
    }

    fn validate_shape(&self) -> Result<(), CellParameterBundleErrorV1> {
        if self.entries.is_empty() || self.entries.len() > MAX_MANIFEST_ENTRIES {
            return Err(CellParameterBundleErrorV1::InvalidManifest(
                "manifest entry count is outside the bounded limit",
            ));
        }
        if self
            .entries
            .windows(2)
            .any(|pair| pair[0].artifact_id == pair[1].artifact_id)
        {
            return Err(CellParameterBundleErrorV1::InvalidManifest(
                "manifest contains duplicate artifact identities",
            ));
        }
        for entry in &self.entries {
            entry.validate("artifact bytes")?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellComponentRefV1 {
    pub component_id: StableId,
    pub mode: CellComponentModeV1,
    pub artifact: CasArtifactRefV1,
    /// For a clone this is the exact parent (or rollback target) artifact.
    /// Reinitialized components must leave it absent.
    pub source_artifact_digest: Option<Digest32>,
    pub compatibility_digest: Digest32,
}

impl CellComponentRefV1 {
    fn validate(&self, label: &'static str) -> Result<(), CellParameterBundleErrorV1> {
        self.artifact.validate(label)?;
        if self.compatibility_digest.is_zero() {
            return Err(CellParameterBundleErrorV1::EmptyDigest(
                "component compatibility",
            ));
        }
        match (self.mode, self.source_artifact_digest) {
            (CellComponentModeV1::Cloned, Some(source))
                if source == self.artifact.content_digest =>
            {
                Ok(())
            }
            (CellComponentModeV1::Cloned, _) => {
                Err(CellParameterBundleErrorV1::MalformedInheritance(
                    "clone source does not match artifact",
                ))
            }
            (CellComponentModeV1::Reinitialized, None) => Ok(()),
            (CellComponentModeV1::Reinitialized, Some(_)) => {
                Err(CellParameterBundleErrorV1::MalformedInheritance(
                    "reinitialized component cannot carry a clone source",
                ))
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellIdentityV1 {
    pub cell_id: StableId,
    pub child_id: StableId,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub lineage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellBundlePredecessorV1 {
    pub bundle_id: StableId,
    pub bundle_digest: Digest32,
    pub generation: Generation,
    pub lineage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellParameterBundleV1 {
    pub bundle_id: StableId,
    pub identity: CellIdentityV1,
    pub parent_predecessor: Option<CellBundlePredecessorV1>,
    pub shared_base: CasArtifactRefV1,
    pub adapter: CellComponentRefV1,
    pub head: CellComponentRefV1,
    pub state_schema_digest: Digest32,
    pub optimizer_lineage_digest: Digest32,
    pub artifact_manifest: CellArtifactManifestV1,
    /// Set only on an owner-created rollback successor.
    pub rollback_target: Option<CellBundlePredecessorV1>,
    pub bundle_digest: Digest32,
}

impl CellParameterBundleV1 {
    /// Computes all derived digests after the caller has supplied the immutable
    /// component references.  `seal` never repairs malformed inheritance.
    pub fn seal(&mut self) -> Result<(), CellParameterBundleErrorV1> {
        self.validate_shape()?;
        self.identity.lineage_digest =
            compute_lineage_digest(&self.identity, self.parent_predecessor.as_ref());
        self.artifact_manifest.seal()?;
        self.bundle_digest = digest_bundle(self)?;
        Ok(())
    }

    pub fn validate(&self) -> Result<(), CellParameterBundleErrorV1> {
        self.validate_shape()?;
        let expected_lineage =
            compute_lineage_digest(&self.identity, self.parent_predecessor.as_ref());
        if self.identity.lineage_digest != expected_lineage {
            return Err(CellParameterBundleErrorV1::DigestMismatch("cell lineage"));
        }
        self.artifact_manifest.validate()?;
        if self.bundle_digest != digest_bundle(self)? {
            return Err(CellParameterBundleErrorV1::DigestMismatch("bundle"));
        }
        Ok(())
    }

    fn validate_shape(&self) -> Result<(), CellParameterBundleErrorV1> {
        if self.identity.generation.get() == 0 {
            return Err(CellParameterBundleErrorV1::InvalidGeneration);
        }
        if self.identity.scope_digest.is_zero() {
            return Err(CellParameterBundleErrorV1::EmptyDigest("cell scope"));
        }
        if self.state_schema_digest.is_zero() {
            return Err(CellParameterBundleErrorV1::EmptyDigest("state schema"));
        }
        if self.optimizer_lineage_digest.is_zero() {
            return Err(CellParameterBundleErrorV1::EmptyDigest("optimizer lineage"));
        }
        self.shared_base.validate("shared base")?;
        self.adapter.validate("adapter")?;
        self.head.validate("head")?;
        let expected_artifacts = [
            &self.shared_base,
            &self.adapter.artifact,
            &self.head.artifact,
        ];
        if self.artifact_manifest.entries.len() != expected_artifacts.len()
            || expected_artifacts.iter().any(|artifact| {
                !self
                    .artifact_manifest
                    .entries
                    .iter()
                    .any(|entry| entry.artifact_id == artifact.artifact_id)
            })
        {
            return Err(CellParameterBundleErrorV1::InvalidManifest(
                "manifest must contain exactly the shared base, adapter and head",
            ));
        }
        if self.adapter.component_id == self.head.component_id {
            return Err(CellParameterBundleErrorV1::MalformedInheritance(
                "adapter and head identities must differ",
            ));
        }
        match self.parent_predecessor.as_ref() {
            None if self.identity.generation.get() == 1 => {}
            None => return Err(CellParameterBundleErrorV1::MissingPredecessor),
            Some(parent) => {
                if parent.bundle_digest.is_zero() || parent.lineage_digest.is_zero() {
                    return Err(CellParameterBundleErrorV1::EmptyDigest(
                        "parent predecessor",
                    ));
                }
                if parent.generation.get().checked_add(1) != Some(self.identity.generation.get()) {
                    return Err(CellParameterBundleErrorV1::InvalidGeneration);
                }
            }
        }
        if let Some(target) = &self.rollback_target {
            if target.bundle_digest.is_zero() || target.lineage_digest.is_zero() {
                return Err(CellParameterBundleErrorV1::EmptyDigest("rollback target"));
            }
            if self
                .parent_predecessor
                .as_ref()
                .map(|parent| &parent.bundle_id)
                == Some(&target.bundle_id)
            {
                return Err(CellParameterBundleErrorV1::RollbackConflict);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellParameterBundlePublishRequestV1 {
    pub operation_id: StableId,
    pub expected_head_digest: Digest32,
    pub bundle: CellParameterBundleV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellParameterBundleAppendDispositionV1 {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellParameterBundleReceiptV1 {
    pub disposition: CellParameterBundleAppendDispositionV1,
    pub operation_id: StableId,
    pub sequence: u64,
    pub bundle_id: StableId,
    pub bundle_digest: Digest32,
    pub predecessor_head_digest: Digest32,
    pub head_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellParameterBundleErrorV1 {
    EmptyScope,
    EmptyDigest(&'static str),
    InvalidGeneration,
    InvalidManifest(&'static str),
    MalformedInheritance(&'static str),
    MissingPredecessor,
    PredecessorNotFound(String),
    PredecessorMismatch,
    ScopeMismatch,
    DigestMismatch(&'static str),
    IdentityConflict(String),
    CasConflict,
    RollbackTargetNotFound(String),
    RollbackConflict,
    ReceiptMismatch,
    Capacity,
    Arithmetic,
}

impl fmt::Display for CellParameterBundleErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CellParameterBundleErrorV1 {}

fn compute_lineage_digest(
    identity: &CellIdentityV1,
    parent: Option<&CellBundlePredecessorV1>,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.cell-lineage.v1\0".to_vec();
    push_id(&mut bytes, &identity.cell_id);
    push_id(&mut bytes, &identity.child_id);
    bytes.extend_from_slice(&identity.generation.get().to_be_bytes());
    bytes.extend_from_slice(identity.scope_digest.as_array());
    match parent {
        Some(parent) => {
            bytes.push(1);
            push_id(&mut bytes, &parent.bundle_id);
            bytes.extend_from_slice(parent.bundle_digest.as_array());
            bytes.extend_from_slice(parent.lineage_digest.as_array());
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

fn digest_cas_entries(
    entries: &[CasArtifactRefV1],
) -> Result<Digest32, CellParameterBundleErrorV1> {
    let mut bytes = b"hepta.learning-artifacts.cell-cas-root.v1\0".to_vec();
    for entry in entries {
        entry.validate("artifact bytes")?;
        push_id(&mut bytes, &entry.artifact_id);
        bytes.extend_from_slice(entry.content_digest.as_array());
        bytes.extend_from_slice(entry.manifest_digest.as_array());
        bytes.extend_from_slice(entry.compatibility_digest.as_array());
        bytes.extend_from_slice(&entry.encoded_size_bytes.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_manifest(
    manifest: &CellArtifactManifestV1,
) -> Result<Digest32, CellParameterBundleErrorV1> {
    let mut bytes = b"hepta.learning-artifacts.cell-artifact-manifest.v1\0".to_vec();
    push_id(&mut bytes, &manifest.manifest_id);
    bytes.extend_from_slice(manifest.cas_root_digest.as_array());
    bytes.extend_from_slice(&(manifest.entries.len() as u64).to_be_bytes());
    for entry in &manifest.entries {
        push_id(&mut bytes, &entry.artifact_id);
        bytes.extend_from_slice(entry.content_digest.as_array());
        bytes.extend_from_slice(entry.manifest_digest.as_array());
        bytes.extend_from_slice(entry.compatibility_digest.as_array());
        bytes.extend_from_slice(&entry.encoded_size_bytes.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_bundle(bundle: &CellParameterBundleV1) -> Result<Digest32, CellParameterBundleErrorV1> {
    let mut bytes = b"hepta.learning-artifacts.cell-parameter-bundle.v1\0".to_vec();
    push_id(&mut bytes, &bundle.bundle_id);
    push_id(&mut bytes, &bundle.identity.cell_id);
    push_id(&mut bytes, &bundle.identity.child_id);
    bytes.extend_from_slice(&bundle.identity.generation.get().to_be_bytes());
    bytes.extend_from_slice(bundle.identity.scope_digest.as_array());
    bytes.extend_from_slice(bundle.identity.lineage_digest.as_array());
    push_optional_predecessor(&mut bytes, bundle.parent_predecessor.as_ref());
    push_artifact(&mut bytes, &bundle.shared_base);
    push_component(&mut bytes, &bundle.adapter);
    push_component(&mut bytes, &bundle.head);
    bytes.extend_from_slice(bundle.state_schema_digest.as_array());
    bytes.extend_from_slice(bundle.optimizer_lineage_digest.as_array());
    bytes.extend_from_slice(bundle.artifact_manifest.manifest_digest.as_array());
    push_optional_predecessor(&mut bytes, bundle.rollback_target.as_ref());
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) fn digest_head(predecessor: Digest32, sequence: u64, bundle: Digest32) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.cell-bundle-head.v1\0".to_vec();
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(bundle.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_artifact(bytes: &mut Vec<u8>, artifact: &CasArtifactRefV1) {
    push_id(bytes, &artifact.artifact_id);
    bytes.extend_from_slice(artifact.content_digest.as_array());
    bytes.extend_from_slice(artifact.manifest_digest.as_array());
    bytes.extend_from_slice(artifact.compatibility_digest.as_array());
    bytes.extend_from_slice(&artifact.encoded_size_bytes.to_be_bytes());
}

fn push_component(bytes: &mut Vec<u8>, component: &CellComponentRefV1) {
    push_id(bytes, &component.component_id);
    bytes.push(match component.mode {
        CellComponentModeV1::Cloned => 0,
        CellComponentModeV1::Reinitialized => 1,
    });
    push_artifact(bytes, &component.artifact);
    match component.source_artifact_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(component.compatibility_digest.as_array());
}

fn push_optional_predecessor(bytes: &mut Vec<u8>, predecessor: Option<&CellBundlePredecessorV1>) {
    match predecessor {
        Some(predecessor) => {
            bytes.push(1);
            push_id(bytes, &predecessor.bundle_id);
            bytes.extend_from_slice(predecessor.bundle_digest.as_array());
            bytes.extend_from_slice(&predecessor.generation.get().to_be_bytes());
            bytes.extend_from_slice(predecessor.lineage_digest.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "cell_parameter_bundle_tests.rs"]
mod tests;
