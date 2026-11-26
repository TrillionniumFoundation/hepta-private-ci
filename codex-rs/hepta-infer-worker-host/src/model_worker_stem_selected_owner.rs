//! Owner-bound, shadow-only single/batch dispatch of two independently
//! selected Stem artifacts. This module obtains CURRENT from the existing
//! single Learning Artifact product owner on EVERY dispatch.
//!
//! A caller cannot pass a saved CURRENT view or backdate selection time:
//! the host-bound AuthorityClock supplies one timestamp for CURRENT,
//! independent Selector verification and Worker lease/deadline evaluation.
//! Holding &mut LearningArtifactOwnerService through the complete execution
//! also prevents concurrent mutations through that Rust owner value.
//!
//! This is still not production authorization: external Encoder provenance,
//! Final-use, scope/revocation publication, durable WAL and Supervisor crash
//! reconciliation remain separate mandatory product-owner gates.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;

use super::CpuGatedHeadDriver;
use super::InferenceWorker;
use super::NeuronBackendBatchReceipt;
use super::NeuronFeatureRequest;
use super::SelectedStemHeadBankReaderV1;
use super::SelectedStemProjectionReaderV1;
use super::StemCpuHeadBatchItemV1;
use super::StemCpuHeadBatchUseV1;
use super::StemCpuHeadUseV1;
use super::StemHeadArtifactError;
use super::StemHeadBankReadObservationV1;
use super::stem_projection::StemProjectionBindingV1;

#[derive(Debug)]
pub enum StemSelectedOwnerError {
    UnavailableClock(String),
    UnavailableCurrent(String),
    Reader(StemHeadArtifactError),
}

impl fmt::Display for StemSelectedOwnerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for StemSelectedOwnerError {}

/// Acquire both signed CURRENT views from one live product owner under one
/// host-bound time sample. A caller cannot substitute an old view or a
/// test-supplied historical selection timestamp.
fn acquire_current_pair(
    artifacts: &mut LearningArtifactOwnerService,
    clock: &dyn AuthorityClock,
) -> Result<
    (
        u64,
        VerifiedCurrentRegistryViewV1,
        VerifiedCurrentRegistryViewV1,
    ),
    StemSelectedOwnerError,
> {
    let now = clock
        .now_unix_ms()
        .map_err(|error| StemSelectedOwnerError::UnavailableClock(error.to_string()))?;
    let projection_current = artifacts
        .current_registry_view(now)
        .map_err(|error| StemSelectedOwnerError::UnavailableCurrent(error.to_string()))?;
    let head_current = artifacts
        .current_registry_view(now)
        .map_err(|error| StemSelectedOwnerError::UnavailableCurrent(error.to_string()))?;
    Ok((now, projection_current, head_current))
}

/// A single same-principal read-only dispatch lane. The only public run path
/// obtains signed CURRENT directly from the existing durable Artifact Owner.
///
/// This struct deliberately holds a *mutable borrow* of that owner service for
/// the entire dispatch. No clone of verified-current data is cached.
pub struct StemSelectedReadOwnerV1<'a> {
    artifacts: &'a mut LearningArtifactOwnerService,
    projection: &'a mut SelectedStemProjectionReaderV1,
    heads: &'a mut SelectedStemHeadBankReaderV1,
    worker: &'a mut InferenceWorker<CpuGatedHeadDriver>,
    projection_selector: &'a ArtifactSelectionVerifierV1,
    head_selector: &'a ArtifactSelectionVerifierV1,
    clock: &'a dyn AuthorityClock,
}

impl<'a> StemSelectedReadOwnerV1<'a> {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        artifacts: &'a mut LearningArtifactOwnerService,
        projection: &'a mut SelectedStemProjectionReaderV1,
        heads: &'a mut SelectedStemHeadBankReaderV1,
        worker: &'a mut InferenceWorker<CpuGatedHeadDriver>,
        projection_selector: &'a ArtifactSelectionVerifierV1,
        head_selector: &'a ArtifactSelectionVerifierV1,
        clock: &'a dyn AuthorityClock,
    ) -> Self {
        Self {
            artifacts,
            projection,
            heads,
            worker,
            projection_selector,
            head_selector,
            clock,
        }
    }

    /// This is a read-only model calculation under the product Artifact
    /// Owner's live CURRENT discovery, not a final-use token or signed receipt.
    #[allow(clippy::too_many_arguments)]
    pub fn run_one(
        &mut self,
        signed_projection: &SignedArtifactSelectionV1,
        signed_head: &SignedArtifactSelectionV1,
        binding: &StemProjectionBindingV1,
        features: &[f32],
        token_count: u64,
        request: NeuronFeatureRequest,
        model_id: &str,
    ) -> Result<
        (
            codex_hepta_infer_core::NeuronFeatureReceiptV1,
            StemHeadBankReadObservationV1,
        ),
        StemSelectedOwnerError,
    > {
        let result = (|| {
            // A single owner-bound clock sample controls both signed CURRENT
            // checks, independent Selector verification and Worker deadline.
            let (now, projection_current, head_current) =
                acquire_current_pair(self.artifacts, self.clock)?;
            self.heads
                .run_selected_cpu_head(
                    self.projection,
                    self.worker,
                    StemCpuHeadUseV1 {
                        selector: self.projection_selector,
                        signed_selection: signed_projection,
                        current: projection_current,
                        selection_now: now,
                        binding,
                        source_features: features,
                        token_count,
                        request,
                        worker_now_ms: now,
                        model_id,
                    },
                    self.head_selector,
                    signed_head,
                    head_current,
                    now,
                )
                .map_err(StemSelectedOwnerError::Reader)
        })();
        if result.is_err() {
            // Missing CURRENT, clock failure or mismatch cannot leave a
            // seemingly valid counterpart reader usable after the failure.
            self.projection.invalidate();
            self.heads.invalidate();
        }
        result
    }

    /// Exactly one native CPU Head backend invocation for 2..=32 validated
    /// requests. Never falls back to per-Cell sequential Worker execution.
    #[allow(clippy::too_many_arguments)]
    pub fn run_batch(
        &mut self,
        signed_projection: &SignedArtifactSelectionV1,
        signed_head: &SignedArtifactSelectionV1,
        items: Vec<StemCpuHeadBatchItemV1<'_>>,
        model_id: &str,
    ) -> Result<(NeuronBackendBatchReceipt, StemHeadBankReadObservationV1), StemSelectedOwnerError> {
        let result = (|| {
            // A single owner-bound clock sample controls both signed CURRENT
            // checks, independent Selector verification and Worker deadline.
            let (now, projection_current, head_current) =
                acquire_current_pair(self.artifacts, self.clock)?;
            self.heads
                .run_selected_cpu_head_backend_batch(
                    self.projection,
                    self.worker,
                    StemCpuHeadBatchUseV1 {
                        selector: self.projection_selector,
                        signed_selection: signed_projection,
                        current: projection_current,
                        selection_now: now,
                        items,
                        worker_now_ms: now,
                        model_id,
                    },
                    self.head_selector,
                    signed_head,
                    head_current,
                    now,
                )
                .map_err(StemSelectedOwnerError::Reader)
        })();
        if result.is_err() {
            self.projection.invalidate();
            self.heads.invalidate();
        }
        result
    }
}

#[cfg(test)]
#[path = "model_worker_stem_selected_owner_tests.rs"]
mod tests;
