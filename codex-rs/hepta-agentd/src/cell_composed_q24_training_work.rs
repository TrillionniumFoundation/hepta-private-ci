//! Actual original Training result DATA, authenticated by the already-signed
//! Training receipt's complete HQ24TRES preimage. No extra signing claim is
//! needed. Capacity comes from the loaded matrices, never manifest estimates.
//! Gradient-coordinate counts describe this one recorded native optimization;
//! they do not measure historical pretraining, wall time or benchmark costs.

use super::result_data::PREFIX_BYTES;
use super::result_data::decode_header;
use super::*;
use crate::CellParameterCapacityV1;
use crate::CellQ24PrivateHeadV1;
use crate::CellSelectiveUpdateV1;
use crate::CellTrainingBudgetV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OriginalQ24TrainingWorkDataV1 {
    prefix: Vec<u8>,
    epochs: u16,
    learning_rate_q24: i64,
}

/// Computed DATA after authentication to a supplied original Training cut.
/// Its caller must still supply the actual Root trust, files and live context.
pub(crate) struct OriginalQ24TrainingWorkObservedV1 {
    pub(crate) capacity: CellParameterCapacityV1,
    pub(crate) cumulative: CellTrainingBudgetV1,
    pub(crate) selective_update: CellSelectiveUpdateV1,
}

impl<W: AnchorWitnessStore> CellQ24TrainingOwnerV1<W> {
    pub(crate) fn read_original_work_with_source(
        &mut self,
        original_dataset_cut: &LearningIterationSnapshotV1,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<Option<OriginalQ24TrainingWorkDataV1>, Error> {
        self.require_current_with_source(source)?;
        if original_dataset_cut != &self.plan.prefix {
            return Err(Error::Binding("original training Dataset cut"));
        }
        let payload = match self.journal.readback(&self.key)? {
            ProductEvaluationExecutionStateV1::Pending => return Err(Error::Pending),
            ProductEvaluationExecutionStateV1::Completed(payload) => payload,
        };
        let data = match self.decode(&payload)? {
            CellQ24TrainingOutcomeV1::Candidate(_) => Some(OriginalQ24TrainingWorkDataV1 {
                prefix: payload[..PREFIX_BYTES].to_vec(),
                epochs: self.rule.epochs,
                learning_rate_q24: self.rule.learning_rate_q24,
            }),
            CellQ24TrainingOutcomeV1::NoUpdate { .. } => None,
        };
        self.require_current_with_source(source)?;
        Ok(data)
    }
}

impl OriginalQ24TrainingWorkDataV1 {
    pub(crate) fn digest(&self) -> Result<Digest32, Error> {
        if self.prefix.len() != PREFIX_BYTES {
            return Err(Error::Binding("bounded original Training result header"));
        }
        Ok(Digest32::of_parts(&[
            b"hepta.q24.original-training-work-data.v1\0",
            &self.prefix,
            &self.epochs.to_le_bytes(),
            &self.learning_rate_q24.to_le_bytes(),
        ]))
    }

