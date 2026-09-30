//! Backend-neutral DecisionCell composition through the unified V2 Neuron owner.
//!
//! The selected model produces both the bounded Neuron transition tensors and
//! typed advisory heads in one execution.  The Neuron owner remains the sole
//! checkpoint/result writer; the typed receipt is attached to the same HPTNGS02
//! commit through HPTNFR02 and never creates a second ledger or effect owner.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_infer_core::DecisionCellContractError;
use codex_hepta_infer_core::DecisionCellObservationV1;
use codex_hepta_infer_core::DecisionCellReceiptV1;
use codex_hepta_infer_core::DecisionCellRequestV1;
use codex_hepta_infer_core::DecisionCellRuntimeTupleV1;
use codex_hepta_infer_core::DecisionCellTerminalStatusV1;
use codex_hepta_infer_core::build_decision_cell_receipt_v1;
use codex_hepta_infer_core::decision_cell_head_set_digest_v1;
use codex_hepta_infer_core::decision_cell_request_digest_v1;
use codex_hepta_infer_core::decision_cell_runtime_tuple_digest_v1;
use codex_hepta_infer_core::decode_decision_cell_receipt_v1;
use codex_hepta_infer_core::encode_decision_cell_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AnchorWitnessStore;
use crate::DurableNeuronModelPort;
use crate::NeuronAdmissionGuard;
use crate::NeuronBodyBundleIdentityV1;
use crate::NeuronModelError;
use crate::NeuronModelOutputV1;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::NeuronModelResolutionV2;
use crate::NeuronReceiptExtensionV2;
use crate::NeuronRuntimeCommitV2;
use crate::NeuronRuntimeConfigV1;
use crate::NeuronRuntimeOutputV1;
use crate::NeuronRuntimeV2;
use crate::NeuronRuntimeV2Error;
use crate::NeuronTickInputV1;

#[path = "decision_cell_lifecycle_v2.rs"]
mod lifecycle;

const RECEIPT_SCHEMA_ID: &str = "hepta.decision-cell.receipt.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DecisionCellModelFailureV2 {
    Unavailable,
    Rejected,
    TimedOut,
    Cancelled,
    Indeterminate,
}

