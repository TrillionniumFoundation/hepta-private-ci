//! One complete frozen base/organ/cell composition for bounded control models.
//! Host-opened bytes become immutable matrices. The original generation control,
//! journal, CURRENT publication and learning owners retain all authority. This
//! profile is stateless and requires Reset at a task boundary; it is not an LLM
//! or a generic adapter ABI. Runtime/device provenance remains host admission.
//! Each successful task has one forward step. At most 16,384 bounded i128
//! multiply/add terms execute between live cancellation/deadline checks; a late
//! result is withheld. Loader time, CPU/energy and deployment provenance are not
//! inferred from this worker's measured inference wall interval.

use std::fs::File;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationProposalV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellGenerationWorkerV2;
use codex_hepta_neuron::CellLearningBindingV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;

#[path = "cell_composed_q24_codec.rs"]
mod codec;
use codec::Adapter;
use codec::Matrix;

#[path = "cell_composed_q24_training_plan.rs"]
mod training_plan;
pub use training_plan::CellQ24SingleHeadTrainingPlanV1;
pub use training_plan::CellQ24SgdRuleV1;
pub use training_plan::CellQ24TrainedCandidateV1;
pub use training_plan::CellQ24TrainingBatchV1;
pub use training_plan::CellQ24TrainingErrorV1;
pub use training_plan::CellQ24TrainingMetricsV1;
pub use training_plan::CellQ24TrainingOutcomeV1;
pub use training_plan::CellQ24TrainingOwnerErrorV1;
pub use training_plan::CellQ24TrainingOwnerV1;
pub use training_plan::CellQ24TrainingPlanErrorV1;
pub use training_plan::CellQ24TrainingSampleV1;
pub use training_plan::cell_q24_single_head_update_rule_v1;

pub struct CellQ24ModelFilesV1 {
    pub base: File,
    pub organ_adapter: Option<File>,
    pub cell_adapter: Option<File>,
    pub encoder: File,
    /// First half of the rows are drives; the second half are predictions.
    pub heads: File,
}

/// One linear row in the fixed drive/prediction heads matrix. Indices are
/// zero-based within their respective halves, not arbitrary byte ranges.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellQ24PrivateHeadV1 {
    Drive { index: u16 },
    Prediction { index: u16 },
}

/// Actual parsed model bytes; callers cannot replace pins after loading.
pub struct LoadedCellQ24ModelV1 {
    components: CellBundleComponentsV1,
    base: Matrix,
    organ: Option<Adapter>,
    cell: Option<Adapter>,
    encoder: Matrix,
    heads: Matrix,
}

pub struct CellQ24GenerationWorkerV1 {
    model: Arc<LoadedCellQ24ModelV1>,
    manifest: CellBackendManifestV2,
    clock: Arc<dyn Fn() -> u64 + Send + Sync>,
}

