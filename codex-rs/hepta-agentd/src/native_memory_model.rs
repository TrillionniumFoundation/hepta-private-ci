//! Actual CPU decoder implementation of the existing NeuronModelPort boundary.

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_memory::MemoryCellAdmissionV1;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_neuron::LocalModelRuntimeReceiptV1;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelOutputV1;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::canonical_model_output_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Serialize;

use crate::native_memory_process;
use crate::native_memory_types::*;
use crate::native_memory_tick_binding::NativeTickBindingV1;

pub(crate) struct NativeMemoryModelPort {
    writer: Arc<ProductionDurableWriter>,
    admission: Arc<MemoryCellAdmissionV1>,
    config: NativeMemoryModelConfigV1,
    handle: tokio::runtime::Handle,
    expected: NeuronModelRequestV1,
    tick_binding: Option<NativeTickBindingV1>,
    execution: Option<NativeMemoryExecutionV1>,
    attempted: bool,
    failure: Option<String>,
    dispatches: Arc<AtomicU64>,
    cancellation: tokio_util::sync::CancellationToken,
}

#[derive(Serialize)]
struct WorkerRequest<'a> {
    schema: &'static str,
    repo: &'a std::path::Path,
    model: &'a std::path::Path,
    checkpoint: &'a std::path::Path,
    scope: &'a str,
    source_root: &'a str,
    rank: u32,
    seed: u32,
    pins: &'a NativeMemoryPinsV1,
    question: &'a str,
    query_digest: String,
    source_binding_digest: String,
    neuron_request: NativeNeuronRequestV1<'a>,
    #[serde(skip_serializing_if = "Option::is_none")]
    tick_binding: Option<&'a NativeTickBindingV1>,
}

impl NativeMemoryModelPort {
    pub(crate) fn new(
        writer: Arc<ProductionDurableWriter>,
        admission: Arc<MemoryCellAdmissionV1>,
        config: NativeMemoryModelConfigV1,
        handle: tokio::runtime::Handle,
        dispatches: Arc<AtomicU64>,
        cancellation: tokio_util::sync::CancellationToken,
    ) -> Result<Self, NativeMemoryError> {
        config.validate().map_err(NativeMemoryError::Rejected)?;
        let query = admission.query();
        let question = query.key.question()?;
        let expected = NeuronModelRequestV1 {
            request_id: query.request_id.clone(),
            config_id: StableId::new(config.config_id.clone())
                .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?,
            generation: Generation::new(config.generation)
                .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?,
            model_id: StableId::new(config.model_id.clone())
                .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?,
            encoder_digest: Digest32::of_bytes(ENCODER),
            head_digest: Digest32::of_bytes(HEAD),
            weights_digest: parse_digest(&config.pins.weights_digest)
                .map_err(NativeMemoryError::Rejected)?,
            input_digest: admission.binding().binding_digest,
            feature_vector_q24: query_features(&question).map_err(NativeMemoryError::Rejected)?,
            expected_output_width: config.output_width,
        };
        Ok(Self {
            writer,
            admission,
            config,
            handle,
            expected,
            tick_binding: None,
            execution: None,
            attempted: false,
            failure: None,
            dispatches,
            cancellation,
        })
    }

    /// Preserve the registered model tuple and source admission while binding
    /// the full live tick. A source hash cannot stand in for objective or NDU.
    pub(crate) fn bind_tick(
        &mut self,
        input: &NeuronTickInputV1,
        request: &NeuronModelRequestV1,
    ) -> Result<(), NativeMemoryError> {
        let mut expected = self.expected.clone();
        expected.input_digest = input.semantic_digest()
            .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?;
        if self.attempted || self.tick_binding.is_some() || request != &expected
            || request.request_id != input.tick_id
            || request.feature_vector_q24 != input.feature_vector_q24 {
            return Err(NativeMemoryError::Rejected("tick differs from admitted native model tuple".to_string()));
        }
        self.tick_binding = Some(NativeTickBindingV1::new(input, self.admission.binding())?);
        self.expected = expected;
        Ok(())
    }

    pub(crate) fn request(&self) -> NeuronModelRequestV1 {
        self.expected.clone()
    }
    pub(crate) fn failure(&self) -> Option<&str> {
        self.failure.as_deref()
    }
    pub(crate) fn take_execution(&mut self) -> Result<NativeMemoryExecutionV1, NativeMemoryError> {
        self.execution
            .take()
            .ok_or_else(|| NativeMemoryError::Rejected("model never completed".to_string()))
    }
}

