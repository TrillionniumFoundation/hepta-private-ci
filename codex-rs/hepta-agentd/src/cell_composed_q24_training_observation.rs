//! Read-only coordinator material from the original anchored training result.
//! No time, signature, claim, candidate fitting or owner publication is created.

use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateReasonV2;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateV2;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::CellQ24TrainingOutcomeV1;
use super::CellQ24TrainingOwnerV1;
use super::Error;

/// Exact unsigned material read from an anchored original training completion.
/// The original evidence owner must retain its own observation time and sign
/// the complete receipt. This value creates no receipt or signing authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellQ24TrainingObservationV2 {
    iteration_head: Digest32,
    scope_binding: Digest32,
    evidence_digest: Digest32,
    observation: LearningIterationObservationV1,
}

impl CellQ24TrainingObservationV2 {
    pub fn iteration_head(&self) -> Digest32 { self.iteration_head }
    pub fn scope_binding(&self) -> Digest32 { self.scope_binding }
    pub fn evidence_digest(&self) -> Digest32 { self.evidence_digest }
    pub fn observation(&self) -> &LearningIterationObservationV1 { &self.observation }
}

impl<W: AnchorWitnessStore> CellQ24TrainingOwnerV1<W> {
    /// Read a completed original job into the coordinator's Training outcome.
    /// Missing, Pending and uncertain custody remain errors. Caller-supplied
    /// outcomes are never accepted as proof, and recovery never restamps time.
    pub fn read_learning_observation(
        &mut self,
        original_dataset_cut: &LearningIterationSnapshotV1,
    ) -> Result<CellQ24TrainingObservationV2, Error> {
        self.require_current()?;
        if original_dataset_cut != &self.plan.prefix {
            return Err(Error::Binding("original training Dataset cut"));
        }
        let payload = match self.journal.readback(&self.key)? {
            ProductEvaluationExecutionStateV1::Pending => return Err(Error::Pending),
            ProductEvaluationExecutionStateV1::Completed(payload) => payload,
        };
        let observation = match self.decode(&payload)? {
            CellQ24TrainingOutcomeV1::Candidate(candidate) => LearningIterationObservationV1::Training {
                candidate: Box::new(candidate.bundle), steps: candidate.metrics.optimizer_steps,
                milliseconds: candidate.metrics.elapsed_microseconds.div_ceil(1_000).max(1),
                artifact_bytes: candidate.heads.len() as u64,
            },
            CellQ24TrainingOutcomeV1::NoUpdate { retained_bundle, metrics } => {
                let Some(LearningIterationObservationV1::Dataset { snapshot_digest, .. }) =
                    self.plan.prefix.receipts.last().map(|receipt| &receipt.observation)
                else { return Err(Error::Binding("original training Dataset receipt")); };
                LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
                    retained_bundle, dataset: *snapshot_digest, update_rule: metrics.update_rule,
                    steps: metrics.optimizer_steps,
                    milliseconds: metrics.elapsed_microseconds.div_ceil(1_000).max(1),
                    reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
                })
            }
        };
        self.plan.scope.validate_observation(&observation)
            .map_err(|_| Error::Binding("original frozen training scope"))?;
        self.require_current()?;
        Ok(CellQ24TrainingObservationV2 {
            iteration_head: self.plan.prefix.head_digest,
            scope_binding: self.plan.scope.binding(),
            evidence_digest: Digest32::of_parts(&[
                b"hepta.cell.q24.original-training-observation.v2\0",
                self.key.binding_digest.as_array(), &payload,
            ]),
            observation,
        })
    }
}
