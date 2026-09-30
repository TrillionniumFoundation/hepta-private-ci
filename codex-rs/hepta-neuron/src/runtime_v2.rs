//! Product Neuron owner over the unified V2 generation store.
//!
//! This owner has one durable local commit point: `HPTNGS02`. The operation
//! key, replayable checkpoint transition, exact full receipt, terminal
//! disposition and witness-outbox target are appended and synced together.
//! `HPTNGI02` is a bounded discovery index only; every indexed item is checked
//! against the authoritative generation-store record on recovery.

use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AnchorWitnessStore;
use crate::CalibrationExpiryPolicyV1;
use crate::CalibrationWindowDecisionV1;
use crate::DegradationReasonV1;
use crate::FileNeuronGenerationStoreV2;
use crate::FileNeuronRuntimeIndexV2;
use crate::GenerationStoreError;
use crate::InferenceControlModelPort;
use crate::JournalAnchor;
use crate::JournalScope;
use crate::ModelExecutionObservationV1;
use crate::ModelSemanticIdentityV2;
use crate::NeuronAdmissionError;
use crate::NeuronAdmissionGuard;
use crate::NeuronBodyBundleIdentityV1;
use crate::NeuronCommitDispositionV1;
use crate::NeuronGenerationAdmissionV2;
use crate::NeuronGenerationCommitResultV2;
use crate::NeuronGenerationCommitV2;
use crate::NeuronGenerationRecordV2;
use crate::NeuronGenerationStoreContextV2;
use crate::NeuronInferenceControlPort;
use crate::NeuronModelError;
use crate::NeuronModelOutputV1;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::NeuronOperationKeyV2;
use crate::NeuronReceiptExtensionErrorV2;
use crate::NeuronReceiptExtensionV2;
use crate::NeuronResourceReceiptV1;
use crate::NeuronRuntimeConfigV1;
use crate::NeuronRuntimeError;
use crate::NeuronRuntimeIndexAdmissionV2;
use crate::NeuronRuntimeIndexContextV2;
use crate::NeuronRuntimeIndexError;
use crate::NeuronRuntimeIndexRecordV2;
use crate::NeuronRuntimeOutputV1;
use crate::NeuronSemanticV2Error;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickInputV1;
use crate::NeuronTickReceiptV1;
use crate::OperationStoreError;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseError;
use crate::SparseSignalReceipt;
use crate::SparseTick;
use crate::WitnessStoreError;
use crate::operation_codec::DecodedOperationEvent;
use crate::operation_codec::decode_event;
use crate::operation_codec::encode_prepared;
use crate::operation_store::PreparedNeuronOperationV1;
use crate::receipt_extension_v2::decode_full_receipt_v2;
use crate::receipt_extension_v2::encode_full_receipt_v2;
use crate::runtime_types::calibrate;
use crate::runtime_types::digest_model_binding;
use crate::runtime_types::subject_scope_digest;
use crate::runtime_types::validate_model_output;
use crate::sparse_tick;

#[path = "runtime_v2_lifecycle.rs"]
mod lifecycle;
pub use lifecycle::NeuronOperationStatusV2;

#[path = "runtime_v2_archive.rs"]
mod archive;
pub use archive::MAX_NEURON_GENERATION_ARCHIVE_BYTES_V1;
pub use archive::NeuronGenerationArchiveV1;

/// Marker for an inference-control owner that durably reserves an operation
/// before physical dispatch and reconciles dispatched operations without blind
/// re-execution. There is intentionally no blanket implementation.
pub trait DurableNeuronInferenceControlPort: NeuronInferenceControlPort {
    /// Execute all typed heads and transition tensors under this same durable
    /// inference owner. Unsupported implementations reject before physical work;
    /// they must never route a typed request through the untyped feature path.
    fn execute_decision_cell(
        &mut self,
        _request: &codex_hepta_infer_core::DecisionCellRequestV1,
    ) -> Result<crate::DecisionCellModelExecutionV2, crate::DecisionCellModelFailureV2> {
        Err(crate::DecisionCellModelFailureV2::Rejected)
    }

    /// Observe the original typed operation without inference or result-use
    /// authority. Missing typed capability/history is not a no-dispatch proof.
    fn reconcile_decision_cell(
        &mut self,
        _request: &codex_hepta_infer_core::DecisionCellRequestV1,
    ) -> Result<crate::DecisionCellModelResolutionV2, crate::DecisionCellModelFailureV2> {
        Ok(crate::DecisionCellModelResolutionV2::Unknown)
    }

