//! Source-admitted immutable consumption of an independently selected tensor.
//!
//! This is part of the existing Agentd replay owner. It adds no provider, model
//! service, authority issuer or publication path. Actual App Server cutover is
//! still a separately authorized effect; this API only prepares read results.
use std::fs::File;

use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::GuardedSelectedCandidateV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::load_guarded_selected_candidate_v1;

use super::*;

/// Cannot be constructed from a trainer receipt, an unsigned manifest, or a
/// deserialized model alone. It is deliberately neither Clone nor serializable.
pub struct SelectedMemoryTensorModelV1 {
    candidate: MemoryTensorCandidateV1,
    source: SharedExperienceUseV1,
    pinned: GuardedSelectedCandidateV1,
    unavailable: bool,
}

impl SelectedMemoryTensorModelV1 {
    pub fn selection_digest(&self) -> Digest32 {
        self.pinned.selection_digest()
    }
}

impl AgentdSharedReplayHostV1 {
    /// `clock` and both owners are host-controlled. Select against authenticated
    /// CURRENT, not a CURRENT receipt supplied by the model or its producer.
    /// Files must already have been opened through the artifact owner's path
    /// confinement; exact pinning and payload verification happen here.
    #[allow(clippy::too_many_arguments)]
    pub async fn load_selected_memory_tensor_v1(
        &self,
        candidate: SharedMemoryTensorCandidateV1,
        ledger: &LedgerWriter,
        owner: &LearningArtifactOwnerService,
        selector: &ArtifactSelectionVerifierV1,
        selection: &SignedArtifactSelectionV1,
        snapshot_file: File,
        payload_file: File,
        clock: impl Fn() -> Result<u64, SharedMemoryTrainingError>,
    ) -> Result<SelectedMemoryTensorModelV1, SharedMemoryTrainingError> {
        if owner.recovery_required().is_some() {
            return Err(SharedMemoryTrainingError::Invalid("artifact recovery required"));
        }
        self.revalidate_memory_source(
            &candidate.source, ledger, candidate.candidate.frozen().dataset(), clock()?,
        ).await?;
        let now = clock()?;
        let current = owner.current_registry_view(now)
            .map_err(|_| SharedMemoryTrainingError::Invalid("current registry unavailable"))?;
        let selected = selector.verify(selection, &current, now)
            .map_err(|_| SharedMemoryTrainingError::Invalid("independent selection rejected"))?;
        let mut pinned = load_guarded_selected_candidate_v1(
            snapshot_file, payload_file, selected, selector, clock()?,
        ).map_err(|_| SharedMemoryTrainingError::Invalid("selected tensor load rejected"))?;
        if !memory_manifest_matches(&candidate, pinned.manifest()) {
            return Err(SharedMemoryTrainingError::Invalid("selected training lineage mismatch"));
        }
        let now = clock()?;
        let current = owner.current_registry_view(now)
            .map_err(|_| SharedMemoryTrainingError::Invalid("current registry unavailable"))?;
        let exact = pinned.with_current(selector, current, now, |bytes| bytes == candidate.payload)
            .map_err(|_| SharedMemoryTrainingError::Invalid("selected payload unavailable"))?;
        if !exact {
            return Err(SharedMemoryTrainingError::Invalid("selected training payload mismatch"));
        }
        let mut model = SelectedMemoryTensorModelV1 {
            candidate: candidate.candidate,
            source: candidate.source,
            pinned,
            unavailable: false,
        };
        self.with_current_selected_memory_tensor_v1(
            &mut model, ledger, owner, selector, clock, |_| (),
        ).await?;
        Ok(model)
    }

    /// Read-only bounded computation. Recheck after it, using a newly sampled
    /// clock and authenticated CURRENT; do not expose the result of failed work.
    /// A failure (including unwinding) closes this instance permanently. Restart
    /// or restore requires the complete source/selection/payload load path again.
    pub async fn with_current_selected_memory_tensor_v1<T>(
        &self,
        model: &mut SelectedMemoryTensorModelV1,
        ledger: &LedgerWriter,
        owner: &LearningArtifactOwnerService,
        selector: &ArtifactSelectionVerifierV1,
        clock: impl Fn() -> Result<u64, SharedMemoryTrainingError>,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, SharedMemoryTrainingError> {
        if model.unavailable || owner.recovery_required().is_some() {
            model.unavailable = true;
            return Err(SharedMemoryTrainingError::Invalid("selected memory unavailable"));
        }
        model.unavailable = true;
        self.revalidate_memory_source(
            &model.source, ledger, model.candidate.frozen().dataset(), clock()?,
        ).await?;
        let now = clock()?;
        let current = owner.current_registry_view(now)
            .map_err(|_| SharedMemoryTrainingError::Invalid("current registry unavailable"))?;
        let value = model.pinned.with_current(selector, current, now, consume)
            .map_err(|_| SharedMemoryTrainingError::Invalid("selected payload unavailable"))?;
        self.revalidate_memory_source(
            &model.source, ledger, model.candidate.frozen().dataset(), clock()?,
        ).await?;
        let now = clock()?;
        let current = owner.current_registry_view(now)
            .map_err(|_| SharedMemoryTrainingError::Invalid("current registry unavailable"))?;
        model.pinned.with_current(selector, current, now, |_| ())
            .map_err(|_| SharedMemoryTrainingError::Invalid("selection changed during computation"))?;
        model.unavailable = false;
        Ok(value)
    }
}
