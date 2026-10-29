//! Typed payload extension points share one publication/selection state machine.

use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractGenerationV1, ContractIdV1};
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use super::LoadedMemoryCellBundleV1;

pub trait Sealed {}

/// Construction remains inside this crate, as for the original loaded bundle.
/// No external consumer can manufacture a loaded release through the trait.
pub struct MemoryCellDecodeTokenV1(());
impl MemoryCellDecodeTokenV1 {
    pub(crate) fn new() -> Self { Self(()) }
}

/// Implemented only by registered native payload profiles. This trait supplies
/// typed validation; it cannot replace signed CURRENT, independent selection,
/// withdrawal admission or the release host's final-use state machine.
pub trait MemoryCellReleaseBundleV1: Sealed + Send + Sync {
    type OwnerSnapshot;
    fn decode(bytes: &[u8], expected: Digest32, token: MemoryCellDecodeTokenV1) -> Result<Self, String> where Self: Sized;
    fn validate_owner_snapshot(&self, snapshot: &Self::OwnerSnapshot) -> Result<(), String>;
    fn validate_manifest(&self, manifest: &LearningArtifactManifestV2) -> Result<(), String>;
    fn generation(&self) -> ContractGenerationV1;
    fn bundle_digest(&self) -> ContractDigestV1;
    fn scope(&self) -> &ContractIdV1;
}

impl Sealed for LoadedMemoryCellBundleV1 {}

impl MemoryCellReleaseBundleV1 for LoadedMemoryCellBundleV1 {
    type OwnerSnapshot = MemoryCellOwnerSnapshotV1;
    fn decode(bytes: &[u8], expected: Digest32, _token: MemoryCellDecodeTokenV1) -> Result<Self, String> {
        Self::decode(bytes, expected)
    }
    fn validate_owner_snapshot(&self, snapshot: &Self::OwnerSnapshot) -> Result<(), String> {
        self.validate_owner_snapshot(snapshot)
    }
    fn validate_manifest(&self, manifest: &LearningArtifactManifestV2) -> Result<(), String> {
        self.validate_manifest(manifest)
    }
    fn generation(&self) -> ContractGenerationV1 { self.generation() }
    fn bundle_digest(&self) -> ContractDigestV1 { self.bundle_digest() }
    fn scope(&self) -> &ContractIdV1 { self.scope() }
}