    /// Query the exact operation without starting physical work. `NotStarted`
    /// requires an authoritative, current no-dispatch observation under the
    /// same durable owner. Missing history is not proof of non-execution.
    fn reconcile_feature(
        &mut self,
        _request: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    ) -> Result<DurableNeuronFeatureResolutionV2, NeuronModelError> {
        Ok(DurableNeuronFeatureResolutionV2::Unknown)
    }
}

/// Marker for the model port accepted by the V2 product runtime. Qualification
/// stubs may implement it in tests, but ordinary `NeuronModelPort` values cannot
/// accidentally enter the product path.
pub trait DurableNeuronModelPort: NeuronModelPort {
    /// Query, never blindly redispatch, an operation whose local dispatch fence
    /// is durable. `NotStarted` permits resuming the *same* operation only while
    /// its exclusive durable owner still fences competing dispatch.
    fn reconcile(
        &mut self,
        _request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        Ok(NeuronModelResolutionV2::Unknown)
    }

    /// Optional typed application receipt produced by the same exact model
    /// observation. The runtime validates and durably attaches it to the unified
    /// V2 commit; it grants no effect or model-selection authority.
    fn receipt_extension(
        &mut self,
        _request: &NeuronModelRequestV1,
        _model_output: &NeuronModelOutputV1,
        _runtime_output: &NeuronRuntimeOutputV1,
    ) -> Result<Option<NeuronReceiptExtensionV2>, NeuronModelError> {
        Ok(None)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableNeuronFeatureResolutionV2 {
    NotStarted,
    Observed(Box<codex_hepta_infer_core::NeuronFeatureReceiptV1>),
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronModelResolutionV2 {
    NotStarted,
    Observed(Box<NeuronModelOutputV1>),
    Unknown,
}

pub struct DurableInferenceControlModelPort<'a, P: DurableNeuronInferenceControlPort> {
    pub(crate) control: &'a mut P,
}

impl<'a, P: DurableNeuronInferenceControlPort> DurableInferenceControlModelPort<'a, P> {
    pub fn new(control: &'a mut P) -> Self {
        Self { control }
    }
}

impl<P: DurableNeuronInferenceControlPort> NeuronModelPort
    for DurableInferenceControlModelPort<'_, P>
{
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        InferenceControlModelPort::new(self.control).execute(request)
    }
}

impl<P: DurableNeuronInferenceControlPort> DurableNeuronModelPort
    for DurableInferenceControlModelPort<'_, P>
{
    fn reconcile(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        let request = crate::inference_control::feature_request(request);
        match self.control.reconcile_feature(&request)? {
            DurableNeuronFeatureResolutionV2::NotStarted => Ok(NeuronModelResolutionV2::NotStarted),
            DurableNeuronFeatureResolutionV2::Observed(receipt) => {
                crate::inference_control::model_output(&request, *receipt)
                    .map(Box::new)
                    .map(NeuronModelResolutionV2::Observed)
            }
            DurableNeuronFeatureResolutionV2::Unknown => Ok(NeuronModelResolutionV2::Unknown),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronRuntimeCommitV2 {
    pub key: NeuronOperationKeyV2,
    pub expected_anchor: Option<JournalAnchor>,
    pub next_anchor: JournalAnchor,
    pub operation_digest: Digest32,
    pub model_semantic_digest: Digest32,
    pub model_observation_digest: Digest32,
    pub disposition: NeuronCommitDispositionV1,
    pub receipt_extension: Option<NeuronReceiptExtensionV2>,
    pub output: NeuronRuntimeOutputV1,
}

#[derive(Debug)]
pub enum NeuronRuntimeV2Error {
    Admission(NeuronAdmissionError),
    Configuration(NeuronRuntimeError),
    Store(GenerationStoreError),
    Index(NeuronRuntimeIndexError),
    Witness(WitnessStoreError),
    Model(NeuronModelError),
    Semantic(NeuronSemanticV2Error),
    Codec(OperationStoreError),
    ReceiptExtension(NeuronReceiptExtensionErrorV2),
    Mechanism(SparseError),
    ContextMismatch,
    CheckpointMismatch,
    OperationConflict,
    RecoveryMismatch,
    PendingOperation,
    Arithmetic,
    TerminalFailure(crate::NeuronOperationFailureV2),
}

impl fmt::Display for NeuronRuntimeV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronRuntimeV2Error {}

impl From<NeuronRuntimeError> for NeuronRuntimeV2Error {
    fn from(value: NeuronRuntimeError) -> Self {
        Self::Configuration(value)
    }
}

impl From<GenerationStoreError> for NeuronRuntimeV2Error {
    fn from(value: GenerationStoreError) -> Self {
        Self::Store(value)
    }
}

impl From<NeuronRuntimeIndexError> for NeuronRuntimeV2Error {
    fn from(value: NeuronRuntimeIndexError) -> Self {
        Self::Index(value)
    }
}

impl From<WitnessStoreError> for NeuronRuntimeV2Error {
    fn from(value: WitnessStoreError) -> Self {
        Self::Witness(value)
    }
}

impl From<NeuronModelError> for NeuronRuntimeV2Error {
    fn from(value: NeuronModelError) -> Self {
        Self::Model(value)
    }
}

impl From<NeuronSemanticV2Error> for NeuronRuntimeV2Error {
    fn from(value: NeuronSemanticV2Error) -> Self {
        Self::Semantic(value)
    }
}

impl From<OperationStoreError> for NeuronRuntimeV2Error {
    fn from(value: OperationStoreError) -> Self {
        Self::Codec(value)
    }
}

impl From<NeuronReceiptExtensionErrorV2> for NeuronRuntimeV2Error {
    fn from(value: NeuronReceiptExtensionErrorV2) -> Self {
        Self::ReceiptExtension(value)
    }
}

impl From<SparseError> for NeuronRuntimeV2Error {
    fn from(value: SparseError) -> Self {
        Self::Mechanism(value)
    }
}

pub struct NeuronRuntimeV2<W: AnchorWitnessStore> {
    config: NeuronRuntimeConfigV1,
    native: SparseConfig,
    body_bundle: NeuronBodyBundleIdentityV1,
    body_bundle_digest: Digest32,
    store_context: NeuronGenerationStoreContextV2,
    store: FileNeuronGenerationStoreV2,
    index: FileNeuronRuntimeIndexV2,
    witness: W,
    checkpoint: Option<SparseCheckpoint>,
    last_measurement: Option<crate::NeuronRuntimeMeasurementV2>,
    recovery_micros: Option<u64>,
}

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    #[allow(clippy::too_many_arguments)]
    pub fn bootstrap(
        generation_store_path: &Path,
        runtime_index_path: &Path,
        native: SparseConfig,
        scope: JournalScope,
        config: NeuronRuntimeConfigV1,
        body_bundle: NeuronBodyBundleIdentityV1,
        store_context: NeuronGenerationStoreContextV2,
        index_context: NeuronRuntimeIndexContextV2,
        witness: W,
    ) -> Result<Self, NeuronRuntimeV2Error> {
        let body_bundle_digest = validate_contexts(
            &native,
            scope,
            &config,
            &body_bundle,
            &store_context,
            &index_context,
        )?;
        if witness.current()?.is_some() {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        let store =
            FileNeuronGenerationStoreV2::create(generation_store_path, store_context.clone())?;
        let index = FileNeuronRuntimeIndexV2::create(runtime_index_path, index_context)?;
        Ok(Self {
            config,
            native,
            body_bundle,
            body_bundle_digest,
            store_context,
            store,
            index,
            witness,
            checkpoint: None,
            last_measurement: None,
            recovery_micros: None,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn recover(
        generation_store_path: &Path,
        runtime_index_path: &Path,
        native: SparseConfig,
        scope: JournalScope,
        config: NeuronRuntimeConfigV1,
        body_bundle: NeuronBodyBundleIdentityV1,
        store_context: NeuronGenerationStoreContextV2,
        index_context: NeuronRuntimeIndexContextV2,
        witness: W,
    ) -> Result<Self, NeuronRuntimeV2Error> {
        let recovery_started = Instant::now();
        let body_bundle_digest = validate_contexts(
            &native,
            scope,
            &config,
            &body_bundle,
            &store_context,
            &index_context,
        )?;
        let store = FileNeuronGenerationStoreV2::open_existing(
            generation_store_path,
            store_context.clone(),
        )?;
        let index = FileNeuronRuntimeIndexV2::open_existing(runtime_index_path, index_context)?;
        let mut runtime = Self {
            config,
            native,
            body_bundle,
            body_bundle_digest,
            store_context,
            store,
            index,
            witness,
            checkpoint: None,
            last_measurement: None,
            recovery_micros: None,
        };
        runtime.replay_index()?;
        runtime.reconcile_witnesses()?;
        runtime.validate_frontiers()?;
        runtime.recovery_micros =
            Some(u64::try_from(recovery_started.elapsed().as_micros()).unwrap_or(u64::MAX));
        Ok(runtime)
    }

    pub fn configuration(&self) -> &NeuronRuntimeConfigV1 {
        &self.config
    }

    pub fn configuration_digest(&self) -> Result<Digest32, NeuronRuntimeV2Error> {
        Ok(self.config.semantic_digest()?)
    }

    pub fn body_bundle(&self) -> &NeuronBodyBundleIdentityV1 {
        &self.body_bundle
    }

    pub fn body_bundle_digest(&self) -> Digest32 {
        self.body_bundle_digest
    }

    pub fn current_anchor(&self) -> Result<Option<JournalAnchor>, NeuronRuntimeV2Error> {
        Ok(self.store.current_anchor()?)
    }

    pub fn pending_witness_count(&self) -> Result<usize, NeuronRuntimeV2Error> {
        Ok(self.store.pending_witness_count()?)
    }

    pub fn reconcile(&mut self) -> Result<(), NeuronRuntimeV2Error> {
        self.finish_pending_index_commit()?;
        self.reconcile_witnesses()?;
        self.validate_frontiers()
    }

    pub(crate) fn decision_cell_context(
        &self,
    ) -> (
        &NeuronRuntimeConfigV1,
        &NeuronBodyBundleIdentityV1,
        Digest32,
    ) {
        (&self.config, &self.body_bundle, self.body_bundle_digest)
    }

    fn require_expected_checkpoint(
        &self,
        input: &NeuronTickInputV1,
        expected_anchor: Option<JournalAnchor>,
    ) -> Result<(), NeuronRuntimeV2Error> {
        if input.checkpoint_digest
            != expected_anchor.map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
        {
            return Err(NeuronRuntimeV2Error::CheckpointMismatch);
        }
        Ok(())
    }

    fn model_request(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronModelRequestV1, NeuronRuntimeV2Error> {
        let input_digest = input.semantic_digest()?;
        if input.feature_vector_q24.len() != self.config.input_feature_dimension {
            return Err(NeuronRuntimeV2Error::Configuration(
                NeuronRuntimeError::InvalidInput,
            ));
        }
        Ok(NeuronModelRequestV1 {
            request_id: input.tick_id.clone(),
            config_id: self.config.config_id.clone(),
            generation: self.config.generation,
            model_id: self.config.model_id.clone(),
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            weights_digest: self.config.weights_digest,
            input_digest,
            feature_vector_q24: input.feature_vector_q24.clone(),
            expected_output_width: self.config.state_width,
        })
    }

    fn preflight_new_tick(&self, input: &NeuronTickInputV1) -> Result<(), NeuronRuntimeV2Error> {
        if subject_scope_digest(&input.subject_id)? != self.store_context.scope.scope_digest
            || input.objective_digest != self.store_context.scope.objective_digest
        {
            return Err(NeuronRuntimeV2Error::ContextMismatch);
        }
        if let Some(checkpoint) = &self.checkpoint
            && input.monotonic_time_micros <= checkpoint.monotonic_micros()
        {
            return Err(NeuronRuntimeV2Error::Mechanism(SparseError::Clock));
        }
        let expected_sequence = self
            .checkpoint
            .as_ref()
            .map_or(1, |checkpoint| checkpoint.sequence().saturating_add(1));
        if input.logical_sequence != expected_sequence {
            return Err(NeuronRuntimeV2Error::Mechanism(SparseError::Sequence));
        }
        let decision = CalibrationExpiryPolicyV1::RejectBeforeMutation.decide(
            input.logical_sequence,
            self.config.calibration.valid_from_sequence,
            self.config.calibration.expires_after_sequence,
        )?;
        if decision == CalibrationWindowDecisionV1::RejectNoUpdate {
            return Err(NeuronRuntimeV2Error::Configuration(
                NeuronRuntimeError::CalibrationExpired,
            ));
        }
        let checkpoint_bytes = estimated_checkpoint_bytes(self.config.state_width)?;
        let logical_transition_bytes = logical_transition_bytes(self.config.state_width)?;
        if checkpoint_bytes > self.config.resource_envelope.checkpoint_bytes
            || write_amplification(logical_transition_bytes, checkpoint_bytes)?
                > self.config.resource_envelope.write_amplification_ppm
        {
            return Err(NeuronRuntimeV2Error::Configuration(
                NeuronRuntimeError::InvalidConfig,
            ));
        }
        Ok(())
    }

    fn build_output(
        &self,
        tick_id: &StableId,
        model_output: &NeuronModelOutputV1,
        checkpoint: &SparseCheckpoint,
        sparse_receipt: &SparseSignalReceipt,
        started: Instant,
    ) -> Result<(NeuronRuntimeOutputV1, NeuronCommitDispositionV1), NeuronRuntimeV2Error> {
        let (confidence_ppm, ood_ppm, calibration_abstain) = calibrate(
            &self.config.calibration,
            sparse_receipt,
            checkpoint.sequence(),
        )?;
        let execution_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let checkpoint_bytes = checkpoint.bounded_encoded_bytes() as u64;
        let journal_bytes_written = logical_transition_bytes(self.config.state_width)?;
        let write_amplification_ppm = write_amplification(journal_bytes_written, checkpoint_bytes)?;
        let resource_receipt = NeuronResourceReceiptV1 {
            execution_micros,
            transient_allocation_bytes: model_output.transient_allocation_bytes,
            checkpoint_bytes,
            journal_bytes_written,
            write_amplification_ppm,
            saturation_count: sparse_receipt.projection_count,
            queue_age_micros: model_output.queue_age_micros,
        };
        let mut abstain_reasons = Vec::new();
        let profile = &self.config.calibration;
        for (condition, reason) in [
            (
                confidence_ppm < profile.minimum_confidence_ppm,
                crate::AbstainReasonV1::LowConfidence,
            ),
            (
                ood_ppm > profile.maximum_ood_ppm,
                crate::AbstainReasonV1::OutOfDomain,
            ),
            (
                sparse_receipt.active_fraction_ppm < profile.minimum_active_ppm,
                crate::AbstainReasonV1::SparseCollapse,
            ),
            (
                sparse_receipt.active_fraction_ppm > profile.maximum_active_ppm,
                crate::AbstainReasonV1::DenseCollapse,
            ),
            (
                sparse_receipt.projection_count > profile.maximum_projection_count,
                crate::AbstainReasonV1::ProjectionLimit,
            ),
        ] {
            if condition {
                abstain_reasons.push(reason);
            }
        }
        if calibration_abstain && abstain_reasons.is_empty() {
            abstain_reasons.push(crate::AbstainReasonV1::HostPolicy);
        }
        let envelope = &self.config.resource_envelope;
        let mut degradation = Vec::new();
        for (condition, reason) in [
            (
                execution_micros > envelope.p99_latency_micros,
                DegradationReasonV1::LatencyEnvelope,
            ),
            (
                model_output.transient_allocation_bytes > envelope.transient_allocation_bytes,
                DegradationReasonV1::AllocationEnvelope,
            ),
            (
                checkpoint_bytes > envelope.checkpoint_bytes,
                DegradationReasonV1::CheckpointEnvelope,
            ),
            (
                write_amplification_ppm > envelope.write_amplification_ppm,
                DegradationReasonV1::WriteAmplificationEnvelope,
            ),
        ] {
            if condition {
                degradation.push(reason);
            }
        }
        let disposition = if !degradation.is_empty() {
            NeuronCommitDispositionV1::degraded(degradation, abstain_reasons.clone())?
        } else if !abstain_reasons.is_empty() {
            NeuronCommitDispositionV1::abstained(abstain_reasons)?
        } else {
            NeuronCommitDispositionV1::CommittedReady
        };
        let abstain = !matches!(disposition, NeuronCommitDispositionV1::CommittedReady);
        let active_indices = checkpoint
            .activation_q24()
            .iter()
            .enumerate()
            .filter(|(_, value)| **value > 0)
            .map(|(index, _)| u32::try_from(index).map_err(|_| NeuronRuntimeV2Error::Arithmetic))
            .collect::<Result<Vec<_>, _>>()?;
        let tick = NeuronTickReceiptV1 {
            tick_id: tick_id.clone(),
            checkpoint_before: sparse_receipt.checkpoint_before,
            checkpoint_after: sparse_receipt.checkpoint_after,
            activation_digest: checkpoint.activation_digest(),
            active_indices,
            sparsity_ppm: sparse_receipt.active_fraction_ppm,
            threshold_digest: checkpoint.threshold_digest(),
            eligibility_digest: checkpoint.eligibility_digest(),
            prediction_error_q24: sparse_receipt.prediction_error_q24,
            confidence_ppm,
            ood_ppm,
            abstain,
            resource_receipt,
        };
        let signal = NeuronSignalReceiptV1 {
            signal_set_id: tick_id.clone(),
            model_runtime_digest: digest_model_binding(model_output)?,
            temporal_state_digest: checkpoint.temporal_state_digest(),
            signals_q24: sparse_receipt.activation_q24.clone(),
            activation_sparsity_ppm: sparse_receipt.active_fraction_ppm,
            ood_ppm,
            abstain,
            authority: AuthorityPosture::DENY_ALL,
        };
        Ok((
            NeuronRuntimeOutputV1 {
                tick,
                signal,
                model_runtime: model_output.runtime_receipt.clone(),
            },
            disposition,
        ))
    }

    fn replay_index(&mut self) -> Result<(), NeuronRuntimeV2Error> {
        let records = self.index.records()?;
        let mut checkpoint = None;
        for indexed in records {
            let stored = self
                .store
                .find_operation(&indexed.key)?
                .ok_or(NeuronRuntimeV2Error::RecoveryMismatch)?;
            validate_index_record(&indexed, &stored)?;
            checkpoint = Some(self.replay_record(checkpoint.as_ref(), &stored)?);
        }
        self.checkpoint = checkpoint;
        self.finish_pending_index_commit()?;
        self.validate_frontiers()
    }

    fn finish_pending_index_commit(&mut self) -> Result<(), NeuronRuntimeV2Error> {
        let Some(pending) = self.index.pending()? else {
            return Ok(());
        };
        let Some(record) = self.store.find_operation(&pending.key)? else {
            return Ok(());
        };
        if record.expected_anchor != pending.expected_anchor {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        let checkpoint = self.replay_record(self.checkpoint.as_ref(), &record)?;
        self.index
            .complete(&pending.key, record.next_anchor, record.operation_digest)?;
        self.checkpoint = Some(checkpoint);
        Ok(())
    }

    fn replay_record(
        &self,
        previous: Option<&SparseCheckpoint>,
        record: &NeuronGenerationRecordV2,
    ) -> Result<SparseCheckpoint, NeuronRuntimeV2Error> {
        let prepared = decode_prepared(&record.checkpoint_bytes)?;
        validate_prepared_against_record(&prepared, record)?;
        decode_full_receipt_v2(&record.checkpoint_bytes, &record.full_receipt_bytes)?;
        if prepared.sparse_tick.body_digest != self.body_bundle_digest {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        let (checkpoint, sparse_receipt) =
            sparse_tick(&self.native, &prepared.sparse_tick, previous)?;
        if checkpoint.digest() != record.next_anchor.checkpoint_digest
            || sparse_receipt.checkpoint_after != record.next_anchor.checkpoint_digest
            || prepared.output.tick.checkpoint_after != checkpoint.digest()
            || prepared.output.tick.checkpoint_before
                != record
                    .expected_anchor
                    .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
            || prepared.output.tick.activation_digest != checkpoint.activation_digest()
            || prepared.output.tick.threshold_digest != checkpoint.threshold_digest()
            || prepared.output.tick.eligibility_digest != checkpoint.eligibility_digest()
            || prepared.output.signal.temporal_state_digest != checkpoint.temporal_state_digest()
            || prepared.output.signal.signals_q24 != sparse_receipt.activation_q24
            || prepared.output.signal.authority.grants_any()
        {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        let (semantic, observation) =
            self.model_identities(&prepared.output, prepared.sparse_tick.monotonic_micros)?;
        if semantic != record.model_semantic_digest
            || observation != record.model_observation_digest
        {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        validate_disposition(&self.config, &prepared.output, &record.disposition)?;
        Ok(checkpoint)
    }

    fn commit_from_record(
        &self,
        record: &NeuronGenerationRecordV2,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        let prepared = decode_prepared(&record.checkpoint_bytes)?;
        validate_prepared_against_record(&prepared, record)?;
        let receipt_extension =
            decode_full_receipt_v2(&record.checkpoint_bytes, &record.full_receipt_bytes)?;
        let (semantic, observation) =
            self.model_identities(&prepared.output, prepared.sparse_tick.monotonic_micros)?;
        if semantic != record.model_semantic_digest
            || observation != record.model_observation_digest
        {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        validate_disposition(&self.config, &prepared.output, &record.disposition)?;
        Ok(NeuronRuntimeCommitV2 {
            key: record.key.clone(),
            expected_anchor: record.expected_anchor,
            next_anchor: record.next_anchor,
            operation_digest: record.operation_digest,
            model_semantic_digest: record.model_semantic_digest,
            model_observation_digest: record.model_observation_digest,
            disposition: record.disposition.clone(),
            receipt_extension,
            output: prepared.output,
        })
    }

    fn model_identities(
        &self,
        output: &NeuronRuntimeOutputV1,
        observed_at_monotonic_micros: u64,
    ) -> Result<(Digest32, Digest32), NeuronRuntimeV2Error> {
        let runtime = &output.model_runtime;
        let artifact_use_digest = Digest32::of_parts(&[
            b"hepta.neuron.selected-artifact-use.v2",
            self.config.model_manifest_digest.as_array(),
            self.config.weights_digest.as_array(),
            self.config
                .calibration
                .calibration_artifact_digest
                .as_array(),
            self.config.calibration.ood_artifact_digest.as_array(),
            self.body_bundle_digest.as_array(),
        ]);
        let semantic = ModelSemanticIdentityV2 {
            model_id: runtime.model_id.clone(),
            model_manifest_digest: runtime.model_manifest_digest,
            weights_digest: runtime.weights_digest,
            tokenizer_digest: runtime.tokenizer_digest,
            preprocessor_digest: runtime.preprocessor_digest,
            quantization_id: runtime.quantization_id.clone(),
            quantization_digest: runtime.quantization_digest,
            backend_id: runtime.backend_id.clone(),
            runtime_digest: runtime.runtime_digest,
            device_identity_digest: runtime.device_identity_digest,
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            artifact_use_digest,
        }
        .semantic_digest()?;
        let observation = ModelExecutionObservationV1 {
            latency_micros: runtime.latency_micros,
            queue_age_micros: output.tick.resource_receipt.queue_age_micros,
            resident_bytes: runtime.resident_bytes,
            transient_allocation_bytes: output.tick.resource_receipt.transient_allocation_bytes,
            observed_at_monotonic_micros,
        }
        .observation_digest()?;
        Ok((semantic, observation))
    }

    fn reconcile_witnesses(&mut self) -> Result<(), NeuronRuntimeV2Error> {
        let maximum = self.store_context.max_pending_witness.saturating_add(1);
        for _ in 0..maximum {
            let Some(pending) = self.store.pending_witness_record()? else {
                let current = self.witness.current()?;
                if current != self.store.witnessed_anchor()? {
                    return Err(NeuronRuntimeV2Error::RecoveryMismatch);
                }
                return Ok(());
            };
            let key = pending.key.clone();
            let expected_anchor = pending.expected_anchor;
            let next_anchor = pending.next_anchor;
            let current = self.witness.current()?;
            if current == expected_anchor {
                if let Err(error) = self.witness.compare_and_swap(expected_anchor, next_anchor) {
                    match self.witness.current() {
                        Ok(Some(anchor)) if anchor == next_anchor => {}
                        _ => return Err(NeuronRuntimeV2Error::Witness(error)),
                    }
                }
            } else if current != Some(next_anchor) {
                return Err(NeuronRuntimeV2Error::RecoveryMismatch);
            }
            self.store.acknowledge_witness(&key, next_anchor)?;
        }
        Err(NeuronRuntimeV2Error::RecoveryMismatch)
    }

    fn validate_frontiers(&self) -> Result<(), NeuronRuntimeV2Error> {
        let checkpoint = self.current_checkpoint_anchor();
        if self.index.frontier()? != checkpoint || self.store.current_anchor()? != checkpoint {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        if self.index.pending()?.is_none()
            && self.store.pending_witness_count()? == 0
            && (self.store.witnessed_anchor()? != checkpoint
                || self.witness.current()? != checkpoint)
        {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        Ok(())
    }

    fn current_checkpoint_anchor(&self) -> Option<JournalAnchor> {
        self.checkpoint.as_ref().map(|checkpoint| JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        })
    }
}

#[allow(clippy::too_many_arguments)]
fn validate_contexts(
    native: &SparseConfig,
    scope: JournalScope,
    config: &NeuronRuntimeConfigV1,
    body_bundle: &NeuronBodyBundleIdentityV1,
    store_context: &NeuronGenerationStoreContextV2,
    index_context: &NeuronRuntimeIndexContextV2,
) -> Result<Digest32, NeuronRuntimeV2Error> {
    config.validate_native(native)?;
    let config_digest = config.semantic_digest()?;
    let body_bundle_digest = body_bundle.semantic_digest()?;
    if store_context.generation != config.generation
        || store_context.scope != scope
        || store_context.runtime_config_digest != config_digest
        || store_context.body_bundle_digest != body_bundle_digest
        || index_context.generation != store_context.generation
        || index_context.scope != scope
        || index_context.runtime_config_digest != config_digest
        || index_context.body_bundle_digest != body_bundle_digest
        || body_bundle.body_generation != config.generation
    {
        return Err(NeuronRuntimeV2Error::ContextMismatch);
    }
    Ok(body_bundle_digest)
}

fn decode_prepared(bytes: &[u8]) -> Result<PreparedNeuronOperationV1, NeuronRuntimeV2Error> {
    let value = match decode_event(bytes)? {
        DecodedOperationEvent::Prepared(value) => *value,
        DecodedOperationEvent::Completed(_) => {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
    };
    let rebuilt = PreparedNeuronOperationV1::new(
        value.input_digest,
        value.tick_id.clone(),
        value.expected_anchor,
        value.next_anchor,
        value.sparse_tick.clone(),
        value.output.clone(),
    )?;
    if rebuilt.operation_digest != value.operation_digest {
        return Err(NeuronRuntimeV2Error::RecoveryMismatch);
    }
    Ok(value)
}

fn validate_prepared_against_record(
    prepared: &PreparedNeuronOperationV1,
    record: &NeuronGenerationRecordV2,
) -> Result<(), NeuronRuntimeV2Error> {
    if prepared.tick_id != record.key.tick_id
        || prepared.input_digest != record.key.input_semantic_digest
        || prepared.expected_anchor != record.expected_anchor
        || prepared.next_anchor != record.next_anchor
        || prepared.output.tick.tick_id != record.key.tick_id
        || prepared.output.signal.signal_set_id != record.key.tick_id
    {
        return Err(NeuronRuntimeV2Error::RecoveryMismatch);
    }
    Ok(())
}

fn validate_index_record(
    indexed: &NeuronRuntimeIndexRecordV2,
    record: &NeuronGenerationRecordV2,
) -> Result<(), NeuronRuntimeV2Error> {
    if indexed.key != record.key
        || indexed.expected_anchor != record.expected_anchor
        || indexed.next_anchor != record.next_anchor
        || indexed.generation_operation_digest != record.operation_digest
    {
        return Err(NeuronRuntimeV2Error::RecoveryMismatch);
    }
    Ok(())
}

fn validate_disposition(
    config: &NeuronRuntimeConfigV1,
    output: &NeuronRuntimeOutputV1,
    disposition: &NeuronCommitDispositionV1,
) -> Result<(), NeuronRuntimeV2Error> {
    let resource = &output.tick.resource_receipt;
    let envelope = &config.resource_envelope;
    let degraded = resource.execution_micros > envelope.p99_latency_micros
        || resource.transient_allocation_bytes > envelope.transient_allocation_bytes
        || resource.checkpoint_bytes > envelope.checkpoint_bytes
        || resource.write_amplification_ppm > envelope.write_amplification_ppm;
    match disposition {
        NeuronCommitDispositionV1::CommittedReady if !output.tick.abstain && !degraded => Ok(()),
        NeuronCommitDispositionV1::CommittedAbstained { .. }
            if output.tick.abstain && !degraded =>
        {
            Ok(())
        }
        NeuronCommitDispositionV1::CommittedDegraded { .. } if output.tick.abstain && degraded => {
            Ok(())
        }
        _ => Err(NeuronRuntimeV2Error::RecoveryMismatch),
    }
}

fn estimated_checkpoint_bytes(width: usize) -> Result<u64, NeuronRuntimeV2Error> {
    let fixed = 6_usize
        .checked_mul(std::mem::size_of::<Digest32>())
        .and_then(|value| value.checked_add(7 * std::mem::size_of::<u64>()))
        .ok_or(NeuronRuntimeV2Error::Arithmetic)?;
    let vectors = width
        .checked_mul(5)
        .and_then(|value| value.checked_mul(std::mem::size_of::<i64>()))
        .ok_or(NeuronRuntimeV2Error::Arithmetic)?;
    u64::try_from(
        fixed
            .checked_add(vectors)
            .ok_or(NeuronRuntimeV2Error::Arithmetic)?,
    )
    .map_err(|_| NeuronRuntimeV2Error::Arithmetic)
}

fn logical_transition_bytes(width: usize) -> Result<u64, NeuronRuntimeV2Error> {
    u64::try_from(
        304_usize
            .checked_add(
                width
                    .checked_mul(16)
                    .ok_or(NeuronRuntimeV2Error::Arithmetic)?,
            )
            .ok_or(NeuronRuntimeV2Error::Arithmetic)?,
    )
    .map_err(|_| NeuronRuntimeV2Error::Arithmetic)
}

fn write_amplification(
    journal_bytes_written: u64,
    checkpoint_bytes: u64,
) -> Result<u32, NeuronRuntimeV2Error> {
    if checkpoint_bytes == 0 {
        return Err(NeuronRuntimeV2Error::Arithmetic);
    }
    let numerator = u128::from(journal_bytes_written)
        .checked_mul(1_000_000)
        .ok_or(NeuronRuntimeV2Error::Arithmetic)?;
    let denominator = u128::from(checkpoint_bytes);
    let rounded_up = numerator
        .checked_add(denominator.saturating_sub(1))
        .ok_or(NeuronRuntimeV2Error::Arithmetic)?
        / denominator;
    u32::try_from(rounded_up).map_err(|_| NeuronRuntimeV2Error::Arithmetic)
}

#[cfg(test)]
#[path = "runtime_v2_tests.rs"]
mod tests;
