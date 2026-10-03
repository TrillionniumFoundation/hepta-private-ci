//! Content-addressed immutable tokenizer custody and execution contract.
//!
//! Production execution is host-owned. Agentd supplies exact provider-body
//! bytes and receives an attested count bound to immutable executable and
//! vocabulary objects. The interface exposes no mutable filesystem path and no
//! model-name lookup, path reopen, token estimate, or provider-usage fallback.

use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const BUNDLE_DOMAIN: &[u8] = b"hepta.context-tokenizer-immutable-bundle.v3";
const REQUEST_DOMAIN: &[u8] = b"hepta.context-tokenizer-execution-request.v3";
const RECEIPT_DOMAIN: &[u8] = b"hepta.context-tokenizer-execution-receipt.v3";

#[derive(Clone, Eq, PartialEq)]
pub struct ImmutableTokenizerBundleIdentityV3 {
    pub provider_id: StableId,
    pub model_id: StableId,
    pub tokenizer_profile_digest: Digest32,
    pub executable_object_id: StableId,
    pub executable_digest: Digest32,
    pub vocabulary_object_id: StableId,
    pub vocabulary_digest: Digest32,
    pub normalization_policy_digest: Digest32,
    pub template_revision_digest: Digest32,
    pub custody_authority_digest: Digest32,
    pub object_generation: u64,
    bundle_digest: Digest32,
}