    pub(crate) fn verify_original_training(
        &self,
        training: &LearningIterationSnapshotV1,
        baseline: &super::super::LoadedCellQ24ModelV1,
        model: &super::super::LoadedCellQ24ModelV1,
        head: CellQ24PrivateHeadV1,
        heads: &[u8],
    ) -> Result<OriginalQ24TrainingWorkObservedV1, Error> {
        self.digest()?;
        let header = decode_header(&mut self.prefix.as_slice())?;
        let receipt = training
            .receipts
            .last()
            .ok_or(Error::Binding("Training receipt"))?;
        let LearningIterationObservationV1::Training {
            candidate,
            steps,
            milliseconds,
            artifact_bytes,
        } = &receipt.observation
        else {
            return Err(Error::Binding("actual candidate Training receipt required"));
        };
        let mut rows = None;
        for previous in &training.receipts[..training.receipts.len() - 1] {
            if let LearningIterationObservationV1::Dataset { rows: actual, .. } =
                &previous.observation
            {
                if rows.replace(*actual).is_some() {
                    return Err(Error::Binding("one actual original Dataset required"));
                }
            }
        }
        let rows = rows.ok_or(Error::Binding("original Dataset rows absent"))?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(training.clone())
            .map_err(|_| Error::Binding("original Training cut"))?;
        let lineage = candidate
            .training_lineage
            .as_ref()
            .ok_or(Error::Binding("original candidate lineage"))?;
        let rule = CellQ24SgdRuleV1 {
            epochs: self.epochs,
            learning_rate_q24: self.learning_rate_q24,
        };
        let optimizer = rule.digest_for_original_batch(header.metrics.batch_digest)?;
        let update = super::super::cell_q24_single_head_update_rule_v1(
            &training.request.selected_bundle,
            head,
            optimizer,
        )
        .map_err(CellQ24TrainingErrorV1::from)?;
        let scope = FrozenLearningScopeV2::freeze(
            &training.request,
            &training.owners,
            LearningUpdateScopeV2::Cell,
            update,
        )
        .map_err(|_| Error::Binding("original frozen Training scope"))?;
        let binding = Digest32::of_parts(&[
            b"hepta.cell.q24.original-training-job.v1\0",
            receipt.predecessor.as_array(),
            scope.binding().as_array(),
            baseline.effective_weights_digest().as_array(),
            header.metrics.batch_digest.as_array(),
            optimizer.as_array(),
        ]);
        let mut payload = self.prefix.clone();
        payload.extend_from_slice(heads);
        if header.tag != 1
            || header.binding != binding
            || baseline.components() != &training.request.selected_bundle.components
            || header.length != heads.len()
            || header.length > 32_780
            || coordinator.candidate() != Some(candidate.as_ref())
            || model.components() != &candidate.components
            || model.original_head_bytes() != heads
            || header.bundle_digest
                != candidate
                    .digest()
                    .map_err(|_| Error::Binding("candidate bundle"))?
            || Digest32::of_bytes(heads) != candidate.components.heads
            || header.metrics.optimizer_rule != optimizer
            || header.metrics.update_rule != update
            || lineage.update_rule != update
            || header.metrics.optimizer_steps != *steps
            || *steps != u64::from(rows) * u64::from(self.epochs)
            || *milliseconds != header.metrics.elapsed_microseconds.div_ceil(1_000).max(1)
            || *artifact_bytes != heads.len() as u64
            || receipt.evidence_digest
                != Digest32::of_parts(&[
                    b"hepta.cell.q24.original-training-observation.v2\0",
                    header.binding.as_array(),
                    &payload,
                ])
        {
            return Err(Error::Binding("authenticated native Training work differs"));
        }
        let index = match head {
            CellQ24PrivateHeadV1::Drive { index } | CellQ24PrivateHeadV1::Prediction { index } => {
                index
            }
        };
        if usize::from(index) >= model.output_width() {
            return Err(Error::Binding("actual native training row differs"));
        }
        let mut total =
            model.base.values.len() + model.encoder.values.len() + model.heads.values.len();
        for adapter in [&model.organ, &model.cell].into_iter().flatten() {
            total += adapter.down.values.len() + adapter.up.values.len();
        }
        let width = model.heads.cols as u64;
        let updates = steps
            .checked_mul(width)
            .ok_or(Error::Binding("native work count overflow"))?;
        let (compute, policy, eligibility, schedule) = original_q24_work_contract(head, rule);
        Ok(OriginalQ24TrainingWorkObservedV1 {
            capacity: CellParameterCapacityV1 {
                total_parameters: total as u64,
                trainable_parameters: width,
                maximum_active_parameters: total as u64,
            },
            cumulative: CellTrainingBudgetV1 {
                examples_seen: u64::from(rows),
                optimizer_steps: *steps,
                parameter_updates: updates,
                compute_units: updates,
                compute_unit_contract: compute.into_array(),
            },
            selective_update: CellSelectiveUpdateV1 {
                policy_digest: policy.into_array(),
                eligibility_digest: eligibility.into_array(),
                schedule_digest: schedule.into_array(),
                maximum_parameters_per_step: width,
            },
        })
    }
}

/// Pure units/policy DATA shared with explicit comparison declarations. This
/// function neither reports completed work nor authenticates a Training job.
/// `examples_seen` counts distinct original frozen rows; `optimizer_steps`
/// counts all row visits across epochs. Compute counts gradient coordinates.
pub(crate) fn original_q24_work_contract(
    head: CellQ24PrivateHeadV1,
    rule: CellQ24SgdRuleV1,
) -> (Digest32, Digest32, Digest32, Digest32) {
    let (tag, index) = match head {
        CellQ24PrivateHeadV1::Drive { index } => (1_u8, index),
        CellQ24PrivateHeadV1::Prediction { index } => (2_u8, index),
    };
    (
        Digest32::of_bytes(b"hepta.q24.work.v1;one-SGD-gradient-coordinate;zero-delta-included;forward-cost-separate"),
        Digest32::of_parts(&[b"hepta.q24.work-policy.v1\0fixed-order;half-squared;STE;clip-eight", &[tag], &index.to_le_bytes()]),
        Digest32::of_bytes(b"hepta.q24.work-eligibility.v1\0all-original-frozen-rows"),
        Digest32::of_parts(&[b"hepta.q24.work-schedule.v1\0", &rule.epochs.to_le_bytes(), &rule.learning_rate_q24.to_le_bytes()]),
    )
}
