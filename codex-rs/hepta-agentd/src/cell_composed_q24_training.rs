//! Bounded native single-row optimization on the actual frozen Q24 graph.
//! The host owns source authentication, durable job claims and attestation.
//! Training metrics are development observations, not independent evaluation.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::super::codec;
use super::CellQ24PrivateHeadV1;
use super::CellQ24SingleHeadTrainingPlanV1;
use super::CellQ24TrainingPlanErrorV1;
use super::LoadedCellQ24ModelV1;
use super::cell_q24_single_head_update_rule_v1;

#[path = "cell_q24_dataset_materializer.rs"]
mod dataset;
pub use dataset::CellQ24DatasetErrorV1;
pub use dataset::CellQ24DatasetProjectionV1;
pub use dataset::CellQ24DatasetTaskV1;
pub use dataset::cell_q24_dataset_run_snapshot_digest_v1;
pub(crate) use dataset::project_original_q24_dataset_v1;

#[path = "cell_q24_training_fit.rs"]
mod fit;

#[path = "cell_q24_training_source_read.rs"]
mod source_read;
pub(crate) use source_read::OriginalQ24DatasetReadV1;
pub(crate) use source_read::OriginalQ24OwnerReadV1;

#[cfg(target_os = "linux")]
#[path = "cell_q24_learning_preparation.rs"]
mod preparation;
#[cfg(target_os = "linux")]
pub use preparation::CellQ24DatasetFreezePreparationV1;
#[cfg(target_os = "linux")]
pub use preparation::CellQ24FrozenDatasetV1;
#[cfg(target_os = "linux")]
pub use preparation::CellQ24LearningPreparationConfigV1;
#[cfg(target_os = "linux")]
pub use preparation::CellQ24LearningPreparationErrorV1;
#[cfg(target_os = "linux")]
pub use preparation::CellQ24PreparedLearningFactsV1;
#[cfg(target_os = "linux")]
pub use preparation::CellQ24PreparedLearningV1;
#[cfg(target_os = "linux")]
pub use preparation::CellQ24PreparedTrainingMaterialV1;
#[cfg(target_os = "linux")]
pub use preparation::OriginalCellQ24DatasetFreezeErrorV1;
#[cfg(target_os = "linux")]
pub use preparation::OriginalCellQ24DatasetFreezeOwnerV1;
#[cfg(target_os = "linux")]
pub use preparation::OriginalCellQ24DatasetFreezeSigningConfigV1;
#[cfg(target_os = "linux")]
pub(crate) use preparation::OriginalPreparedReadV1;

const LIMIT: i64 = 8 * codec::Q;

