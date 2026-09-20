//! Immutable selected local-model identity for one neuron runtime generation.
//!
//! A model ID or encoder digest is not enough to freeze execution. This manifest
//! binds the exact weights/head, tokenizer, preprocessor, quantization, backend,
//! device, runtime binary, SBOM, license and OOD detector tuple used by the owner
//! host. The tuple is immutable for one runtime generation.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::BoundModelExecutionV1;
use crate::NativeSparseProfileV1;
use crate::NeuronRuntimeConfigV1;
use crate::ProtocolError;
use crate::SparseConfig;
use crate::runtime_profile_digest;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedNeuronModelManifestV1 {
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_id: StableId,
    pub backend_id: StableId,
    pub device_identity_digest: Digest32,
    pub runtime_binary_digest: Digest32,
    pub sbom_digest: Digest32,
    pub license_digest: Digest32,
    pub ood_detector_digest: Digest32,
}

impl SelectedNeuronModelManifestV1 {
    pub fn digest(&self) -> Result<Digest32, ProtocolError> {
        self.validate_shape()?;
        let mut bytes = b"hepta.neuron.selected-model-manifest.v1".to_vec();
        for digest in [
            self.encoder_digest,
            self.head_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
            self.device_identity_digest,
            self.runtime_binary_digest,
            self.sbom_digest,
            self.license_digest,
            self.ood_detector_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.quantization_id);
        push_id(&mut bytes, &self.backend_id);
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn lineage_digests(&self) -> Result<Vec<Digest32>, ProtocolError> {
        let manifest_digest = self.digest()?;
        Ok(vec![
            manifest_digest,
            self.encoder_digest,
            self.head_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
            self.device_identity_digest,
            self.runtime_binary_digest,
            self.sbom_digest,
            self.license_digest,
            self.ood_detector_digest,
        ])
    }

    pub fn validate_for_config(
        &self,
        config: &NeuronRuntimeConfigV1,
    ) -> Result<(), ProtocolError> {
        self.validate_shape()?;
        if self.encoder_digest != config.encoder_digest {
            return Err(ProtocolError::InvalidModelExecution(
                "selected manifest encoder mismatch",
            ));
        }
        if self.head_digest != config.head_digest {
            return Err(ProtocolError::InvalidModelExecution(
                "selected manifest head mismatch",
            ));
        }
        Ok(())
    }

    pub fn validate_execution(
        &self,
        execution: &BoundModelExecutionV1,
    ) -> Result<(), ProtocolError> {
        self.validate_shape()?;
        if execution.runtime_receipt.weights_digest != self.encoder_digest
            || execution.head_digest != self.head_digest
            || execution.runtime_receipt.tokenizer_digest != self.tokenizer_digest
            || execution.runtime_receipt.preprocessor_digest != self.preprocessor_digest
            || execution.runtime_receipt.quantization_id != self.quantization_id
            || execution.runtime_receipt.backend_id != self.backend_id
            || execution.runtime_receipt.device_identity_digest != self.device_identity_digest
            || execution.runtime_binary_digest != self.runtime_binary_digest
            || execution.sbom_digest != self.sbom_digest
            || execution.license_digest != self.license_digest
            || execution.ood_detector_digest != self.ood_detector_digest
        {
            return Err(ProtocolError::InvalidModelExecution(
                "selected model manifest drift",
            ));
        }
        Ok(())
    }

    fn validate_shape(&self) -> Result<(), ProtocolError> {
        for (name, digest) in [
            ("selected encoder", self.encoder_digest),
            ("selected head", self.head_digest),
            ("selected tokenizer", self.tokenizer_digest),
            ("selected preprocessor", self.preprocessor_digest),
            ("selected device", self.device_identity_digest),
            ("selected runtime binary", self.runtime_binary_digest),
            ("selected sbom", self.sbom_digest),
            ("selected license", self.license_digest),
            ("selected ood detector", self.ood_detector_digest),
        ] {
            if digest.is_zero() {
                return Err(ProtocolError::EmptyDigest(name));
            }
        }
        Ok(())
    }
}

/// Full owner profile identity. Unlike the compatibility
/// `runtime_profile_digest`, this binds the entire selected model execution
/// tuple and therefore is suitable for persistent owner/witness context.
pub fn bound_runtime_profile_digest(
    config: &NeuronRuntimeConfigV1,
    native: &NativeSparseProfileV1,
    manifest: &SelectedNeuronModelManifestV1,
) -> Result<Digest32, ProtocolError> {
    manifest.validate_for_config(config)?;
    let compatibility_digest = runtime_profile_digest(config, native)?;
    let manifest_digest = manifest.digest()?;
    let mut bytes = b"hepta.neuron.bound-runtime-profile.v1".to_vec();
    bytes.extend_from_slice(compatibility_digest.as_array());
    bytes.extend_from_slice(manifest_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

/// Build the native sparse profile with the complete selected model manifest as
/// the model identity. This prevents a checkpoint from surviving a tokenizer,
/// runtime, device or OOD-detector substitution under equal encoder/head bytes.
pub fn bound_sparse_config(
    config: &NeuronRuntimeConfigV1,
    native: &NativeSparseProfileV1,
    manifest: &SelectedNeuronModelManifestV1,
) -> Result<SparseConfig, ProtocolError> {
    manifest.validate_for_config(config)?;
    let mut sparse = config.to_sparse_config(native)?;
    sparse.model_digest = manifest.digest()?;
    sparse
        .digest()
        .map_err(|_| ProtocolError::InvalidNativeProfile("bound sparse config"))?;
    Ok(sparse)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
