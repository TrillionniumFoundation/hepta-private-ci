//! One original Q24 training job with durable admission and immutable readback.
//! Reuses the bounded execution journal as storage only, in a separate training
//! domain; it obtains no evaluation, signing, selection or CURRENT authority.
//! The host supplies an exclusively owned authorized file and an independently
//! scoped durable witness. No path, key, witness or provenance is provisioned.

use std::fs::File;
use std::sync::atomic::AtomicBool;

use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionErrorV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionClaimV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::Digest32;

use super::CellQ24SgdRuleV1;
use super::CellQ24SingleHeadTrainingPlanV1;
use super::CellQ24TrainingBatchV1;
use super::CellQ24TrainingErrorV1;
use super::CellQ24TrainingMetricsV1;
use super::CellQ24TrainingOutcomeV1;
use super::OriginalQ24DatasetReadV1;
use super::OriginalQ24OwnerReadV1;

#[derive(Debug, thiserror::Error)]
pub enum CellQ24TrainingOwnerErrorV1 {
    #[error("Q24 training owner binding: {0}")]
    Binding(&'static str),
    #[error("Q24 training has an admitted unresolved operation; readback only")]
    Pending,
    #[error("Q24 training persistence acknowledgement is uncertain; reopen original owner")]
    CommitUncertain,
    #[error("Q24 training journal: {0}")]
    File(#[from] LockedFileProductEvaluationExecutionErrorV1),
    #[error("Q24 training execution storage: {0}")]
    Store(#[from] ProductEvaluationExecutionStoreErrorV1),
    #[error("Q24 training witness: {0}")]
    Witness(#[from] WitnessStoreError),
    #[error("Q24 training: {0}")]
    Training(#[from] CellQ24TrainingErrorV1),
}

type Error = CellQ24TrainingOwnerErrorV1;

#[path = "cell_composed_q24_training_construction.rs"]
mod construction;
#[path = "cell_composed_q24_training_observation.rs"]
mod observation;
pub use observation::CellQ24TrainingObservationV2;

/// Owns one exact frozen Dataset cut and its bounded native optimizer. Transfer
/// exclusive file ownership; writable duplicate descriptors are not supported.
/// The witness must retain its original independent rollback domain on reopen.
pub struct CellQ24TrainingOwnerV1<W: AnchorWitnessStore> {
    journal: LockedFileProductEvaluationExecutionStoreV1,
    witness: W,
    plan: CellQ24SingleHeadTrainingPlanV1,
    batch: CellQ24TrainingBatchV1,
    rule: CellQ24SgdRuleV1,
    key: ProductEvaluationExecutionKeyV1,
    fenced: bool,
}

impl<W: AnchorWitnessStore> CellQ24TrainingOwnerV1<W> {
    /// The enrolled Model factory checks this owner's own retained source
    /// capability. Legacy HQ24T001 trainers keep their existing behavior.
    #[cfg(target_os = "linux")]
    pub(crate) fn require_original_dataset_provenance(&self) -> Result<(), Error> {
        self.require_original_dataset_source(&OriginalQ24OwnerReadV1)
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn require_original_dataset_source(
        &self,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<(), Error> {
        OriginalQ24DatasetReadV1::require_original_batch(source, &self.batch)?;
        self.require_current_with_source(source)
    }

    /// Read-only preflight for the original typed training/signature pair.
    pub(crate) fn require_original_dataset_scope(
        &self,
        dataset: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        self.require_dataset_scope_with_source(dataset, scope, &OriginalQ24OwnerReadV1)
    }

    pub(crate) fn require_dataset_scope_with_source(
        &self,
        dataset: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<(), Error> {
        if dataset != &self.plan.prefix || scope != &self.plan.scope {
            return Err(Error::Binding("original training Dataset and scope"));
        }
        self.require_current_with_source(source)
    }

    /// Explicit genesis only. An existing file or witness is never reset.
    pub fn create(
        file: File,
        witness: W,
        plan: CellQ24SingleHeadTrainingPlanV1,
        batch: CellQ24TrainingBatchV1,
        rule: CellQ24SgdRuleV1,
    ) -> Result<Self, Error> {
        Self::create_with_source(file, witness, plan, batch, rule, &OriginalQ24OwnerReadV1)
    }

    /// Open only the original journal/witness. A valid suffix after a lost
    /// witness ACK is reconciled before readback; no optimizer runs here.
    pub fn recover(
        file: File,
        witness: W,
        plan: CellQ24SingleHeadTrainingPlanV1,
        batch: CellQ24TrainingBatchV1,
        rule: CellQ24SgdRuleV1,
    ) -> Result<Self, Error> {
        Self::recover_with_source(file, witness, plan, batch, rule, &OriginalQ24OwnerReadV1)
    }

    /// The durable claim and its independent witness precede all computation.
    /// Existing Pending is never permission to retry, even if cancellation or
    /// a crash may have happened before the first optimizer step. Completed
    /// reads preserve original metrics and bytes after the compute deadline;
    /// provenance batches still require current Dataset/source authorization.
    pub fn fit_or_readback(
        &mut self,
        cancellation: &AtomicBool,
    ) -> Result<CellQ24TrainingOutcomeV1, Error> {
        self.fit_or_readback_with_source(cancellation, &OriginalQ24OwnerReadV1)
    }

    pub(crate) fn fit_or_readback_with_source(
        &mut self,
        cancellation: &AtomicBool,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<CellQ24TrainingOutcomeV1, Error> {
        self.require_current_with_source(source)?;
        let before = anchor(self.journal.anchor());
        match self.journal.claim(&self.key)? {
            ProductEvaluationExecutionClaimV1::Existing(state) => return self.decode_state(state),
            ProductEvaluationExecutionClaimV1::Claimed => self.anchor_append(before)?,
        }
        let outcome = self.plan.fit_with_original_source(
            self.batch.clone(),
            self.rule,
            cancellation,
            source,
        )?;
        let payload = encode(&outcome, self.key.binding_digest)?;
        // Validate exactly the bytes that will be persisted, using the same
        // reconstruction as cold readback, before committing a terminal result.
        self.decode(&payload)?;
        self.require_current_with_source(source)?;
        let before = anchor(self.journal.anchor());
        self.journal.complete(&self.key, &payload)?;
        self.anchor_append(before)?;
        self.readback_with_source(source)
    }

    /// Inspect only this original operation. Missing storage remains Missing;
    /// no request is claimed and no deadline, weight or metric is regenerated.
    pub fn readback(&mut self) -> Result<CellQ24TrainingOutcomeV1, Error> {
        self.readback_with_source(&OriginalQ24OwnerReadV1)
    }

    pub(crate) fn readback_with_source(
        &mut self,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<CellQ24TrainingOutcomeV1, Error> {
        self.require_current_with_source(source)?;
        let state = self.journal.readback(&self.key)?;
        self.decode_state(state)
    }

    fn require_current_with_source(
        &self,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<(), Error> {
        if self.fenced || self.witness.current()? != Some(anchor(self.journal.anchor())) {
            return Err(Error::CommitUncertain);
        }
        OriginalQ24DatasetReadV1::require_current_batch(source, &self.batch)?;
        Ok(())
    }

    fn anchor_append(&mut self, before: JournalAnchor) -> Result<(), Error> {
        if self
            .witness
            .compare_and_swap(Some(before), anchor(self.journal.anchor()))
            .is_err()
        {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }

    fn decode_state(
        &self,
        state: ProductEvaluationExecutionStateV1,
    ) -> Result<CellQ24TrainingOutcomeV1, Error> {
        match state {
            ProductEvaluationExecutionStateV1::Pending => Err(Error::Pending),
            ProductEvaluationExecutionStateV1::Completed(payload) => self.decode(&payload),
        }
    }

    fn decode(&self, mut bytes: &[u8]) -> Result<CellQ24TrainingOutcomeV1, Error> {
        if take::<8>(&mut bytes)? != *b"HQ24TRES"
            || take::<32>(&mut bytes)? != self.key.binding_digest.into_array()
        {
            return Err(Error::Binding("training result and original job"));
        }
        let tag = take::<1>(&mut bytes)?[0];
        let bundle_digest = Digest32::from_array(take::<32>(&mut bytes)?);
        let metrics = CellQ24TrainingMetricsV1 {
            batch_digest: Digest32::from_array(take::<32>(&mut bytes)?),
            optimizer_rule: Digest32::from_array(take::<32>(&mut bytes)?),
            update_rule: Digest32::from_array(take::<32>(&mut bytes)?),
            optimizer_steps: u64::from_le_bytes(take::<8>(&mut bytes)?),
            squared_error_before_q48: u128::from_le_bytes(take::<16>(&mut bytes)?),
            squared_error_after_q48: u128::from_le_bytes(take::<16>(&mut bytes)?),
            elapsed_microseconds: u64::from_le_bytes(take::<8>(&mut bytes)?),
        };
        let length = u32::from_le_bytes(take::<4>(&mut bytes)?) as usize;
        let optimizer = self.rule.digest(&self.batch)?;
        let update_rule = super::cell_q24_single_head_update_rule_v1(
            &self.plan.prefix.request.selected_bundle,
            self.plan.head,
            optimizer,
        )
        .map_err(CellQ24TrainingErrorV1::from)?;
        let error_limit = u128::from(self.batch.rows()) * (16_u128 * (1 << 24)).pow(2);
        if metrics.batch_digest != self.batch.digest()
            || metrics.optimizer_rule != optimizer
            || metrics.update_rule != update_rule
            || metrics.optimizer_steps != u64::from(self.rule.epochs) * u64::from(self.batch.rows())
            || metrics.squared_error_before_q48 > error_limit
            || metrics.squared_error_after_q48 > error_limit
            || metrics.elapsed_microseconds
                > self
                    .plan
                    .prefix
                    .request
                    .budget
                    .maximum_training_milliseconds
                    .saturating_mul(1_000)
            || bytes.len() != length
        {
            return Err(Error::Binding("original training metrics or result length"));
        }
        match tag {
            0 => {
                let baseline = self
                    .plan
                    .prefix
                    .request
                    .selected_bundle
                    .digest()
                    .map_err(|_| Error::Binding("original baseline"))?;
                if length != 0
                    || bundle_digest != baseline
                    || metrics.squared_error_before_q48 != metrics.squared_error_after_q48
                {
                    return Err(Error::Binding("unchanged quantized result"));
                }
                Ok(CellQ24TrainingOutcomeV1::NoUpdate {
                    retained_bundle: baseline,
                    metrics,
                })
            }
            1 => {
                let candidate = self.plan.rebuild_candidate(bytes.to_vec(), metrics)?;
                if candidate
                    .bundle
                    .digest()
                    .map_err(|_| Error::Binding("candidate bundle"))?
                    != bundle_digest
                {
                    return Err(Error::Binding("original candidate digest"));
                }
                Ok(CellQ24TrainingOutcomeV1::Candidate(Box::new(candidate)))
            }
            _ => Err(Error::Binding("training result tag")),
        }
    }
}

fn anchor(value: ProductEvaluationExecutionAnchorV1) -> JournalAnchor {
    // The execution journal starts at zero; the original witness starts at one.
    // This bounded single-job journal has at most two execution events.
    JournalAnchor {
        sequence: value.sequence + 1,
        checkpoint_digest: value.history_digest,
    }
}

fn encode(outcome: &CellQ24TrainingOutcomeV1, binding: Digest32) -> Result<Vec<u8>, Error> {
    let (tag, bundle, heads, metrics) = match outcome {
        CellQ24TrainingOutcomeV1::Candidate(candidate) => (
            1,
            candidate
                .bundle
                .digest()
                .map_err(|_| Error::Binding("candidate bundle"))?,
            candidate.heads.as_slice(),
            &candidate.metrics,
        ),
        CellQ24TrainingOutcomeV1::NoUpdate {
            retained_bundle,
            metrics,
        } => (0, *retained_bundle, &[][..], metrics),
    };
    let mut bytes = b"HQ24TRES".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.push(tag);
    for digest in [
        bundle,
        metrics.batch_digest,
        metrics.optimizer_rule,
        metrics.update_rule,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&metrics.optimizer_steps.to_le_bytes());
    bytes.extend_from_slice(&metrics.squared_error_before_q48.to_le_bytes());
    bytes.extend_from_slice(&metrics.squared_error_after_q48.to_le_bytes());
    bytes.extend_from_slice(&metrics.elapsed_microseconds.to_le_bytes());
    bytes.extend_from_slice(&(heads.len() as u32).to_le_bytes());
    bytes.extend_from_slice(heads);
    Ok(bytes)
}

fn take<const N: usize>(bytes: &mut &[u8]) -> Result<[u8; N], Error> {
    let (value, rest) = bytes
        .split_at_checked(N)
        .ok_or(Error::Binding("truncated training result"))?;
    *bytes = rest;
    value
        .try_into()
        .map_err(|_| Error::Binding("training field"))
}
