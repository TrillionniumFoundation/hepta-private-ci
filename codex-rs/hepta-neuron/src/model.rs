//! Frozen local model execution boundary for neuron runtime.
//!
//! The neuron crate verifies exact artifact/runtime/device bindings and the
//! numerical output returned by a host-supplied executor. It does not discover
//! models, open providers, mint execution authority, or treat a digest as proof
//! that model bytes were executed. Production hosts must authenticate the
//! executor and its receipt independently.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const MAX_APPROVED_FEATURES: usize = 512;
const MAX_RUNTIME_WIDTH: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenModelManifestV1 {
    pub model_id: StableId,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_digest: Digest32,
    pub license_sbom_digest: Digest32,
    pub runtime_digest: Digest32,
    pub device_digest: Digest32,
    pub input_width: usize,
    pub output_width: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenHeadRequestV1 {
    pub request_id: StableId,
    pub approved_input_digest: Digest32,
    pub approved_features_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenHeadOutputV1 {
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    /// Qualified detector score in `[0, 1]` Q24. Calibration policy decides
    /// whether the score is in-domain; the model boundary does not.
    pub ood_score_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalModelRuntimeReceiptV1 {
    pub request_id: StableId,
    pub manifest_digest: Digest32,
    pub input_digest: Digest32,
    pub output_digest: Digest32,
    pub runtime_digest: Digest32,
    pub device_digest: Digest32,
    pub execution_micros: u64,
    pub observed_memory_bytes: u64,
    pub terminal_observed: bool,
    pub succeeded: bool,
    pub authority: AuthorityPosture,
}

/// Host-owned frozen encoder/head execution port.
///
/// Implementations are expected to execute an already selected immutable model
/// and return a receipt produced at that execution boundary. The neuron crate
/// verifies the returned bindings but does not authenticate the implementation.
pub trait FrozenSignalHead {
    fn execute(
        &mut self,
        manifest: &FrozenModelManifestV1,
        request: &FrozenHeadRequestV1,
    ) -> Result<(FrozenHeadOutputV1, LocalModelRuntimeReceiptV1), ModelError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ModelError {
    InvalidManifest,
    InvalidRequest,
    InvalidOutput,
    ReceiptMismatch(&'static str),
    RuntimeNotTerminal,
    RuntimeFailed,
    AuthorityGranted,
    Driver(String),
    Arithmetic,
}

impl fmt::Display for ModelError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ModelError {}

impl FrozenModelManifestV1 {
    pub fn digest(&self) -> Result<Digest32, ModelError> {
        if self.input_width == 0
            || self.input_width > MAX_APPROVED_FEATURES
            || !(5..=MAX_RUNTIME_WIDTH).contains(&self.output_width)
        {
            return Err(ModelError::InvalidManifest);
        }
        if [
            self.encoder_digest,
            self.head_digest,
            self.weights_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
            self.quantization_digest,
            self.license_sbom_digest,
            self.runtime_digest,
            self.device_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
        {
            return Err(ModelError::InvalidManifest);
        }
        let mut bytes = b"hepta.neuron.frozen-model-manifest.v1".to_vec();
        push_id(&mut bytes, &self.model_id)?;
        for digest in [
            self.encoder_digest,
            self.head_digest,
            self.weights_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
            self.quantization_digest,
            self.license_sbom_digest,
            self.runtime_digest,
            self.device_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&u64_from_usize(self.input_width)?.to_be_bytes());
        bytes.extend_from_slice(&u64_from_usize(self.output_width)?.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl FrozenHeadRequestV1 {
    pub fn digest(&self, manifest: &FrozenModelManifestV1) -> Result<Digest32, ModelError> {
        if self.approved_input_digest.is_zero()
            || self.approved_features_q24.len() != manifest.input_width
            || self
                .approved_features_q24
                .iter()
                .any(|value| !(-H..=H).contains(value))
        {
            return Err(ModelError::InvalidRequest);
        }
        let mut bytes = b"hepta.neuron.frozen-head-request.v1".to_vec();
        push_id(&mut bytes, &self.request_id)?;
        bytes.extend_from_slice(self.approved_input_digest.as_array());
        bytes.extend_from_slice(manifest.digest()?.as_array());
        bytes.extend_from_slice(&u64_from_usize(self.approved_features_q24.len())?.to_be_bytes());
        for value in &self.approved_features_q24 {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl FrozenHeadOutputV1 {
    pub fn digest(&self, manifest: &FrozenModelManifestV1) -> Result<Digest32, ModelError> {
        if self.drive_q24.len() != manifest.output_width
            || self.prediction_q24.len() != manifest.output_width
            || self
                .drive_q24
                .iter()
                .chain(&self.prediction_q24)
                .any(|value| !(-H..=H).contains(value))
            || !(0..=Q).contains(&self.ood_score_q24)
        {
            return Err(ModelError::InvalidOutput);
        }
        let mut bytes = b"hepta.neuron.frozen-head-output.v1".to_vec();
        bytes.extend_from_slice(manifest.digest()?.as_array());
        bytes.extend_from_slice(&u64_from_usize(self.drive_q24.len())?.to_be_bytes());
        for value in self.drive_q24.iter().chain(&self.prediction_q24) {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&self.ood_score_q24.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub fn execute_verified_head<H: FrozenSignalHead>(
    executor: &mut H,
    manifest: &FrozenModelManifestV1,
    request: &FrozenHeadRequestV1,
) -> Result<(FrozenHeadOutputV1, LocalModelRuntimeReceiptV1), ModelError> {
    let manifest_digest = manifest.digest()?;
    let input_digest = request.digest(manifest)?;
    let (output, receipt) = executor.execute(manifest, request)?;
    let output_digest = output.digest(manifest)?;
    if receipt.request_id != request.request_id {
        return Err(ModelError::ReceiptMismatch("request"));
    }
    if receipt.manifest_digest != manifest_digest {
        return Err(ModelError::ReceiptMismatch("manifest"));
    }
    if receipt.input_digest != input_digest {
        return Err(ModelError::ReceiptMismatch("input"));
    }
    if receipt.output_digest != output_digest {
        return Err(ModelError::ReceiptMismatch("output"));
    }
    if receipt.runtime_digest != manifest.runtime_digest {
        return Err(ModelError::ReceiptMismatch("runtime"));
    }
    if receipt.device_digest != manifest.device_digest {
        return Err(ModelError::ReceiptMismatch("device"));
    }
    if !receipt.terminal_observed {
        return Err(ModelError::RuntimeNotTerminal);
    }
    if !receipt.succeeded || receipt.execution_micros == 0 {
        return Err(ModelError::RuntimeFailed);
    }
    if receipt.authority.grants_any() {
        return Err(ModelError::AuthorityGranted);
    }
    Ok((output, receipt))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ModelError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| ModelError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn u64_from_usize(value: usize) -> Result<u64, ModelError> {
    u64::try_from(value).map_err(|_| ModelError::Arithmetic)
}

#[cfg(test)]
#[path = "model_tests.rs"]
mod tests;
