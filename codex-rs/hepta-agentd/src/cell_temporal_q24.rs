//! Bounded diagonal recurrence through the existing generation owner. This is
//! a simple Q24 temporal kernel, not Mamba/S4D or a learned semantic encoder.
//! Parameters are immutable after loading. State belongs exclusively to the
//! original journal; a changed model requires the original explicit Reset.

use std::fs::File;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;

use crate::cell_composed_q24::codec;
use codec::Matrix;

pub struct CellTemporalQ24ModelFilesV1 {
    pub encoder: File,
    pub base: File,
    /// An n-by-1 HQ24M001 matrix containing the n diagonal coefficients.
    pub diagonal: File,
    /// First half of the rows are drives; the second half are predictions.
    pub heads: File,
}

pub struct LoadedCellTemporalQ24ModelV1 {
    components: CellBundleComponentsV1,
    encoder: Matrix,
    base: Matrix,
    diagonal: Vec<i64>,
    heads: Matrix,
}

pub struct CellTemporalQ24GenerationWorkerV1 {
    model: LoadedCellTemporalQ24ModelV1,
    manifest: CellBackendManifestV2,
    clock: Arc<dyn Fn() -> u64 + Send + Sync>,
}

impl LoadedCellTemporalQ24ModelV1 {
    /// Read only host-opened files under the existing Q24 decoder/asset limits.
    pub fn open_files(files: CellTemporalQ24ModelFilesV1) -> Result<Self, CellGenerationErrorV2> {
        let (bytes, encoder_digest) = codec::read(files.encoder)?;
        let encoder = Matrix::decode(&bytes)?;
        let (bytes, base_digest) = codec::read(files.base)?;
        let base = Matrix::decode(&bytes)?;
        let (bytes, diagonal_digest) = codec::read(files.diagonal)?;
        let diagonal = Matrix::decode(&bytes)?;
        let (bytes, head_digest) = codec::read(files.heads)?;
        let heads = Matrix::decode(&bytes)?;
        if encoder.rows != base.cols || diagonal.rows != base.rows || diagonal.cols != 1
            || heads.cols != base.rows || heads.rows % 2 != 0
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let components = CellBundleComponentsV1 {
            base: Digest32::of_parts(&[b"hepta.cell.temporal-q24.base.v1\0",
                base_digest.as_array(), diagonal_digest.as_array()]),
            organ_adapter: None,
            cell_adapter: None,
            encoder: encoder_digest,
            heads: head_digest,
            composition: pin(b"encoder;base-input+diagonal-state;clip;drive-prediction-heads"),
            tokenizer: pin(b"no-tokenizer;HQ24I001-or-HQ24STOP"),
            normalizer: pin(b"identity;input-range-plus-minus-eight"),
            calibration: pin(b"raw-drive-prediction;no-probability-calibration"),
            numeric_profile: pin(b"Q24-i64;dot-i128;truncate-toward-zero;clip-eight-each-matvec-and-state"),
            output_schema: pin(b"HQ24O001;u16le-width;drive-then-prediction-i64le"),
            state_schema: pin(b"HQ24S001;weights32;count-u64le;width-u16le;hidden-i64le"),
            state_semantics: pin(b"diagonal-recurrence;canonical-initial;bound-weights;stop-preserves;reset-on-model-change"),
        };
        Ok(Self { components, encoder, base, diagonal: diagonal.apply(&[codec::Q]), heads })
    }

    pub fn components(&self) -> &CellBundleComponentsV1 { &self.components }
    pub fn input_width(&self) -> usize { self.encoder.cols }
    pub fn output_width(&self) -> usize { self.heads.rows / 2 }
    pub fn state_bytes(&self) -> usize { 50 + 8 * self.base.rows }
    /// The host puts this canonical zero state into the original journal config.
    pub fn initial_state(&self) -> Vec<u8> {
        let mut state = b"HQ24S001".to_vec();
        state.extend_from_slice(self.effective_weights_digest().as_array());
        state.extend_from_slice(&0_u64.to_le_bytes());
        state.extend_from_slice(&(self.base.rows as u16).to_le_bytes());
        state.resize(self.state_bytes(), 0);
        state
    }
    pub fn effective_weights_digest(&self) -> Digest32 {
        Digest32::of_parts(&[b"hepta.cell.temporal-q24.effective.v1\0",
            self.components.base.as_array(), self.components.encoder.as_array(),
            self.components.heads.as_array(), self.components.composition.as_array(),
            self.components.numeric_profile.as_array()])
    }

