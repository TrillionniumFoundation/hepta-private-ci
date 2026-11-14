//! Stable extension seam for exact tokenization of the frozen provider request.
//!
//! Raw request bytes are borrowed only for the synchronous tokenizer call and
//! are never retained in the receipt or the turn-scoped state. The host is a
//! trusted capability installed by the embedding runtime; ordinary extensions
//! continue to see only digest material through `ModelProviderInvocationInput`.

use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;

use crate::ModelProviderPolicyError;
use crate::ModelProviderSha256Digest;

pub const MODEL_PROVIDER_EXACT_TOKENIZER_SCHEMA_VERSION: u32 = 1;
pub const MAX_MODEL_PROVIDER_TOKENIZER_VERSION_BYTES: usize = 256;
pub const MAX_MODEL_PROVIDER_TOKENIZATION_ATTEMPTS_PER_TURN: usize = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelProviderExactTokenizerDescriptor {
    provider_id: String,
    model: String,
    tokenizer_binary_sha256: ModelProviderSha256Digest,
    tokenizer_version: String,
    vocabulary_sha256: ModelProviderSha256Digest,
    normalization_policy_sha256: ModelProviderSha256Digest,
}

impl ModelProviderExactTokenizerDescriptor {
    pub fn new(
        provider_id: impl Into<String>,
        model: impl Into<String>,
        tokenizer_binary_sha256: ModelProviderSha256Digest,
        tokenizer_version: impl Into<String>,
        vocabulary_sha256: ModelProviderSha256Digest,
        normalization_policy_sha256: ModelProviderSha256Digest,
    ) -> Result<Self, ModelProviderPolicyError> {
        let value = Self {
            provider_id: provider_id.into(),
            model: model.into(),
            tokenizer_binary_sha256,
            tokenizer_version: tokenizer_version.into(),
            vocabulary_sha256,
            normalization_policy_sha256,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    pub fn model(&self) -> &str {
        &self.model
    }

    pub fn tokenizer_binary_sha256(&self) -> &ModelProviderSha256Digest {
        &self.tokenizer_binary_sha256
    }

    pub fn tokenizer_version(&self) -> &str {
        &self.tokenizer_version
    }

    pub fn vocabulary_sha256(&self) -> &ModelProviderSha256Digest {
        &self.vocabulary_sha256
    }

    pub fn normalization_policy_sha256(&self) -> &ModelProviderSha256Digest {
        &self.normalization_policy_sha256
    }

    pub fn validate(&self) -> Result<(), ModelProviderPolicyError> {
        if self.provider_id.is_empty()
            || self.provider_id.len() > 256
            || self.provider_id.as_bytes().contains(&0)
            || self.model.is_empty()
            || self.model.len() > 256
            || self.model.as_bytes().contains(&0)
            || self.tokenizer_version.is_empty()
            || self.tokenizer_version.len() > MAX_MODEL_PROVIDER_TOKENIZER_VERSION_BYTES
            || self.tokenizer_version.as_bytes().contains(&0)
        {
            return Err(ModelProviderPolicyError::new(
                "invalid_exact_tokenizer_descriptor",
                "provider, model, and tokenizer version must be bounded non-NUL strings",
            ));
        }
        Ok(())
    }
}

pub struct ModelProviderExactTokenizerRequest<'a> {
    pub schema_version: u32,
    pub attempt_id: &'a str,
    pub provider_id: &'a str,
    pub model: &'a str,
    pub wire_semantic_sha256: &'a ModelProviderSha256Digest,
    /// Exact canonical bytes whose SHA-256 is `wire_semantic_sha256`.
    /// Implementations must not retain or log this slice.
    pub canonical_final_request: &'a [u8],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelProviderExactTokenizationReceipt {
    schema_version: u32,
    attempt_id: String,
    tokenizer_capability_id: String,
    descriptor: ModelProviderExactTokenizerDescriptor,
    final_request_sha256: ModelProviderSha256Digest,
    wire_semantic_sha256: ModelProviderSha256Digest,
    final_request_bytes: u64,
    token_count: u64,
}

impl ModelProviderExactTokenizationReceipt {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        attempt_id: impl Into<String>,
        tokenizer_capability_id: impl Into<String>,
        descriptor: ModelProviderExactTokenizerDescriptor,
        final_request_sha256: ModelProviderSha256Digest,
        wire_semantic_sha256: ModelProviderSha256Digest,
        final_request_bytes: u64,
        token_count: u64,
    ) -> Result<Self, ModelProviderPolicyError> {
        let value = Self {
            schema_version: MODEL_PROVIDER_EXACT_TOKENIZER_SCHEMA_VERSION,
            attempt_id: attempt_id.into(),
            tokenizer_capability_id: tokenizer_capability_id.into(),
            descriptor,
            final_request_sha256,
            wire_semantic_sha256,
            final_request_bytes,
            token_count,
        };
        value.validate_shape()?;
        Ok(value)
    }