impl ImmutableTokenizerBundleIdentityV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        provider_id: StableId,
        model_id: StableId,
        tokenizer_profile_digest: Digest32,
        executable_object_id: StableId,
        executable_digest: Digest32,
        vocabulary_object_id: StableId,
        vocabulary_digest: Digest32,
        normalization_policy_digest: Digest32,
        template_revision_digest: Digest32,
        custody_authority_digest: Digest32,
        object_generation: u64,
    ) -> Result<Self, ImmutableTokenizerCustodyErrorV3> {
        let mut value = Self {
            provider_id,
            model_id,
            tokenizer_profile_digest,
            executable_object_id,
            executable_digest,
            vocabulary_object_id,
            vocabulary_digest,
            normalization_policy_digest,
            template_revision_digest,
            custody_authority_digest,
            object_generation,
            bundle_digest: Digest32::ZERO,
        };
        value.bundle_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ImmutableTokenizerCustodyErrorV3> {
        if [
            self.tokenizer_profile_digest,
            self.executable_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
            self.template_revision_digest,
            self.custody_authority_digest,
            self.bundle_digest,
        ]
        .into_iter()
        .any(Digest32::is_zero)
            || self.object_generation == 0
            || self.bundle_digest != self.compute_digest()
        {
            return Err(ImmutableTokenizerCustodyErrorV3::InvalidBundle);
        }
        Ok(())
    }

    #[must_use]
    pub const fn bundle_digest(&self) -> Digest32 {
        self.bundle_digest
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = BUNDLE_DOMAIN.to_vec();
        for value in [
            &self.provider_id,
            &self.model_id,
            &self.executable_object_id,
            &self.vocabulary_object_id,
        ] {
            push_id(&mut bytes, value);
        }
        for digest in [
            self.tokenizer_profile_digest,
            self.executable_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
            self.template_revision_digest,
            self.custody_authority_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.object_generation.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

impl fmt::Debug for ImmutableTokenizerBundleIdentityV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ImmutableTokenizerBundleIdentityV3")
            .field("provider_id", &self.provider_id)
            .field("model_id", &self.model_id)
            .field("tokenizer_profile_digest", &self.tokenizer_profile_digest)
            .field("executable_object_id", &self.executable_object_id)
            .field("executable_digest", &self.executable_digest)
            .field("vocabulary_object_id", &self.vocabulary_object_id)
            .field("vocabulary_digest", &self.vocabulary_digest)
            .field(
                "normalization_policy_digest",
                &self.normalization_policy_digest,
            )
            .field("template_revision_digest", &self.template_revision_digest)
            .field("custody_authority_digest", &self.custody_authority_digest)
            .field("object_generation", &self.object_generation)
            .field("bundle_digest", &self.bundle_digest)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ImmutableTokenizerExecutionRequestV3 {
    pub attempt_id: StableId,
    pub exact_body_digest: Digest32,
    pub bundle_digest: Digest32,
    pub maximum_tokens: u64,
    pub deadline_unix_ms: u64,
    pub request_digest: Digest32,
}

impl ImmutableTokenizerExecutionRequestV3 {
    pub fn new(
        attempt_id: StableId,
        exact_body_digest: Digest32,
        bundle: &ImmutableTokenizerBundleIdentityV3,
        maximum_tokens: u64,
        deadline_unix_ms: u64,
    ) -> Result<Self, ImmutableTokenizerCustodyErrorV3> {
        bundle.validate()?;
        if exact_body_digest.is_zero() || maximum_tokens == 0 || deadline_unix_ms == 0 {
            return Err(ImmutableTokenizerCustodyErrorV3::InvalidRequest);
        }
        let mut bytes = REQUEST_DOMAIN.to_vec();
        push_id(&mut bytes, &attempt_id);
        bytes.extend_from_slice(exact_body_digest.as_array());
        bytes.extend_from_slice(bundle.bundle_digest().as_array());
        bytes.extend_from_slice(&maximum_tokens.to_be_bytes());
        bytes.extend_from_slice(&deadline_unix_ms.to_be_bytes());
        Ok(Self {
            attempt_id,
            exact_body_digest,
            bundle_digest: bundle.bundle_digest(),
            maximum_tokens,
            deadline_unix_ms,
            request_digest: Digest32::of_bytes(&bytes),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ImmutableTokenizerExecutionReceiptV3 {
    pub request_digest: Digest32,
    pub exact_body_digest: Digest32,
    pub bundle_digest: Digest32,
    pub custody_authority_digest: Digest32,
    pub executor_digest: Digest32,
    pub token_count: u64,
    pub started_unix_ms: u64,
    pub completed_unix_ms: u64,
    pub receipt_digest: Digest32,
}

impl ImmutableTokenizerExecutionReceiptV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_host(
        request: &ImmutableTokenizerExecutionRequestV3,
        bundle: &ImmutableTokenizerBundleIdentityV3,
        executor_digest: Digest32,
        token_count: u64,
        started_unix_ms: u64,
        completed_unix_ms: u64,
    ) -> Result<Self, ImmutableTokenizerCustodyErrorV3> {
        bundle.validate()?;
        if request.bundle_digest != bundle.bundle_digest()
            || request.exact_body_digest.is_zero()
            || executor_digest.is_zero()
            || token_count == 0
            || token_count > request.maximum_tokens
            || started_unix_ms == 0
            || completed_unix_ms < started_unix_ms
            || completed_unix_ms >= request.deadline_unix_ms
        {
            return Err(ImmutableTokenizerCustodyErrorV3::InvalidReceipt);
        }
        let mut bytes = RECEIPT_DOMAIN.to_vec();
        for digest in [
            request.request_digest,
            request.exact_body_digest,
            bundle.bundle_digest(),
            bundle.custody_authority_digest,
            executor_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&token_count.to_be_bytes());
        bytes.extend_from_slice(&started_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&completed_unix_ms.to_be_bytes());
        Ok(Self {
            request_digest: request.request_digest,
            exact_body_digest: request.exact_body_digest,
            bundle_digest: bundle.bundle_digest(),
            custody_authority_digest: bundle.custody_authority_digest,
            executor_digest,
            token_count,
            started_unix_ms,
            completed_unix_ms,
            receipt_digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn validate_for(
        &self,
        request: &ImmutableTokenizerExecutionRequestV3,
        bundle: &ImmutableTokenizerBundleIdentityV3,
    ) -> Result<(), ImmutableTokenizerCustodyErrorV3> {
        let recomputed = Self::from_host(
            request,
            bundle,
            self.executor_digest,
            self.token_count,
            self.started_unix_ms,
            self.completed_unix_ms,
        )?;
        if &recomputed != self {
            return Err(ImmutableTokenizerCustodyErrorV3::InvalidReceipt);
        }
        Ok(())
    }
}

pub trait ImmutableTokenizerExecutorV3: Send + Sync {
    fn executor_digest(&self) -> Digest32;

    fn bundle_identity(
        &self,
        provider_id: &StableId,
        model_id: &StableId,
    ) -> Result<ImmutableTokenizerBundleIdentityV3, String>;

    fn count_exact_body(
        &self,
        bundle: &ImmutableTokenizerBundleIdentityV3,
        request: &ImmutableTokenizerExecutionRequestV3,
        exact_body: &[u8],
    ) -> Result<ImmutableTokenizerExecutionReceiptV3, String>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ImmutableTokenizerCustodyErrorV3 {
    InvalidBundle,
    InvalidRequest,
    InvalidReceipt,
    BodyDigestMismatch,
    ExecutorMismatch,
    HostRejected,
}

impl ImmutableTokenizerCustodyErrorV3 {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidBundle => "immutable_tokenizer_invalid_bundle",
            Self::InvalidRequest => "immutable_tokenizer_invalid_request",
            Self::InvalidReceipt => "immutable_tokenizer_invalid_receipt",
            Self::BodyDigestMismatch => "immutable_tokenizer_body_digest_mismatch",
            Self::ExecutorMismatch => "immutable_tokenizer_executor_mismatch",
            Self::HostRejected => "immutable_tokenizer_host_rejected",
        }
    }
}

impl fmt::Display for ImmutableTokenizerCustodyErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl std::error::Error for ImmutableTokenizerCustodyErrorV3 {}

pub fn execute_immutable_tokenizer_v3(
    executor: &impl ImmutableTokenizerExecutorV3,
    bundle: &ImmutableTokenizerBundleIdentityV3,
    request: &ImmutableTokenizerExecutionRequestV3,
    exact_body: &[u8],
) -> Result<ImmutableTokenizerExecutionReceiptV3, ImmutableTokenizerCustodyErrorV3> {
    bundle.validate()?;
    if Digest32::of_bytes(exact_body) != request.exact_body_digest {
        return Err(ImmutableTokenizerCustodyErrorV3::BodyDigestMismatch);
    }
    let resolved = executor
        .bundle_identity(&bundle.provider_id, &bundle.model_id)
        .map_err(|_| ImmutableTokenizerCustodyErrorV3::HostRejected)?;
    if resolved != *bundle
        || bundle.bundle_digest() != request.bundle_digest
        || executor.executor_digest().is_zero()
    {
        return Err(ImmutableTokenizerCustodyErrorV3::ExecutorMismatch);
    }
    let receipt = executor
        .count_exact_body(bundle, request, exact_body)
        .map_err(|_| ImmutableTokenizerCustodyErrorV3::HostRejected)?;
    receipt.validate_for(request, bundle)?;
    Ok(receipt)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|_| panic!("invalid test id"))
    }

    fn bundle() -> ImmutableTokenizerBundleIdentityV3 {
        ImmutableTokenizerBundleIdentityV3::new(
            id("provider"),
            id("model"),
            Digest32::of_bytes(b"profile"),
            id("sha256-executable"),
            Digest32::of_bytes(b"executable"),
            id("sha256-vocabulary"),
            Digest32::of_bytes(b"vocabulary"),
            Digest32::of_bytes(b"normalization"),
            Digest32::of_bytes(b"template"),
            Digest32::of_bytes(b"custody"),
            4,
        )
        .unwrap_or_else(|_| panic!("valid bundle"))
    }

    struct FixtureExecutor {
        bundle: ImmutableTokenizerBundleIdentityV3,
    }

    impl ImmutableTokenizerExecutorV3 for FixtureExecutor {
        fn executor_digest(&self) -> Digest32 {
            Digest32::of_bytes(b"executor")
        }

        fn bundle_identity(
            &self,
            _provider_id: &StableId,
            _model_id: &StableId,
        ) -> Result<ImmutableTokenizerBundleIdentityV3, String> {
            Ok(self.bundle.clone())
        }

        fn count_exact_body(
            &self,
            bundle: &ImmutableTokenizerBundleIdentityV3,
            request: &ImmutableTokenizerExecutionRequestV3,
            _exact_body: &[u8],
        ) -> Result<ImmutableTokenizerExecutionReceiptV3, String> {
            ImmutableTokenizerExecutionReceiptV3::from_host(
                request,
                bundle,
                self.executor_digest(),
                8,
                100,
                101,
            )
            .map_err(|error| error.to_string())
        }
    }

    #[test]
    fn receipt_binds_exact_body_and_immutable_objects() {
        let bundle = bundle();
        let body = b"exact provider body";
        let request = ImmutableTokenizerExecutionRequestV3::new(
            id("attempt"),
            Digest32::of_bytes(body),
            &bundle,
            100,
            1_000,
        )
        .unwrap_or_else(|_| panic!("valid request"));
        let receipt = execute_immutable_tokenizer_v3(
            &FixtureExecutor {
                bundle: bundle.clone(),
            },
            &bundle,
            &request,
            body,
        )
        .unwrap_or_else(|_| panic!("valid receipt"));
        assert_eq!(receipt.exact_body_digest, request.exact_body_digest);
        assert_eq!(receipt.bundle_digest, bundle.bundle_digest());
        assert!(!receipt.receipt_digest.is_zero());
    }

    #[test]
    fn mutable_body_and_object_drift_are_rejected() {
        let bundle = bundle();
        let request = ImmutableTokenizerExecutionRequestV3::new(
            id("attempt"),
            Digest32::of_bytes(b"body-a"),
            &bundle,
            100,
            1_000,
        )
        .unwrap_or_else(|_| panic!("valid request"));
        assert_eq!(
            execute_immutable_tokenizer_v3(
                &FixtureExecutor {
                    bundle: bundle.clone(),
                },
                &bundle,
                &request,
                b"body-b",
            ),
            Err(ImmutableTokenizerCustodyErrorV3::BodyDigestMismatch)
        );
        let drifted = ImmutableTokenizerBundleIdentityV3::new(
            bundle.provider_id.clone(),
            bundle.model_id.clone(),
            bundle.tokenizer_profile_digest,
            id("other-executable"),
            Digest32::of_bytes(b"other-executable"),
            bundle.vocabulary_object_id.clone(),
            bundle.vocabulary_digest,
            bundle.normalization_policy_digest,
            bundle.template_revision_digest,
            bundle.custody_authority_digest,
            bundle.object_generation,
        )
        .unwrap_or_else(|_| panic!("valid drifted bundle"));
        assert_eq!(
            execute_immutable_tokenizer_v3(
                &FixtureExecutor { bundle: drifted },
                &bundle,
                &request,
                b"body-a",
            ),
            Err(ImmutableTokenizerCustodyErrorV3::ExecutorMismatch)
        );
    }
}
