//! Typed legacy memory parameters using the shared durable artifact authority.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_learning_artifacts::ArtifactPublicationReceiptV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::VerifiedArtifactSelectionV1;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_types::Digest32;

#[path = "memory_cell_release_core.rs"]
pub(crate) mod core;
#[path = "memory_cell_bundle.rs"]
mod bundle;
pub use bundle::LoadedMemoryCellBundleV1;
pub use bundle::MemoryCellBundleCandidateV1;

#[path = "memory_structure_runtime_v9.rs"]
mod structure_v9;
pub use structure_v9::MemoryStructurePublicationV9;
pub use structure_v9::sleep_selected_memory_v9;
pub use structure_v9::stage_memory_structure_v9;

#[cfg(test)]
use core::now;
#[cfg(test)]
use core::revalidate_state;

/// Product consumer of the durable artifact service. This wrapper preserves
/// the V1 payload contract; the shared slot owns admission and selection.
pub struct MemoryCellReleaseHostV1 {
    inner: core::MemoryReleaseSlot<LoadedMemoryCellBundleV1>,
}

impl MemoryCellReleaseHostV1 {
    pub fn new(
        service: Arc<Mutex<LearningArtifactOwnerService>>,
        selection_verifier: ArtifactSelectionVerifierV1,
    ) -> Self {
        Self { inner: core::MemoryReleaseSlot::new(service, selection_verifier) }
    }

    pub fn publish(
        &self,
        request: LearningArtifactPublishRequestV1,
        snapshot: &MemoryCellOwnerSnapshotV1,
    ) -> Result<ArtifactPublicationReceiptV1, String> {
        self.inner.publish(request, |bundle| bundle.validate_owner_snapshot(snapshot))
    }

    pub fn install_selected(
        &self,
        snapshot: File,
        payload: File,
        selection: VerifiedArtifactSelectionV1,
        admission: WithdrawalBoundArtifactAdmissionV3,
    ) -> Result<(), String> {
        self.inner.install_selected(snapshot, payload, selection, admission)
    }

    pub fn load_current(&self) -> Result<Arc<LoadedMemoryCellBundleV1>, String> {
        self.inner.load_current()
    }

    pub fn revalidate(&self, bundle: &LoadedMemoryCellBundleV1) -> Result<(), String> {
        self.inner.revalidate(bundle)
    }
}

impl core::MemoryReleaseBundle for LoadedMemoryCellBundleV1 {
    fn decode(bytes: &[u8], expected: Digest32) -> Result<Self, String> {
        Self::decode(bytes, expected)
    }
    fn validate_manifest(&self, manifest: &LearningArtifactManifestV2) -> Result<(), String> {
        self.validate_manifest(manifest)
    }
    fn generation(&self) -> ContractGenerationV1 { self.generation() }
    fn bundle_digest(&self) -> ContractDigestV1 { self.bundle_digest() }
    fn scope(&self) -> &ContractIdV1 { self.scope() }
}

#[cfg(test)]
#[path = "memory_cell_release_test_support.rs"]
pub(crate) mod test_support;
#[cfg(test)]
#[path = "memory_cell_release_tests.rs"]
mod tests;
#[cfg(test)]
#[path = "memory_cell_release_trust_tests.rs"]
mod trust_tests;