#[derive(Debug, thiserror::Error)]
pub enum CellQ24TrainingErrorV1 {
    #[error("original Dataset projection: {0}")]
    Dataset(#[from] CellQ24DatasetErrorV1),
    #[error("Q24 training binding or budget: {0}")]
    Binding(&'static str),
    #[error("original Q24 training plan: {0}")]
    Plan(#[from] CellQ24TrainingPlanErrorV1),
    #[error("Q24 training cancelled; no candidate returned")]
    Cancelled,
    #[error("Q24 training deadline elapsed; no candidate returned")]
    DeadlineExceeded,
}

/// Exact fixed-point input and target supplied by the original dataset owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellQ24TrainingSampleV1 {
    pub input: Vec<i64>,
    pub target: i64,
}

/// Canonical immutable training material. Its digest is frozen into the rule.
/// The dataset identity must also match the original Dataset receipt; this
/// constructor alone cannot attest provenance or authorize source access.
#[derive(Clone)]
pub struct CellQ24TrainingBatchV1 {
    source_dataset: Digest32,
    samples: Vec<CellQ24TrainingSampleV1>,
    encoded: Vec<u8>,
    digest: Digest32,
    source: Option<Arc<dataset::OriginalDataset>>,
}

impl CellQ24TrainingBatchV1 {
    pub fn new(
        source_dataset: Digest32,
        samples: Vec<CellQ24TrainingSampleV1>,
    ) -> Result<Self, CellQ24TrainingErrorV1> {
        if source_dataset.is_zero() || !(1..=256).contains(&samples.len()) {
            return Err(CellQ24TrainingErrorV1::Binding("dataset identity or rows"));
        }
        let width = samples[0].input.len();
        if !(1..=64).contains(&width)
            || samples.iter().any(|sample| {
                sample.input.len() != width
                    || !(-LIMIT..=LIMIT).contains(&sample.target)
                    || sample
                        .input
                        .iter()
                        .any(|value| !(-LIMIT..=LIMIT).contains(value))
            })
        {
            return Err(CellQ24TrainingErrorV1::Binding("Q24 sample shape or range"));
        }
        let mut encoded = b"HQ24T001".to_vec();
        encoded.extend_from_slice(source_dataset.as_array());
        encoded.extend_from_slice(&(width as u16).to_le_bytes());
        encoded.extend_from_slice(&(samples.len() as u16).to_le_bytes());
        for sample in &samples {
            for value in sample.input.iter().chain(std::iter::once(&sample.target)) {
                encoded.extend_from_slice(&value.to_le_bytes());
            }
        }
        Ok(Self {
            source_dataset,
            digest: Digest32::of_bytes(&encoded),
            samples,
            encoded,
            source: None,
        })
    }

    pub(super) fn revalidate_source(&self) -> Result<(), CellQ24TrainingErrorV1> {
        if let Some(source) = &self.source {
            source.require_batch(self)?;
        }
        Ok(())
    }

    /// New Model enrollment requires the original capability, never a byte
    /// prefix or the legacy revalidate_source(None) compatibility result.
    #[cfg(target_os = "linux")]
    pub(crate) fn require_original_dataset_provenance(&self) -> Result<(), CellQ24TrainingErrorV1> {
        let source = self.source.as_ref().ok_or(CellQ24TrainingErrorV1::Binding(
            "original Dataset capability required",
        ))?;
        source.require_batch(self)?;
        Ok(())
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn encoded(&self) -> &[u8] {
        &self.encoded
    }

    pub fn rows(&self) -> u32 {
        self.samples.len() as u32
    }
}

/// Fixed-order online SGD for half squared error. Prediction uses exact Q24
/// serving arithmetic; the derivative is explicitly straight-through for
/// truncation and clipping. This is not an analytic derivative of a step map.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellQ24SgdRuleV1 {
    pub epochs: u16,
    pub learning_rate_q24: i64,
}

impl CellQ24SgdRuleV1 {
    pub fn digest(
        &self,
        batch: &CellQ24TrainingBatchV1,
    ) -> Result<Digest32, CellQ24TrainingErrorV1> {
        if !(1..=256).contains(&self.epochs) || !(1..=codec::Q).contains(&self.learning_rate_q24) {
            return Err(CellQ24TrainingErrorV1::Binding("SGD rule"));
        }
        Ok(Digest32::of_parts(&[
            b"hepta.cell.q24.sgd.v1\0fixed-order;half-squared-error;STE-truncate-and-clip;single-i128-gradient-division;clip-coefficients-eight",
            &self.epochs.to_le_bytes(),
            &self.learning_rate_q24.to_le_bytes(),
            batch.digest.as_array(),
        ]))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellQ24TrainingMetricsV1 {
    pub batch_digest: Digest32,
    pub optimizer_rule: Digest32,
    pub update_rule: Digest32,
    pub optimizer_steps: u64,
    pub squared_error_before_q48: u128,
    pub squared_error_after_q48: u128,
    pub elapsed_microseconds: u64,
}

/// Actual unselected candidate. The original trainer must attest its result;
/// independent evaluator/selector/CURRENT owners retain their responsibilities.
pub struct CellQ24TrainedCandidateV1 {
    pub model: LoadedCellQ24ModelV1,
    pub bundle: CellCompatibilityBundleV1,
    pub heads: Vec<u8>,
    pub metrics: CellQ24TrainingMetricsV1,
}

pub enum CellQ24TrainingOutcomeV1 {
    Candidate(Box<CellQ24TrainedCandidateV1>),
    /// Final quantized coefficients equal the baseline. This creates no Training receipt and
    /// does not convert missing evidence into an evaluated NoUpdate decision.
    NoUpdate {
        retained_bundle: Digest32,
        metrics: CellQ24TrainingMetricsV1,
    },
}

impl CellQ24SingleHeadTrainingPlanV1 {
    /// Run a bounded fit against the pre-frozen plan. A host must claim its
    /// durable operation before calling and reconcile ambiguous completion;
    /// calling this pure compute operation again is another fit, not recovery.
    pub fn fit(
        &self,
        batch: CellQ24TrainingBatchV1,
        rule: CellQ24SgdRuleV1,
        cancellation: &AtomicBool,
    ) -> Result<CellQ24TrainingOutcomeV1, CellQ24TrainingErrorV1> {
        self.fit_with_original_source(batch, rule, cancellation, &OriginalQ24OwnerReadV1)
    }

    /// Static preflight shared with durable admission and read-only recovery.
    /// No job is claimed and the historical work deadline is not extended.
    pub(crate) fn validate_fit_input_with_source(
        &self,
        batch: &CellQ24TrainingBatchV1,
        rule: CellQ24SgdRuleV1,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<Digest32, CellQ24TrainingErrorV1> {
        use CellQ24TrainingErrorV1::Binding;
        OriginalQ24DatasetReadV1::require_current_batch(source, batch)?;
        if let Some(source) = &batch.source {
            source.require_baseline(
                self.prefix
                    .request
                    .selected_bundle
                    .digest()
                    .map_err(|_| Binding("baseline bundle"))?,
            )?;
        }
        let optimizer = rule.digest(batch)?;
        let plan = CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
            self.prefix.clone(),
            self.scope.clone(),
            std::sync::Arc::clone(&self.baseline),
            self.head,
            optimizer,
        )?;
        let budget = &plan.prefix.request.budget;
        let expected_steps = u64::from(rule.epochs) * u64::from(batch.rows());
        let dataset = plan
            .prefix
            .receipts
            .last()
            .ok_or(Binding("Dataset receipt"))?;
        if !matches!(dataset.observation,
            LearningIterationObservationV1::Dataset { snapshot_digest, rows, bytes, .. }
                if snapshot_digest == batch.source_dataset && rows == batch.rows()
                    && bytes == batch.encoded.len() as u64)
            || batch.samples[0].input.len() != plan.baseline.input_width()
            || batch.rows() > budget.maximum_dataset_rows
            || batch.encoded.len() as u64 > budget.maximum_dataset_bytes
            || expected_steps > budget.maximum_training_steps
            || (12 + 8 * plan.baseline.heads.values.len()) as u64 > budget.maximum_artifact_bytes
        {
            return Err(Binding("original dataset, input shape or training quota"));
        }
        Ok(optimizer)
    }

    /// Reconstruct only already retained material. The durable owner must
    /// authenticate its original job/result; this never invokes optimization.
    pub(super) fn rebuild_candidate(
        &self,
        bytes: Vec<u8>,
        metrics: CellQ24TrainingMetricsV1,
    ) -> Result<CellQ24TrainedCandidateV1, CellQ24TrainingErrorV1> {
        use CellQ24TrainingErrorV1::Binding;
        let plan = CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
            self.prefix.clone(),
            self.scope.clone(),
            std::sync::Arc::clone(&self.baseline),
            self.head,
            metrics.optimizer_rule,
        )?;
        let update_rule = cell_q24_single_head_update_rule_v1(
            &plan.prefix.request.selected_bundle,
            plan.head,
            metrics.optimizer_rule,
        )?;
        if metrics.update_rule != update_rule {
            return Err(Binding("original retained update rule"));
        }
        let heads = codec::Matrix::decode(&bytes).map_err(CellQ24TrainingPlanErrorV1::from)?;
        let mut components = plan.baseline.components.clone();
        components.heads = Digest32::of_bytes(&bytes);
        let candidate = LoadedCellQ24ModelV1 {
            components: components.clone(),
            base: plan.baseline.base.clone(),
            organ: plan.baseline.organ.clone(),
            cell: plan.baseline.cell.clone(),
            encoder: plan.baseline.encoder.clone(),
            heads,
        };
        let model = plan
            .baseline
            .validate_single_head_candidate(candidate, plan.head)
            .map_err(CellQ24TrainingPlanErrorV1::from)?;
        let source_bundle = plan
            .prefix
            .request
            .selected_bundle
            .digest()
            .map_err(|_| Binding("baseline bundle"))?;
        let dataset = plan
            .prefix
            .receipts
            .last()
            .ok_or(Binding("Dataset receipt"))?;
        let LearningIterationObservationV1::Dataset {
            snapshot_digest, ..
        } = dataset.observation
        else {
            return Err(Binding("Dataset cut"));
        };
        let bundle = CellCompatibilityBundleV1 {
            artifact_id: StableId::new(format!(
                "q24-sgd:{}",
                Digest32::of_parts(&[
                    b"hepta.cell.q24.trained-candidate.v1\0",
                    plan.prefix.head_digest.as_array(),
                    update_rule.as_array(),
                    components.heads.as_array(),
                ])
            ))
            .map_err(|_| Binding("candidate identity"))?,
            generation: plan
                .prefix
                .request
                .selected_bundle
                .generation
                .next()
                .map_err(|_| Binding("candidate generation"))?,
            components,
            rollback_predecessor: Some(source_bundle),
            training_lineage: Some(CellTrainingLineageV1 {
                source_bundle,
                dataset: snapshot_digest,
                update_rule,
                evaluation_profile: plan.prefix.request.evaluation_profile,
            }),
        };
        bundle.digest().map_err(|_| Binding("candidate bundle"))?;
        Ok(CellQ24TrainedCandidateV1 {
            model,
            bundle,
            heads: bytes,
            metrics,
        })
    }
}
