//! Model identity data shared by qualification-only composition and the legacy driver.
//!
//! This descriptor neither authenticates a model nor grants execution authority.
//! The experimental signed-grant boundary uses its own distinct manifest contract.

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelManifest {
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    /// Digest of the exact feature normalizer used before the shared Encoder
    /// snapshot. This is separate from preprocessing and is required by the
    /// V3 shared-feature admission contract.
    pub normalizer_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    pub maximum_tokens: u32,
}