impl DecisionCellModelFailureV2 {
    const fn into_neuron(self) -> NeuronModelError {
        match self {
            Self::Unavailable => NeuronModelError::Unavailable,
            Self::Rejected => NeuronModelError::Rejected,
            Self::TimedOut | Self::Cancelled | Self::Indeterminate => {
                NeuronModelError::Indeterminate
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellModelExecutionV2 {
    pub neuron_output: NeuronModelOutputV1,
    pub runtime_tuple: DecisionCellRuntimeTupleV1,
    pub observation: DecisionCellObservationV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DecisionCellModelResolutionV2 {
    NotStarted,
    Observed(Box<DecisionCellModelExecutionV2>),
    Unknown,
}

/// Physical backend contract for one exact selected DecisionCell bundle.
/// Implementations must use one model execution for the Neuron tensors and all
/// typed heads.  `reconcile` may observe prior work but may never blindly replay
/// an operation whose dispatch status is unknown.
pub trait DecisionCellModelPortV2 {
    fn infer(
        &mut self,
        request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelExecutionV2, DecisionCellModelFailureV2>;

    fn reconcile(
        &mut self,
        _request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelResolutionV2, DecisionCellModelFailureV2> {
        Ok(DecisionCellModelResolutionV2::Unknown)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellInvocationV2 {
    pub request: DecisionCellRequestV1,
    pub selected_runtime: DecisionCellRuntimeTupleV1,
}

#[derive(Debug)]
pub enum DecisionCellRuntimeV2Error {
    Contract(DecisionCellContractError),
    Binding(&'static str),
    Runtime(NeuronRuntimeV2Error),
}

impl fmt::Display for DecisionCellRuntimeV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DecisionCellRuntimeV2Error {}

impl From<DecisionCellContractError> for DecisionCellRuntimeV2Error {
    fn from(value: DecisionCellContractError) -> Self {
        Self::Contract(value)
    }
}

impl From<NeuronRuntimeV2Error> for DecisionCellRuntimeV2Error {
    fn from(value: NeuronRuntimeV2Error) -> Self {
        Self::Runtime(value)
    }
}

impl DecisionCellInvocationV2 {
    fn validate(
        &self,
        config: &NeuronRuntimeConfigV1,
        body: &NeuronBodyBundleIdentityV1,
        body_digest: Digest32,
        tick: &NeuronTickInputV1,
    ) -> Result<(), DecisionCellRuntimeV2Error> {
        decision_cell_request_digest_v1(&self.request)?;
        decision_cell_runtime_tuple_digest_v1(&self.selected_runtime)?;
        let bundle = &self.selected_runtime.parameter_bundle;
        let bundle_digest = bundle.semantic_digest()?;
        let head_set_digest = decision_cell_head_set_digest_v1(bundle)?;
        let previous_state_digest = if tick.checkpoint_digest.is_zero() {
            None
        } else {
            Some(tick.checkpoint_digest)
        };
        if self.request.request_id != tick.tick_id
            || self.request.generation != config.generation
            || self.request.model_id != config.model_id
            || self.request.model_manifest_digest != config.model_manifest_digest
            || self.request.weights_digest != config.weights_digest
            || self.request.objective_digest != tick.objective_digest
            || self.request.ndu_digest != tick.ndu_snapshot_digest
            || self.request.body_digest != body_digest
            || self.request.previous_state_digest != previous_state_digest
            || self.request.feature_vector_q24 != tick.feature_vector_q24
            || self.request.deadline_monotonic_micros < tick.monotonic_time_micros
            || tick.body_generation != Some(body.body_generation.get())
            || self.request.parameter_bundle_digest != bundle_digest
        {
            return Err(DecisionCellRuntimeV2Error::Binding("request context"));
        }
        if self.selected_runtime.model_id != config.model_id
            || self.selected_runtime.model_manifest_digest != config.model_manifest_digest
            || self.selected_runtime.weights_digest != config.weights_digest
            || self.selected_runtime.tokenizer_digest != config.tokenizer_digest
            || self.selected_runtime.preprocessor_digest != config.preprocessor_digest
            || self.selected_runtime.quantization_digest != config.quantization_digest
            || self.selected_runtime.runtime_digest != config.runtime_digest
            || self.selected_runtime.device_digest != config.device_digest
            || bundle.base_bundle_digest != body.base_bundle_digest
            || bundle.base_bundle_digest != config.encoder_digest
            || bundle.organ_id != body.organ_id
            || bundle.organ_bundle_digest != body.organ_bundle_digest
            || bundle.cell_slot_id != body.cell_slot_id
            || bundle.cell_bundle_digest != body.cell_bundle_digest
            || bundle.effective_parameter_digest != body.effective_parameter_digest
            || bundle.calibration_artifact_digest != config.calibration.calibration_artifact_digest
            || bundle.ood_artifact_digest != config.calibration.ood_artifact_digest
            || head_set_digest != config.head_digest
        {
            return Err(DecisionCellRuntimeV2Error::Binding(
                "selected parameter bundle",
            ));
        }
        Ok(())
    }
}

struct DecisionCellNeuronAdapterV2<'a, M> {
    model: &'a mut M,
    invocation: &'a DecisionCellInvocationV2,
    expected_neuron_request: NeuronModelRequestV1,
    pending: Option<DecisionCellModelExecutionV2>,
}

impl<'a, M> DecisionCellNeuronAdapterV2<'a, M>
where
    M: DecisionCellModelPortV2,
{
    fn new(
        model: &'a mut M,
        invocation: &'a DecisionCellInvocationV2,
        config: &NeuronRuntimeConfigV1,
        body: &NeuronBodyBundleIdentityV1,
        body_digest: Digest32,
        tick: &NeuronTickInputV1,
    ) -> Result<Self, DecisionCellRuntimeV2Error> {
        invocation.validate(config, body, body_digest, tick)?;
        Ok(Self {
            model,
            invocation,
            expected_neuron_request: NeuronModelRequestV1 {
                request_id: tick.tick_id.clone(),
                config_id: config.config_id.clone(),
                generation: config.generation,
                model_id: config.model_id.clone(),
                encoder_digest: config.encoder_digest,
                head_digest: config.head_digest,
                weights_digest: config.weights_digest,
                input_digest: decision_cell_input_digest_v2(invocation, tick)?,
                feature_vector_q24: tick.feature_vector_q24.clone(),
                expected_output_width: config.state_width,
            },
            pending: None,
        })
    }

    fn admit_execution(
        &mut self,
        execution: DecisionCellModelExecutionV2,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        if execution.runtime_tuple != self.invocation.selected_runtime
            || !matches!(
                execution.observation.status,
                DecisionCellTerminalStatusV1::Succeeded
            )
            || !runtime_tuple_matches_output(&execution.runtime_tuple, &execution.neuron_output)
        {
            return Err(NeuronModelError::Rejected);
        }
        let output = execution.neuron_output.clone();
        self.pending = Some(execution);
        Ok(output)
    }
}

impl<M> NeuronModelPort for DecisionCellNeuronAdapterV2<'_, M>
where
    M: DecisionCellModelPortV2,
{
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        if request != &self.expected_neuron_request {
            return Err(NeuronModelError::Rejected);
        }
        let execution = self
            .model
            .infer(&self.invocation.request)
            .map_err(DecisionCellModelFailureV2::into_neuron)?;
        self.admit_execution(execution)
    }
}

impl<M> DurableNeuronModelPort for DecisionCellNeuronAdapterV2<'_, M>
where
    M: DecisionCellModelPortV2,
{
    fn reconcile(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        if request != &self.expected_neuron_request {
            return Err(NeuronModelError::Rejected);
        }
        match self
            .model
            .reconcile(&self.invocation.request)
            .map_err(DecisionCellModelFailureV2::into_neuron)?
        {
            DecisionCellModelResolutionV2::NotStarted => Ok(NeuronModelResolutionV2::NotStarted),
            DecisionCellModelResolutionV2::Observed(execution) => self
                .admit_execution(*execution)
                .map(Box::new)
                .map(NeuronModelResolutionV2::Observed),
            DecisionCellModelResolutionV2::Unknown => Ok(NeuronModelResolutionV2::Unknown),
        }
    }

    fn receipt_extension(
        &mut self,
        request: &NeuronModelRequestV1,
        model_output: &NeuronModelOutputV1,
        runtime_output: &NeuronRuntimeOutputV1,
    ) -> Result<Option<NeuronReceiptExtensionV2>, NeuronModelError> {
        if request != &self.expected_neuron_request
            || runtime_output.model_runtime != model_output.runtime_receipt
        {
            return Err(NeuronModelError::Rejected);
        }
        let Some(mut execution) = self.pending.take() else {
            return Err(NeuronModelError::Rejected);
        };
        if execution.neuron_output != *model_output {
            return Err(NeuronModelError::Rejected);
        }
        // Trust and resource facts come from the calibrated Neuron owner and
        // measured runtime receipt, never from model-authored typed heads.
        execution.observation.confidence_ppm = runtime_output.tick.confidence_ppm;
        execution.observation.ood_ppm = runtime_output.tick.ood_ppm;
        execution.observation.observed_memory_bytes = model_output.runtime_receipt.resident_bytes;
        execution.observation.transient_allocation_bytes = model_output.transient_allocation_bytes;
        execution.observation.queue_age_micros = model_output.queue_age_micros;
        execution.observation.latency_micros = model_output.runtime_receipt.latency_micros;
        if runtime_output.tick.abstain {
            execution.observation.disposition_scores_q24 = [0, 0, 1, 0, 0, 0];
        }
        let receipt = build_decision_cell_receipt_v1(
            &self.invocation.request,
            execution.runtime_tuple,
            execution.observation,
        )
        .map_err(|_| NeuronModelError::Rejected)?;
        let payload = encode_decision_cell_receipt_v1(&self.invocation.request, &receipt)
            .map_err(|_| NeuronModelError::Rejected)?;
        let schema_id = StableId::new(RECEIPT_SCHEMA_ID).map_err(|_| NeuronModelError::Rejected)?;
        NeuronReceiptExtensionV2::new(schema_id, 1, payload)
            .map(Some)
            .map_err(|_| NeuronModelError::Rejected)
    }
}

fn runtime_tuple_matches_output(
    runtime: &DecisionCellRuntimeTupleV1,
    output: &NeuronModelOutputV1,
) -> bool {
    let observed = &output.runtime_receipt;
    runtime.model_id == observed.model_id
        && runtime.model_manifest_digest == observed.model_manifest_digest
        && runtime.weights_digest == observed.weights_digest
        && runtime.tokenizer_digest == observed.tokenizer_digest
        && runtime.preprocessor_digest == observed.preprocessor_digest
        && runtime.quantization_digest == observed.quantization_digest
        && runtime.runtime_digest == observed.runtime_digest
        && runtime.device_digest == observed.device_identity_digest
}

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    pub fn tick_decision_cell_guarded<M, G>(
        &mut self,
        model: &mut M,
        invocation: &DecisionCellInvocationV2,
        input: NeuronTickInputV1,
        guard: &mut G,
    ) -> Result<NeuronRuntimeCommitV2, DecisionCellRuntimeV2Error>
    where
        M: DecisionCellModelPortV2,
        G: NeuronAdmissionGuard,
    {
        let (config, body, body_digest) = self.decision_cell_context();
        let mut adapter =
            DecisionCellNeuronAdapterV2::new(model, invocation, config, body, body_digest, &input)?;
        let input_digest = decision_cell_input_digest_v2(invocation, &input)?;
        self.tick_with_input_digest_guarded(&mut adapter, input, input_digest, guard)
            .map_err(DecisionCellRuntimeV2Error::Runtime)
    }
}

/// Domain separation preserves ordinary tick identities while binding every
/// DecisionCell candidate, frontier and deadline before reservation/dispatch.
fn decision_cell_input_digest_v2(
    invocation: &DecisionCellInvocationV2,
    input: &NeuronTickInputV1,
) -> Result<Digest32, DecisionCellRuntimeV2Error> {
    let tick_digest = input
        .semantic_digest()
        .map_err(NeuronRuntimeV2Error::from)?;
    let request_digest = decision_cell_request_digest_v1(&invocation.request)?;
    Ok(Digest32::of_parts(&[
        b"hepta.neuron.decision-cell-input.v2",
        tick_digest.as_array(),
        request_digest.as_array(),
    ]))
}

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    /// Inspect a typed operation by the same complete identity used at dispatch.
    /// Inspection never calls the model or retries an unknown execution.
    pub fn query_decision_cell_operation(
        &mut self,
        invocation: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
    ) -> Result<crate::NeuronOperationStatusV2, DecisionCellRuntimeV2Error> {
        let (config, body, body_digest) = self.decision_cell_context();
        invocation.validate(config, body, body_digest, input)?;
        let digest = decision_cell_input_digest_v2(invocation, input)?;
        self.query_operation(&input.tick_id, digest)
            .map_err(DecisionCellRuntimeV2Error::Runtime)
    }
}

pub fn decode_decision_cell_commit_v2(
    invocation: &DecisionCellInvocationV2,
    commit: &NeuronRuntimeCommitV2,
) -> Result<Option<DecisionCellReceiptV1>, DecisionCellRuntimeV2Error> {
    let Some(extension) = &commit.receipt_extension else {
        return Ok(None);
    };
    if extension.schema_id.as_str() != RECEIPT_SCHEMA_ID || extension.schema_version != 1 {
        return Err(DecisionCellRuntimeV2Error::Binding("receipt schema"));
    }
    decode_decision_cell_receipt_v1(&invocation.request, &extension.payload)
        .map(Some)
        .map_err(DecisionCellRuntimeV2Error::Contract)
}