    pub fn into_worker(self, bundle: &CellCompatibilityBundleV1, manifest: CellBackendManifestV2,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>) -> Result<CellTemporalQ24GenerationWorkerV1, CellGenerationErrorV2>
    {
        manifest.digest()?;
        if manifest.profile != CellTemporalQ24GenerationWorkerV1::PROFILE
            || bundle.components != self.components
            || manifest.bundle_digest != bundle.digest().map_err(|_| CellGenerationErrorV2::InvalidBinding)?.into_array()
            || manifest.encoder != Some(self.components.encoder.into_array())
            || manifest.head != Some(self.components.heads.into_array())
            || manifest.memory.is_some() || manifest.world_model.is_some() || manifest.decoder.is_some()
            || manifest.input_schema != CellTemporalQ24GenerationWorkerV1::input_schema_digest()
            || manifest.state_schema != self.components.state_schema.into_array()
            || manifest.output_schema != self.components.output_schema.into_array()
            || manifest.learning != (CellLearningBindingV2::Frozen { weights: self.effective_weights_digest().into_array() })
            || manifest.max_input_bytes as usize != 10 + 8 * self.input_width()
            || manifest.max_state_bytes as usize != self.state_bytes()
            || manifest.max_delta_bytes as usize != 10 + 16 * self.output_width()
            || manifest.max_step_cost_entries < 3
        { return Err(CellGenerationErrorV2::InvalidBinding); }
        Ok(CellTemporalQ24GenerationWorkerV1 { model: self, manifest, clock })
    }
}

impl CellTemporalQ24GenerationWorkerV1 {
    pub const PROFILE: &'static str = "cell-diagonal-q24-temporal-v1";
    pub fn input_schema_digest() -> [u8; 32] {
        pin(b"HQ24I001;u16le-width;i64le-Q24;or-exact-HQ24STOP").into_array()
    }

