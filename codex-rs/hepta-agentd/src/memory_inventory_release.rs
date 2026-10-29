//! Residual inventory uses the same signed artifact owner and release checks.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_artifacts::ArtifactPublicationReceiptV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::VerifiedArtifactSelectionV1;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;

use crate::memory_cell_release::core::MemoryReleaseSlot;
use crate::memory_inventory_bundle::LoadedMemoryInventoryBundleV1;

/// Typed residual consumer; a candidate cannot publish or select itself.
pub struct MemoryInventoryReleaseHostV1 {
    inner: MemoryReleaseSlot<LoadedMemoryInventoryBundleV1>,
}

impl MemoryInventoryReleaseHostV1 {
    pub fn new(service: Arc<Mutex<LearningArtifactOwnerService>>, verifier: ArtifactSelectionVerifierV1) -> Self {
        Self { inner: MemoryReleaseSlot::new(service, verifier) }
    }

    pub fn publish(&self, request: LearningArtifactPublishRequestV1, snapshot: &MemoryInventoryOwnerSnapshotV1) -> Result<ArtifactPublicationReceiptV1, String> {
        self.inner.publish(request, |bundle| bundle.validate_owner_snapshot(snapshot))
    }

    pub fn install_selected(&self, snapshot: File, payload: File, selection: VerifiedArtifactSelectionV1, admission: WithdrawalBoundArtifactAdmissionV3) -> Result<(), String> {
        self.inner.install_selected(snapshot, payload, selection, admission)
    }

    pub fn load_current(&self) -> Result<Arc<LoadedMemoryInventoryBundleV1>, String> { self.inner.load_current() }

    pub fn revalidate(&self, bundle: &LoadedMemoryInventoryBundleV1) -> Result<(), String> { self.inner.revalidate(bundle) }

    /// Only a still-current selected bundle may release its decoded cache.
    pub fn sleep_selected(&self) -> Result<(), String> {
        let bundle = self.load_current()?;
        bundle.sleep()?;
        self.revalidate(&bundle)
    }
}