impl LoadedCellQ24ModelV1 {
    /// Consume already opened files. No path is reopened and no executable is
    /// selected by task input. Limits apply before parsing and all shapes must
    /// match the same encoder -> base+BA+BA -> drive/prediction graph.
    pub fn open_files(files: CellQ24ModelFilesV1) -> Result<Self, CellGenerationErrorV2> {
        let (base_bytes, base_digest) = codec::read(files.base)?;
        let base = Matrix::decode(&base_bytes)?;
        let (encoder_bytes, encoder_digest) = codec::read(files.encoder)?;
        let encoder = Matrix::decode(&encoder_bytes)?;
        let (head_bytes, head_digest) = codec::read(files.heads)?;
        let heads = Matrix::decode(&head_bytes)?;
        if encoder.rows != base.cols || heads.cols != base.rows || heads.rows % 2 != 0 {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let load_adapter = |file| -> Result<_, CellGenerationErrorV2> {
            let (bytes, digest) = codec::read(file)?;
            Ok((Adapter::decode(&bytes, &base)?, digest))
        };
        let organ = files.organ_adapter.map(load_adapter).transpose()?;
        let cell = files.cell_adapter.map(load_adapter).transpose()?;
        let components = CellBundleComponentsV1 {
            base: base_digest,
            organ_adapter: organ.as_ref().map(|(_, digest)| *digest),
            cell_adapter: cell.as_ref().map(|(_, digest)| *digest),
            heads: head_digest,
            encoder: encoder_digest,
            composition: pin(
                b"matvec-clip-encoder;base+organ-BA+cell-BA;sum-clip;drive-prediction-heads",
            ),
            tokenizer: pin(b"no-tokenizer;HQ24I001-vector"),
            normalizer: pin(b"identity;input-range-plus-minus-eight"),
            calibration: pin(b"raw-drive-prediction;no-probability-calibration"),
            numeric_profile: pin(
                b"Q24-i64;dot-i128;truncate-toward-zero;clip-eight-after-each-matvec",
            ),
            output_schema: pin(b"HQ24O001;u16le-width;drive-then-prediction-i64le"),
            state_schema: pin(b"empty-stateless-state"),
            state_semantics: pin(b"one-task-one-step;reset-only;no-recurrent-state"),
        };
        Ok(Self {
            components,
            base,
            organ: organ.map(|(adapter, _)| adapter),
            cell: cell.map(|(adapter, _)| adapter),
            encoder,
            heads,
        })
    }

    /// Validate actual already-loaded candidate material against this baseline.
    /// Exactly one selected row must change; all other coefficients, shapes,
    /// adapters and semantic components remain equal. HQ24 matrices/adapters
    /// have canonical, exact-length integer encodings, so these comparisons
    /// preserve the frozen file bytes as well as their component digests.
    ///
    /// Returns the immutable loaded candidate for the existing worker/bundle
    /// checks. This proves no training, useful output, evidence or adoption
    /// authority. Evaluation must execute these actual quantized bytes.
    pub fn validate_single_head_candidate(
        &self,
        candidate: Self,
        head: CellQ24PrivateHeadV1,
    ) -> Result<Self, CellGenerationErrorV2> {
        let (index, offset) = match head {
            CellQ24PrivateHeadV1::Drive { index } => (usize::from(index), 0),
            CellQ24PrivateHeadV1::Prediction { index } => (usize::from(index), self.heads.rows / 2),
        };
        if index >= self.heads.rows / 2
            || candidate.heads.rows != self.heads.rows
            || candidate.heads.cols != self.heads.cols
            || candidate.base != self.base
            || candidate.encoder != self.encoder
            || candidate.organ != self.organ
            || candidate.cell != self.cell
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let mut frozen = candidate.components.clone();
        frozen.heads = self.components.heads;
        let start = (offset + index) * self.heads.cols;
        let end = start + self.heads.cols;
        if frozen != self.components
            || candidate.heads.values[..start] != self.heads.values[..start]
            || candidate.heads.values[end..] != self.heads.values[end..]
            || candidate.heads.values[start..end] == self.heads.values[start..end]
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(candidate)
    }

    pub fn components(&self) -> &CellBundleComponentsV1 {
        &self.components
    }

    pub fn input_width(&self) -> usize {
        self.encoder.cols
    }
    pub fn output_width(&self) -> usize {
        self.heads.rows / 2
    }

    fn hidden(&self, input: &[i64]) -> Vec<i64> {
        let encoded = self.encoder.apply(input);
        let mut hidden = self.base.apply(&encoded);
        let apply = |adapter: &Option<Adapter>| {
            adapter.as_ref().map_or_else(
                || vec![0; hidden.len()],
                |adapter| adapter.up.apply(&adapter.down.apply(&encoded)),
            )
        };
        let organ = apply(&self.organ);
        let cell = apply(&self.cell);
        codec::combine(&mut hidden, &organ, &cell);
        hidden
    }

    /// Identity of the actual executable factor graph. Q24 rounding makes it
    /// deliberately distinct from multiplying a rounded dense merged matrix.
    pub fn effective_weights_digest(&self) -> Digest32 {
        effective(&self.components)
    }

    pub fn into_worker(
        self,
        bundle: &CellCompatibilityBundleV1,
        manifest: CellBackendManifestV2,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<CellQ24GenerationWorkerV1, CellGenerationErrorV2> {
        Arc::new(self).shared_worker(bundle, manifest, clock)
    }

    /// Reuse this immutable parsed allocation across separately controlled
    /// Cell owners. Each worker validates and retains its complete manifest
    /// and clock; requests, activations, state, journal and ACK remain local to
    /// the original owner. This supplies no admission or cross-Cell authority.
    pub fn shared_worker(
        self: &Arc<Self>,
        bundle: &CellCompatibilityBundleV1,
        manifest: CellBackendManifestV2,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<CellQ24GenerationWorkerV1, CellGenerationErrorV2> {
        validate_manifest(bundle, &manifest)?;
        if bundle.components != self.components
            || manifest.max_input_bytes as usize != 10 + 8 * self.encoder.cols
            || manifest.max_delta_bytes as usize != 10 + 8 * self.heads.rows
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(CellQ24GenerationWorkerV1 {
            model: Arc::clone(self),
            manifest,
            clock,
        })
    }
}

impl CellQ24GenerationWorkerV1 {
    pub const PROFILE: &'static str = "cell-composed-q24-control-v1";
    pub fn input_schema_digest() -> [u8; 32] {
        pin(b"HQ24I001;u16le-width;i64le-Q24").into_array()
    }
}

pub(crate) fn validate_manifest(
    bundle: &CellCompatibilityBundleV1,
    manifest: &CellBackendManifestV2,
) -> Result<(), CellGenerationErrorV2> {
    manifest.digest()?;
    let c = &bundle.components;
    if manifest.profile != CellQ24GenerationWorkerV1::PROFILE
        || manifest.bundle_digest
            != bundle
                .digest()
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?
                .into_array()
        || manifest.encoder != Some(c.encoder.into_array())
        || manifest.head != Some(c.heads.into_array())
        || manifest.memory.is_some()
        || manifest.world_model.is_some()
        || manifest.decoder.is_some()
        || manifest.input_schema != CellQ24GenerationWorkerV1::input_schema_digest()
        || manifest.state_schema != c.state_schema.into_array()
        || manifest.output_schema != c.output_schema.into_array()
        || manifest.learning
            != (CellLearningBindingV2::Frozen {
                weights: effective(c).into_array(),
            })
        || manifest.max_input_bytes > 522
        || manifest.max_state_bytes != 1
        || manifest.max_delta_bytes > 522
        || manifest.max_prefix_bytes != manifest.max_delta_bytes
        || manifest.max_step_cost_entries < 3
        || c.composition
            != pin(b"matvec-clip-encoder;base+organ-BA+cell-BA;sum-clip;drive-prediction-heads")
        || c.tokenizer != pin(b"no-tokenizer;HQ24I001-vector")
        || c.normalizer != pin(b"identity;input-range-plus-minus-eight")
        || c.calibration != pin(b"raw-drive-prediction;no-probability-calibration")
        || c.numeric_profile
            != pin(b"Q24-i64;dot-i128;truncate-toward-zero;clip-eight-after-each-matvec")
        || c.output_schema != pin(b"HQ24O001;u16le-width;drive-then-prediction-i64le")
        || c.state_schema != pin(b"empty-stateless-state")
        || c.state_semantics != pin(b"one-task-one-step;reset-only;no-recurrent-state")
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(())
}

fn pin(label: &[u8]) -> Digest32 {
    Digest32::of_parts(&[b"hepta.cell.composed-q24.v1\0", label])
}

fn effective(c: &CellBundleComponentsV1) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.cell.composed-q24.effective-factor-graph.v1\0",
        c.base.as_array(),
        c.organ_adapter.unwrap_or(Digest32::ZERO).as_array(),
        c.cell_adapter.unwrap_or(Digest32::ZERO).as_array(),
        c.encoder.as_array(),
        c.heads.as_array(),
        c.composition.as_array(),
        c.numeric_profile.as_array(),
    ])
}