impl NativeMemoryModelPort {
    fn execute_checked(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, String> {
        let reject = |message: String| message;
        if request != &self.expected || self.attempted {
            return Err(reject(
                "neuron request differs from admitted query or was replayed".to_string(),
            ));
        }
        if self.cancellation.is_cancelled() {
            return Err("native owner is closed".to_string());
        }
        self.handle
            .block_on(self.writer.revalidate_memory_cell(&self.admission))
            .map_err(|e| reject(e.to_string()))?;
        let question = self
            .admission
            .query()
            .key
            .question()
            .map_err(|e| reject(e.to_string()))?;
        let wire = WorkerRequest {
            schema: if self.tick_binding.is_some() { "hepta.memory-cell.native-request.v2" } else { "hepta.memory-cell.native-request.v1" },
            repo: &self.config.repo,
            model: &self.config.model,
            checkpoint: &self.config.checkpoint,
            scope: &self.config.scope,
            source_root: self.admission.binding().source_content_sha256.as_str(),
            rank: self.config.rank,
            seed: self.config.seed,
            pins: &self.config.pins,
            question: &question,
            query_digest: self.admission.binding().query_digest.to_string(),
            source_binding_digest: self.admission.binding().binding_digest.to_string(),
            neuron_request: request.into(),
            tick_binding: self.tick_binding.as_ref(),
        };
        let input = serde_json::to_vec(&wire).map_err(|e| reject(e.to_string()))?;
        let request_digest = Digest32::of_bytes(&input).to_string();
        self.attempted = true;
        self.dispatches.fetch_add(1, Ordering::SeqCst);
        let output = native_memory_process::execute(&self.config, input, &self.cancellation)?;
        let execution: NativeMemoryExecutionV1 =
            serde_json::from_slice(&output).map_err(|e| reject(e.to_string()))?;
        verify_execution(&self.config, &self.admission, &request_digest, &execution)
            .map_err(reject)?;
        if self.cancellation.is_cancelled() {
            return Err("native owner closed during execution".to_string());
        }
        self.handle
            .block_on(self.writer.revalidate_memory_cell(&self.admission))
            .map_err(|e| e.to_string())?;
        let pins = &execution.pins;
        let receipt = LocalModelRuntimeReceiptV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: parse_digest(&pins.manifest_sha256)?,
            weights_digest: parse_digest(&pins.weights_digest)?,
            tokenizer_digest: parse_digest(&pins.tokenizer_digest)?,
            preprocessor_digest: parse_digest(&pins.preprocessor_digest)?,
            quantization_id: StableId::new("float32:none").map_err(|e| e.to_string())?,
            quantization_digest: parse_digest(&pins.quantization_digest)?,
            backend_id: StableId::new("memory-cell:python-cpu").map_err(|e| e.to_string())?,
            runtime_digest: parse_digest(&pins.runtime_digest)?,
            device_identity_digest: parse_digest(&pins.device_digest)?,
            latency_micros: execution.latency_micros,
            resident_bytes: execution.resident_bytes,
        };
        let output_digest = canonical_model_output_digest_v1(
            &execution.drive_q24,
            &execution.prediction_q24,
            &receipt,
        )
        .map_err(|e| e.to_string())?;
        let result = NeuronModelOutputV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            output_digest,
            drive_q24: execution.drive_q24.clone(),
            prediction_q24: execution.prediction_q24.clone(),
            // Whole-process peak RSS is a conservative measured upper bound,
            // not an invented model activation allocation measurement.
            queue_age_micros: 0,
            transient_allocation_bytes: execution.process_peak_rss_bytes,
            runtime_receipt: receipt,
        };
        self.execution = Some(execution);
        Ok(result)
    }
}

pub(crate) fn verify_execution(
    config: &NativeMemoryModelConfigV1,
    admission: &MemoryCellAdmissionV1,
    request_digest: &str,
    e: &NativeMemoryExecutionV1,
) -> Result<(), String> {
    let question = admission
        .query()
        .key
        .question()
        .map_err(|e| e.to_string())?;
    if e.schema != "hepta.memory-cell.native-execution.v1"
        || e.request_sha256 != request_digest
        || e.query_digest != admission.binding().query_digest.to_string()
        || e.source_binding_digest != admission.binding().binding_digest.to_string()
        || e.pins != config.pins
        || e.question != question
        || e.prompt != config.prompt(&question)
        || !(1..=192).contains(&e.prompt_token_ids.len())
        || !(1..=16).contains(&e.generated_token_ids.len())
        || e.prompt_token_ids
            .iter()
            .chain(&e.generated_token_ids)
            .any(|id| *id > 1_000_000)
        || e.text.len() > 1024
        || e.drive_q24.len() != config.output_width
        || e.prediction_q24.len() != config.output_width
        || e.drive_q24
            .iter()
            .any(|v| !(-(1 << 24)..=(1 << 24)).contains(v))
        || e.prediction_q24
            .iter()
            .any(|v| !(0..=(1 << 24)).contains(v))
        || e.latency_micros == 0
        || e.latency_micros > config.timeout_millis * 1000
        || e.resident_bytes == 0
        || e.resident_bytes > (2_u64 << 30)
        || e.process_peak_rss_bytes == 0
        || e.process_peak_rss_bytes > (4_u64 << 30)
        || e.resident_measurement != "model_parameter_bytes_excludes_allocator"
        || e.feature_forward_calls != 1
        || e.decoder_queries != 1
        || !e.adapter_enabled
        || e.answer_postprocessed
        || e.facts_received
        || e.retrieval_received
        || !e.base_unchanged
        || !e.adapter_unchanged
    {
        return Err(
            "actual execution receipt does not match admitted query and retained backend"
                .to_string(),
        );
    }
    Ok(())
}

impl NeuronModelPort for NativeMemoryModelPort {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.execute_checked(request).map_err(|error| {
            self.failure = Some(error);
            NeuronModelError::Rejected
        })
    }
}

#[cfg(test)]
#[path = "native_memory_model_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "native_memory_tick_binding_tests.rs"]
mod tick_binding_tests;