    pub const fn schema_version(&self) -> u32 {
        self.schema_version
    }

    pub fn attempt_id(&self) -> &str {
        &self.attempt_id
    }

    pub fn tokenizer_capability_id(&self) -> &str {
        &self.tokenizer_capability_id
    }

    pub const fn descriptor(&self) -> &ModelProviderExactTokenizerDescriptor {
        &self.descriptor
    }

    pub const fn final_request_sha256(&self) -> &ModelProviderSha256Digest {
        &self.final_request_sha256
    }

    pub const fn wire_semantic_sha256(&self) -> &ModelProviderSha256Digest {
        &self.wire_semantic_sha256
    }

    pub const fn final_request_bytes(&self) -> u64 {
        self.final_request_bytes
    }

    pub const fn token_count(&self) -> u64 {
        self.token_count
    }

    pub fn validate_for(
        &self,
        request: &ModelProviderExactTokenizerRequest<'_>,
        expected_capability_id: &str,
    ) -> Result<(), ModelProviderPolicyError> {
        self.validate_shape()?;
        if request.schema_version != MODEL_PROVIDER_EXACT_TOKENIZER_SCHEMA_VERSION
            || self.attempt_id != request.attempt_id
            || self.tokenizer_capability_id != expected_capability_id
            || self.descriptor.provider_id() != request.provider_id
            || self.descriptor.model() != request.model
            || &self.wire_semantic_sha256 != request.wire_semantic_sha256
            || self.final_request_sha256 != self.wire_semantic_sha256
            || self.final_request_bytes
                != u64::try_from(request.canonical_final_request.len()).unwrap_or(u64::MAX)
        {
            return Err(ModelProviderPolicyError::new(
                "exact_tokenizer_receipt_binding_mismatch",
                "exact tokenizer receipt does not bind the frozen provider attempt",
            ));
        }
        Ok(())
    }

    fn validate_shape(&self) -> Result<(), ModelProviderPolicyError> {
        self.descriptor.validate()?;
        if self.schema_version != MODEL_PROVIDER_EXACT_TOKENIZER_SCHEMA_VERSION
            || self.attempt_id.is_empty()
            || self.attempt_id.len() > 256
            || self.attempt_id.as_bytes().contains(&0)
            || self.tokenizer_capability_id.is_empty()
            || self.tokenizer_capability_id.len() > 256
            || self.tokenizer_capability_id.as_bytes().contains(&0)
            || self.final_request_bytes == 0
            || self.token_count == 0
        {
            return Err(ModelProviderPolicyError::new(
                "invalid_exact_tokenizer_receipt",
                "exact tokenizer receipt has invalid identity or zero counts",
            ));
        }
        Ok(())
    }
}

pub trait ModelProviderExactTokenizer: Send + Sync {
    fn tokenize(
        &self,
        request: ModelProviderExactTokenizerRequest<'_>,
    ) -> Result<ModelProviderExactTokenizationReceipt, ModelProviderPolicyError>;
}