impl CellGenerationWorkerV2 for CellQ24GenerationWorkerV1 {
    fn execute(
        &self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
        cancellation: &AtomicBool,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        let started = Instant::now();
        let request_digest = request.digest()?;
        if manifest != &self.manifest
            || request.predecessor.manifest_digest != manifest.digest()?
            || !request.predecessor.state.is_empty()
            || !request.predecessor.prefix.is_empty()
            || request.predecessor.stopped
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let initial = (self.clock)();
        if initial == 0 || initial < request.admitted_at_micros {
            return Err(CellGenerationErrorV2::Unavailable);
        }
        let mut output = Vec::new();
        let mut disposition = if cancellation.load(Ordering::Acquire) {
            CellGenerationDispositionV2::Cancelled
        } else if initial >= request.deadline_micros {
            CellGenerationDispositionV2::DeadlineExceeded
        } else if let Ok(input) = codec::input(&request.input, self.model.encoder.cols) {
            let hidden = self.model.hidden(&input);
            let heads = self.model.heads.apply(&hidden);
            output.extend_from_slice(b"HQ24O001");
            output.extend_from_slice(&((heads.len() / 2) as u16).to_le_bytes());
            for value in heads {
                output.extend_from_slice(&value.to_le_bytes());
            }
            CellGenerationDispositionV2::Stopped
        } else {
            CellGenerationDispositionV2::Rejected
        };
        let completed = (self.clock)();
        if completed < initial {
            return Err(CellGenerationErrorV2::Unavailable);
        }
        if cancellation.load(Ordering::Acquire) {
            disposition = CellGenerationDispositionV2::Cancelled;
        } else if completed >= request.deadline_micros {
            disposition = CellGenerationDispositionV2::DeadlineExceeded;
        }
        if disposition != CellGenerationDispositionV2::Stopped {
            output.clear();
        }
        let mut cost = CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        cost.record(CellCostEntryV2 {
            event_id: Digest32::of_parts(&[b"hepta.cell.composed-q24.cost.v1\0", &request_digest])
                .into_array(),
            identity: cost.identity(),
            stage: CellCostStageV2::Inference,
            outcome: match disposition {
                CellGenerationDispositionV2::Stopped | CellGenerationDispositionV2::Advanced => {
                    CellCostOutcomeV2::Succeeded
                }
                CellGenerationDispositionV2::Cancelled
                | CellGenerationDispositionV2::DeadlineExceeded => CellCostOutcomeV2::Cancelled,
                CellGenerationDispositionV2::Rejected => CellCostOutcomeV2::Rejected,
                CellGenerationDispositionV2::Failed => CellCostOutcomeV2::Failed,
            },
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(
                    u64::try_from(started.elapsed().as_micros())
                        .map_err(|_| CellGenerationErrorV2::Capacity)?,
                ),
                ..CellCostMetricsV2::default()
            },
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        Ok(CellGenerationProposalV2 {
            request_digest,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: Vec::new(),
            output_delta: output,
            disposition,
            cost,
        })
    }
}
