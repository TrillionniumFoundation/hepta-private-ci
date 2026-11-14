//! Explicit host configuration and closed local-process execution receipts.

use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub(crate) const ENCODER: &[u8] = b"hepta.memory-cell.query-utf8-q16-padded512.v1";
pub(crate) const HEAD: &[u8] = b"hepta.memory-cell.hidden-tanh-and-next-token-top-probabilities.v1";
pub(crate) const SYSTEM: &str = "Answer using stored memory in the specified scope. Return only the value. If unknown, say 'unknown'. Do not cite sources.";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeMemoryPinsV1 {
    pub manifest_sha256: String,
    pub base_identity: String,
    pub adapter_sha256: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    pub worker_sha256: String,
    pub launcher_sha256: String,
}

/// Registered by the host, never taken from a read query. This profile invokes
/// one fixed CPU adapter whose entire training ancestry is one admitted source.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeMemoryModelConfigV1 {
    pub python: PathBuf,
    pub repo: PathBuf,
    pub model: PathBuf,
    pub checkpoint: PathBuf,
    pub receipt_directory: PathBuf,
    pub scope: String,
    pub model_id: String,
    pub config_id: String,
    pub generation: u64,
    pub rank: u32,
    pub seed: u32,
    pub output_width: usize,
    pub timeout_millis: u64,
    pub pins: NativeMemoryPinsV1,
}

impl NativeMemoryModelConfigV1 {
    pub(crate) fn validate(&self) -> Result<(), String> {
        for path in [
            &self.python,
            &self.repo,
            &self.model,
            &self.checkpoint,
            &self.receipt_directory,
        ] {
            if !path.is_absolute() {
                return Err("absolute registered backend paths required".to_string());
            }
        }
        StableId::new(self.model_id.clone()).map_err(|e| e.to_string())?;
        StableId::new(self.config_id.clone()).map_err(|e| e.to_string())?;
        Generation::new(self.generation).map_err(|e| e.to_string())?;
        if !(1..=32).contains(&self.output_width)
            || !(1..=120_000).contains(&self.timeout_millis)
            || ![2, 4, 8].contains(&self.rank)
            || self.seed >= (1 << 31)
            || self.scope.is_empty()
            || self.scope.len() > 128
            || self.scope.chars().any(char::is_control)
            || self.scope.contains("<|")
        {
            return Err("bounded registered backend profile required".to_string());
        }
        for pin in [
            &self.pins.manifest_sha256,
            &self.pins.base_identity,
            &self.pins.adapter_sha256,
            &self.pins.weights_digest,
            &self.pins.tokenizer_digest,
            &self.pins.preprocessor_digest,
            &self.pins.quantization_digest,
            &self.pins.runtime_digest,
            &self.pins.device_digest,
            &self.pins.worker_sha256,
            &self.pins.launcher_sha256,
        ] {
            parse_digest(pin)?;
        }
        if self.pins.preprocessor_digest != Digest32::of_bytes(SYSTEM.as_bytes()).to_string()
            || self.pins.weights_digest
                != Digest32::of_parts(&[
                    self.pins.base_identity.as_bytes(),
                    self.pins.adapter_sha256.as_bytes(),
                ])
                .to_string()
            || self.pins.quantization_digest
                != Digest32::of_bytes(b"hepta.memory-cell.cpu-float32-unquantized.v1").to_string()
        {
            return Err("registered backend pin profile mismatch".to_string());
        }
        Ok(())
    }

    pub(crate) fn prompt(&self, question: &str) -> String {
        format!(
            "<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\nScope: {}\n{question}<|im_end|>\n<|im_start|>assistant\n",
            self.scope
        )
    }
}

pub(crate) fn parse_digest(value: &str) -> Result<Digest32, String> {
    let digest = Digest32::from_str(value).map_err(|e| e.to_string())?;
    if digest.is_zero() {
        return Err("empty digest".to_string());
    }
    Ok(digest)
}

pub(crate) fn query_features(question: &str) -> Result<Vec<i64>, String> {
    if question.is_empty() || question.len() > 512 {
        return Err("bounded UTF-8 query required".to_string());
    }
    let mut features = vec![0; 512];
    for (slot, byte) in features.iter_mut().zip(question.bytes()) {
        *slot = i64::from(byte) << 16;
    }
    Ok(features)
}

#[derive(Serialize)]
pub(crate) struct NativeNeuronRequestV1<'a> {
    request_id: &'a str,
    config_id: &'a str,
    generation: u64,
    model_id: &'a str,
    encoder_digest: String,
    head_digest: String,
    weights_digest: String,
    input_digest: String,
    feature_vector_q24: &'a [i64],
    expected_output_width: usize,
}

impl<'a> From<&'a NeuronModelRequestV1> for NativeNeuronRequestV1<'a> {
    fn from(r: &'a NeuronModelRequestV1) -> Self {
        Self {
            request_id: r.request_id.as_str(),
            config_id: r.config_id.as_str(),
            generation: r.generation.get(),
            model_id: r.model_id.as_str(),
            encoder_digest: r.encoder_digest.to_string(),
            head_digest: r.head_digest.to_string(),
            weights_digest: r.weights_digest.to_string(),
            input_digest: r.input_digest.to_string(),
            feature_vector_q24: &r.feature_vector_q24,
            expected_output_width: r.expected_output_width,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeMemoryExecutionV1 {
    pub schema: String,
    pub request_sha256: String,
    pub query_digest: String,
    pub source_binding_digest: String,
    pub pins: NativeMemoryPinsV1,
    pub question: String,
    pub prompt: String,
    pub prompt_token_ids: Vec<u32>,
    pub generated_token_ids: Vec<u32>,
    pub text: String,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub latency_micros: u64,
    pub resident_bytes: u64,
    pub process_peak_rss_bytes: u64,
    pub resident_measurement: String,
    pub feature_forward_calls: u32,
    pub decoder_queries: u32,
    pub adapter_enabled: bool,
    pub answer_postprocessed: bool,
    pub facts_received: bool,
    pub retrieval_received: bool,
    pub base_unchanged: bool,
    pub adapter_unchanged: bool,
}

#[derive(Debug, thiserror::Error)]
pub enum NativeMemoryError {
    #[error("native memory rejected: {0}")]
    Rejected(String),
    #[error(transparent)]
    Source(#[from] codex_hepta_memory::MemoryCellSourceError),
    #[error(transparent)]
    Model(#[from] codex_hepta_neuron::NeuronModelError),
}