    fn decode_state(&self, request: &CellGenerationRequestV2) -> Result<(u64, Vec<i64>), CellGenerationErrorV2> {
        let bytes = &request.predecessor.state;
        let width = self.model.base.rows;
        if bytes.len() != self.model.state_bytes() || &bytes[..8] != b"HQ24S001"
            || &bytes[8..40] != self.model.effective_weights_digest().as_array()
            || usize::from(u16::from_le_bytes([bytes[48], bytes[49]])) != width
        { return Err(CellGenerationErrorV2::InvalidBinding); }
        let count = u64::from_le_bytes(bytes[40..48].try_into().map_err(|_| CellGenerationErrorV2::InvalidBinding)?);
        if count > request.predecessor.revision || count == 0 && bytes != &self.model.initial_state() {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let mut input = b"HQ24I001".to_vec();
        input.extend_from_slice(&(width as u16).to_le_bytes());
        input.extend_from_slice(&bytes[50..]);
        Ok((count, codec::input(&input, width)?))
    }

    fn forward(&self, request: &CellGenerationRequestV2, count: u64, previous: &[i64])
        -> Result<(Vec<u8>, Vec<u8>), CellGenerationErrorV2>
    {
        let count = count.checked_add(1).ok_or(CellGenerationErrorV2::Capacity)?;
        let input = codec::input(&request.input, self.model.input_width())?;
        let encoded = self.model.encoder.apply(&input);
        let mut hidden = self.model.base.apply(&encoded);
        let limit = 8 * i128::from(codec::Q);
        for ((value, prior), diagonal) in hidden.iter_mut().zip(previous).zip(&self.model.diagonal) {
            *value = (i128::from(*value) + i128::from(*prior) * i128::from(*diagonal) / i128::from(codec::Q))
                .clamp(-limit, limit) as i64;
        }
        let mut state = b"HQ24S001".to_vec();
        state.extend_from_slice(self.model.effective_weights_digest().as_array());
        state.extend_from_slice(&count.to_le_bytes());
        state.extend_from_slice(&(hidden.len() as u16).to_le_bytes());
        for value in &hidden { state.extend_from_slice(&value.to_le_bytes()); }
        let heads = self.model.heads.apply(&hidden);
        let mut output = b"HQ24O001".to_vec();
        output.extend_from_slice(&(self.model.output_width() as u16).to_le_bytes());
        for value in heads { output.extend_from_slice(&value.to_le_bytes()); }
        Ok((state, output))
    }
}

fn pin(label: &[u8]) -> Digest32 { Digest32::of_parts(&[b"hepta.cell.temporal-q24.v1\0", label]) }

impl CellGenerationWorkerV2 for CellTemporalQ24GenerationWorkerV1 {
    fn execute(&self, manifest: &CellBackendManifestV2, request: &CellGenerationRequestV2,
        cancellation: &AtomicBool) -> Result<CellGenerationProposalV2, CellGenerationErrorV2>
    {
        let started = Instant::now();
        let request_digest = request.digest()?;
        if manifest != &self.manifest || request.predecessor.manifest_digest != manifest.digest()?
            || request.predecessor.stopped || request.predecessor.prefix.len() > manifest.max_prefix_bytes as usize
        { return Err(CellGenerationErrorV2::InvalidBinding); }
        let (count, previous) = self.decode_state(request)?;
        let initial = (self.clock)();
        if initial == 0 || initial < request.admitted_at_micros { return Err(CellGenerationErrorV2::Unavailable); }
        let mut state = request.predecessor.state.clone();
        let mut output = Vec::new();
        let mut disposition = if cancellation.load(Ordering::Acquire) {
            CellGenerationDispositionV2::Cancelled
        } else if initial >= request.deadline_micros {
            CellGenerationDispositionV2::DeadlineExceeded
        } else if request.input == b"HQ24STOP" {
            CellGenerationDispositionV2::Stopped
        } else {
            match self.forward(request, count, &previous) {
                Ok((next, delta)) => { state = next; output = delta; CellGenerationDispositionV2::Advanced }
                Err(CellGenerationErrorV2::Capacity) => return Err(CellGenerationErrorV2::Capacity),
                Err(_) => CellGenerationDispositionV2::Rejected,
            }
        };
        let completed = (self.clock)();
        if completed < initial { return Err(CellGenerationErrorV2::Unavailable); }
        if cancellation.load(Ordering::Acquire) { disposition = CellGenerationDispositionV2::Cancelled; }
        else if completed >= request.deadline_micros { disposition = CellGenerationDispositionV2::DeadlineExceeded; }
        if !matches!(disposition, CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped) {
            state = request.predecessor.state.clone(); output.clear();
        }
        let mut cost = CellTaskCostV2::new(CellTaskCostIdentityV2 { task_digest: request.task_digest,
            source_digest: manifest.source_digest }).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        cost.record(CellCostEntryV2 {
            event_id: Digest32::of_parts(&[b"hepta.cell.temporal-q24.cost.v1\0", &request_digest]).into_array(),
            identity: cost.identity(), stage: CellCostStageV2::Inference,
            outcome: match disposition {
                CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped => CellCostOutcomeV2::Succeeded,
                CellGenerationDispositionV2::Cancelled | CellGenerationDispositionV2::DeadlineExceeded => CellCostOutcomeV2::Cancelled,
                CellGenerationDispositionV2::Rejected => CellCostOutcomeV2::Rejected,
                CellGenerationDispositionV2::Failed => CellCostOutcomeV2::Failed,
            },
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 { wall_micros: Some(u64::try_from(started.elapsed().as_micros())
                .map_err(|_| CellGenerationErrorV2::Capacity)?), ..CellCostMetricsV2::default() },
        }).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        Ok(CellGenerationProposalV2 { request_digest, bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest, device_digest: manifest.device_digest,
            successor_state: state, output_delta: output, disposition, cost })
    }
}

#[cfg(test)]
#[path = "cell_temporal_q24_tests.rs"]
mod tests;