#[derive(Clone)]
pub struct ModelProviderExactTokenizerHost {
    capability_id: Arc<str>,
    tokenizer: Arc<dyn ModelProviderExactTokenizer>,
}

impl ModelProviderExactTokenizerHost {
    pub fn new(
        capability_id: impl Into<String>,
        tokenizer: impl ModelProviderExactTokenizer + 'static,
    ) -> Result<Self, ModelProviderPolicyError> {
        let capability_id = capability_id.into();
        if capability_id.is_empty()
            || capability_id.len() > 256
            || capability_id.as_bytes().contains(&0)
        {
            return Err(ModelProviderPolicyError::new(
                "invalid_exact_tokenizer_capability",
                "exact tokenizer capability id must be a bounded non-NUL string",
            ));
        }
        Ok(Self {
            capability_id: Arc::from(capability_id),
            tokenizer: Arc::new(tokenizer),
        })
    }

    pub fn capability_id(&self) -> &str {
        &self.capability_id
    }

    pub fn tokenize(
        &self,
        request: ModelProviderExactTokenizerRequest<'_>,
    ) -> Result<ModelProviderExactTokenizationReceipt, ModelProviderPolicyError> {
        if request.schema_version != MODEL_PROVIDER_EXACT_TOKENIZER_SCHEMA_VERSION
            || request.attempt_id.is_empty()
            || request.provider_id.is_empty()
            || request.model.is_empty()
            || request.canonical_final_request.is_empty()
        {
            return Err(ModelProviderPolicyError::new(
                "invalid_exact_tokenizer_request",
                "exact tokenizer request is incomplete",
            ));
        }
        let receipt = self.tokenizer.tokenize(ModelProviderExactTokenizerRequest {
            schema_version: request.schema_version,
            attempt_id: request.attempt_id,
            provider_id: request.provider_id,
            model: request.model,
            wire_semantic_sha256: request.wire_semantic_sha256,
            canonical_final_request: request.canonical_final_request,
        })?;
        receipt.validate_for(&request, self.capability_id())?;
        Ok(receipt)
    }
}

impl fmt::Debug for ModelProviderExactTokenizerHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ModelProviderExactTokenizerHost")
            .field("capability_id", &self.capability_id)
            .finish_non_exhaustive()
    }
}

#[derive(Debug, Default)]
pub struct ModelProviderExactTokenizationState {
    receipts: Mutex<BTreeMap<String, ModelProviderExactTokenizationReceipt>>,
}

impl ModelProviderExactTokenizationState {
    pub fn record(
        &self,
        receipt: ModelProviderExactTokenizationReceipt,
    ) -> Result<(), ModelProviderPolicyError> {
        receipt.validate_shape()?;
        let mut receipts = self.receipts.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(existing) = receipts.get(receipt.attempt_id()) {
            if existing == &receipt {
                return Ok(());
            }
            return Err(ModelProviderPolicyError::new(
                "exact_tokenizer_receipt_conflict",
                "a different exact tokenizer receipt already exists for this provider attempt",
            ));
        }
        if receipts.len() >= MAX_MODEL_PROVIDER_TOKENIZATION_ATTEMPTS_PER_TURN {
            return Err(ModelProviderPolicyError::new(
                "exact_tokenizer_receipt_limit",
                "turn exact tokenizer receipt limit exceeded",
            ));
        }
        receipts.insert(receipt.attempt_id().to_string(), receipt);
        Ok(())
    }

    pub fn get(&self, attempt_id: &str) -> Option<ModelProviderExactTokenizationReceipt> {
        self.receipts
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .get(attempt_id)
            .cloned()
    }

    pub fn remove(&self, attempt_id: &str) -> Option<ModelProviderExactTokenizationReceipt> {
        self.receipts
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .remove(attempt_id)
    }
}
