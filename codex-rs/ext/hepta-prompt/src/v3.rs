//! Canonical V3 prompt-context bridge for the physical provider spine.
//!
//! The extension contributes exactly one typed developer-policy bundle, asks
//! its host for a fresh context delivery preparation immediately before Core
//! freezes the provider request, persists a dispatch claim before transport,
//! and returns the canonical provider receipt to the host at terminality.

use std::collections::BTreeMap;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_extension_api::ContentItemKind;
use codex_extension_api::ContextContributor;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderContextFinalUseContributor;
use codex_extension_api::ModelProviderContextFinalUseInput;
use codex_extension_api::ModelProviderContextFinalUseProposal;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;
use codex_extension_api::PromptFragment;
use codex_extension_api::TurnContextContributionInput;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_governance::provider_intent;
use codex_hepta_governance::provider_terminal;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::Mutex;

const CONTEXT_BINDING_DOMAIN: &[u8] = b"hepta.runtime-codex.prompt-context.v3";
const MAX_MODEL_BYTES: usize = 256;
const MAX_BUNDLE_BYTES: usize = 16 * 1024 * 1024;
const CAPABILITY_ID: &str = "agentd.prompt-runtime.v3";

#[derive(Clone, Eq, PartialEq)]
pub struct PromptRuntimeContextV3 {
    pub compilation_id: StableId,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub source_binding_digest: Digest32,
    pub execution_profile_digest: Digest32,
    pub tokenization_proof_digest: Digest32,
    pub serialized_token_count: u64,
    pub model: String,
    pub deadline_ms: u64,
    developer_bundle: String,
    binding_digest: Digest32,
}

impl PromptRuntimeContextV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        compilation_id: StableId,
        context_attachment_digest: Digest32,
        context_payload_digest: Digest32,
        source_binding_digest: Digest32,
        execution_profile_digest: Digest32,
        tokenization_proof_digest: Digest32,
        serialized_token_count: u64,
        model: impl Into<String>,
        deadline_ms: u64,
        developer_bundle: impl Into<String>,
    ) -> Result<Self, PromptRuntimeV3Error> {
        let mut value = Self {
            compilation_id,
            context_attachment_digest,
            context_payload_digest,
            source_binding_digest,
            execution_profile_digest,
            tokenization_proof_digest,
            serialized_token_count,
            model: model.into(),
            deadline_ms,
            developer_bundle: developer_bundle.into(),
            binding_digest: Digest32::ZERO,
        };
        value.binding_digest = value.compute_binding_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), PromptRuntimeV3Error> {
        for digest in [
            self.context_attachment_digest,
            self.context_payload_digest,
            self.source_binding_digest,
            self.execution_profile_digest,
            self.tokenization_proof_digest,
            self.binding_digest,
        ] {
            if digest.is_zero() {
                return Err(PromptRuntimeV3Error::InvalidContext);
            }
        }
        if self.model.is_empty()
            || self.model.len() > MAX_MODEL_BYTES
            || self.model.as_bytes().contains(&0)
            || self.deadline_ms == 0
            || self.serialized_token_count == 0
            || self.developer_bundle.is_empty()
            || self.developer_bundle.len() > MAX_BUNDLE_BYTES
            || Digest32::of_bytes(self.developer_bundle.as_bytes()) != self.context_payload_digest
            || self.binding_digest != self.compute_binding_digest()
        {
            return Err(PromptRuntimeV3Error::InvalidContext);
        }
        Ok(())
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    #[must_use]
    pub fn developer_bundle(&self) -> &str {
        &self.developer_bundle
    }

    fn compute_binding_digest(&self) -> Digest32 {
        let mut bytes = CONTEXT_BINDING_DOMAIN.to_vec();
        push_id(&mut bytes, &self.compilation_id);
        for digest in [
            self.context_attachment_digest,
            self.context_payload_digest,
            self.source_binding_digest,
            self.execution_profile_digest,
            self.tokenization_proof_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.serialized_token_count.to_be_bytes());
        push_text(&mut bytes, &self.model);
        bytes.extend_from_slice(&self.deadline_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

impl fmt::Debug for PromptRuntimeContextV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRuntimeContextV3")
            .field("compilation_id", &self.compilation_id)
            .field("context_attachment_digest", &self.context_attachment_digest)
            .field("context_payload_digest", &self.context_payload_digest)
            .field("source_binding_digest", &self.source_binding_digest)
            .field("execution_profile_digest", &self.execution_profile_digest)
            .field("tokenization_proof_digest", &self.tokenization_proof_digest)
            .field("serialized_token_count", &self.serialized_token_count)
            .field("model", &self.model)
            .field("deadline_ms", &self.deadline_ms)
            .field("developer_bundle_bytes", &self.developer_bundle.len())
            .field("binding_digest", &self.binding_digest)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimePrepareRequestV3 {
    pub thread_id: String,
    pub turn_id: String,
    pub model_context_window: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeFinalUseRequestV3 {
    pub compilation_id: StableId,
    pub context_binding_digest: Digest32,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub source_binding_digest: Digest32,
    pub execution_profile_digest: Digest32,
    pub tokenization_proof_digest: Digest32,
    pub serialized_token_count: u64,
    pub attempt_id: String,
    pub base_logical_request_sha256: ModelProviderSha256Digest,
    pub thread_id: String,
    pub turn_id: String,
    pub provider_id: String,
    pub model: String,
    pub transport: ModelProviderTransport,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeFinalUseProofV3 {
    pub compilation_id: StableId,
    pub context_binding_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub source_binding_digest: Digest32,
    pub execution_profile_digest: Digest32,
    pub tokenization_proof_digest: Digest32,
    pub preparation_digest: Digest32,
    pub authority_digest: Digest32,
    pub serialized_token_count: u64,
    pub attempt_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub provider_id: String,
    pub model: String,
    pub prepared_unix_ms: u64,
}

impl PromptRuntimeFinalUseProofV3 {
    pub fn validate_for(
        &self,
        request: &PromptRuntimeFinalUseRequestV3,
    ) -> Result<(), PromptRuntimeV3Error> {
        for digest in [
            self.context_binding_digest,
            self.context_payload_digest,
            self.source_binding_digest,
            self.execution_profile_digest,
            self.tokenization_proof_digest,
            self.preparation_digest,
            self.authority_digest,
        ] {
            if digest.is_zero() {
                return Err(PromptRuntimeV3Error::InvalidFinalUseProof);
            }
        }
        if self.compilation_id != request.compilation_id
            || self.context_binding_digest != request.context_binding_digest
            || self.context_payload_digest != request.context_payload_digest
            || self.source_binding_digest != request.source_binding_digest
            || self.execution_profile_digest != request.execution_profile_digest
            || self.tokenization_proof_digest != request.tokenization_proof_digest
            || self.serialized_token_count != request.serialized_token_count
            || self.attempt_id != request.attempt_id
            || self.thread_id != request.thread_id
            || self.turn_id != request.turn_id
            || self.provider_id != request.provider_id
            || self.model != request.model
            || self.serialized_token_count == 0
            || self.prepared_unix_ms == 0
        {
            return Err(PromptRuntimeV3Error::InvalidFinalUseProof);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeDispatchRecordV3 {
    pub context: PromptRuntimeContextV3,
    pub proof: PromptRuntimeFinalUseProofV3,
    pub intent: ProviderInvocationIntent,
    pub dispatched_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeTerminalRecordV3 {
    pub context: PromptRuntimeContextV3,
    pub proof: PromptRuntimeFinalUseProofV3,
    pub receipt: ProviderInvocationReceipt,
    pub observed_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeHostErrorV3 {
    reason_code: String,
    detail: String,
}

impl PromptRuntimeHostErrorV3 {
    pub fn new(reason_code: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            reason_code: reason_code.into(),
            detail: detail.into(),
        }
    }

    pub fn reason_code(&self) -> &str {
        &self.reason_code
    }

    pub fn detail(&self) -> &str {
        &self.detail
    }
}

impl fmt::Display for PromptRuntimeHostErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.reason_code, self.detail)
    }
}

impl std::error::Error for PromptRuntimeHostErrorV3 {}

pub type PromptRuntimePrepareFutureV3 = Pin<
    Box<
        dyn Future<Output = Result<Option<PromptRuntimeContextV3>, PromptRuntimeHostErrorV3>>
            + Send
            + 'static,
    >,
>;
pub type PromptRuntimeFinalUseFutureV3 = Pin<
    Box<
        dyn Future<Output = Result<PromptRuntimeFinalUseProofV3, PromptRuntimeHostErrorV3>>
            + Send
            + 'static,
    >,
>;
pub type PromptRuntimeDispatchFutureV3 =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostErrorV3>> + Send + 'static>>;
pub type PromptRuntimeRecordFutureV3 =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostErrorV3>> + Send + 'static>>;

type PrepareFnV3 = dyn Fn(PromptRuntimePrepareRequestV3) -> PromptRuntimePrepareFutureV3
    + Send
    + Sync
    + 'static;
type FinalUseFnV3 = dyn Fn(PromptRuntimeFinalUseRequestV3) -> PromptRuntimeFinalUseFutureV3
    + Send
    + Sync
    + 'static;
type DispatchFnV3 = dyn Fn(PromptRuntimeDispatchRecordV3) -> PromptRuntimeDispatchFutureV3
    + Send
    + Sync
    + 'static;
type RecordFnV3 = dyn Fn(PromptRuntimeTerminalRecordV3) -> PromptRuntimeRecordFutureV3
    + Send
    + Sync
    + 'static;

#[derive(Clone)]
pub struct PromptRuntimeHostV3 {
    capability_id: Arc<str>,
    prepare: Arc<PrepareFnV3>,
    final_use: Arc<FinalUseFnV3>,
    dispatch: Arc<DispatchFnV3>,
    record: Arc<RecordFnV3>,
}

impl PromptRuntimeHostV3 {
    pub fn new<P, F, D, R>(
        prepare: P,
        final_use: F,
        dispatch: D,
        record: R,
    ) -> Result<Self, PromptRuntimeV3Error>
    where
        P: Fn(PromptRuntimePrepareRequestV3) -> PromptRuntimePrepareFutureV3
            + Send
            + Sync
            + 'static,
        F: Fn(PromptRuntimeFinalUseRequestV3) -> PromptRuntimeFinalUseFutureV3
            + Send
            + Sync
            + 'static,
        D: Fn(PromptRuntimeDispatchRecordV3) -> PromptRuntimeDispatchFutureV3
            + Send
            + Sync
            + 'static,
        R: Fn(PromptRuntimeTerminalRecordV3) -> PromptRuntimeRecordFutureV3
            + Send
            + Sync
            + 'static,
    {
        StableId::new(CAPABILITY_ID).map_err(|_| PromptRuntimeV3Error::InvalidHost)?;
        Ok(Self {
            capability_id: Arc::from(CAPABILITY_ID),
            prepare: Arc::new(prepare),
            final_use: Arc::new(final_use),
            dispatch: Arc::new(dispatch),
            record: Arc::new(record),
        })
    }

    async fn prepare(
        &self,
        request: PromptRuntimePrepareRequestV3,
    ) -> Result<Option<PromptRuntimeContextV3>, PromptRuntimeHostErrorV3> {
        (self.prepare)(request).await
    }

    async fn final_use(
        &self,
        request: PromptRuntimeFinalUseRequestV3,
    ) -> Result<PromptRuntimeFinalUseProofV3, PromptRuntimeHostErrorV3> {
        (self.final_use)(request).await
    }

    async fn dispatch(
        &self,
        record: PromptRuntimeDispatchRecordV3,
    ) -> Result<(), PromptRuntimeHostErrorV3> {
        (self.dispatch)(record).await
    }

    async fn record(
        &self,
        record: PromptRuntimeTerminalRecordV3,
    ) -> Result<(), PromptRuntimeHostErrorV3> {
        (self.record)(record).await
    }
}

impl fmt::Debug for PromptRuntimeHostV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRuntimeHostV3")
            .field("capability_id", &self.capability_id)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeV3Error {
    InvalidContext,
    InvalidFinalUseProof,
    InvalidProviderBinding,
    InvalidHost,
    ClockUnavailable,
}

impl PromptRuntimeV3Error {
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidContext => "prompt_runtime_v3_invalid_context",
            Self::InvalidFinalUseProof => "prompt_runtime_v3_invalid_final_use_proof",
            Self::InvalidProviderBinding => "prompt_runtime_v3_invalid_provider_binding",
            Self::InvalidHost => "prompt_runtime_v3_invalid_host",
            Self::ClockUnavailable => "prompt_runtime_v3_clock_unavailable",
        }
    }
}

impl fmt::Display for PromptRuntimeV3Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.code())
    }
}

impl std::error::Error for PromptRuntimeV3Error {}

#[derive(Clone)]
enum ResolvedContextV3 {
    None,
    Ready(PromptRuntimeContextV3),
    Failed(PromptRuntimeHostErrorV3),
}

#[derive(Default)]
struct PromptRuntimeTurnStateV3 {
    resolved: Mutex<Option<ResolvedContextV3>>,
    injected: AtomicBool,
    proofs: Mutex<BTreeMap<String, PromptRuntimeFinalUseProofV3>>,
}

#[derive(Clone)]
struct PromptRuntimeExtensionV3 {
    host: PromptRuntimeHostV3,
}

impl PromptRuntimeExtensionV3 {
    async fn resolve(
        &self,
        thread_id: String,
        turn_id: String,
        model_context_window: Option<i64>,
        turn_store: &ExtensionData,
    ) -> ResolvedContextV3 {
        let state = turn_store.get_or_init(PromptRuntimeTurnStateV3::default);
        let mut resolved = state.resolved.lock().await;
        if let Some(value) = resolved.as_ref() {
            return value.clone();
        }
        let value = match self
            .host
            .prepare(PromptRuntimePrepareRequestV3 {
                thread_id,
                turn_id,
                model_context_window,
            })
            .await
        {
            Ok(Some(context)) => match context.validate() {
                Ok(()) => ResolvedContextV3::Ready(context),
                Err(error) => ResolvedContextV3::Failed(PromptRuntimeHostErrorV3::new(
                    error.code(),
                    "host returned an invalid canonical context bundle",
                )),
            },
            Ok(None) => ResolvedContextV3::None,
            Err(error) => ResolvedContextV3::Failed(error),
        };
        *resolved = Some(value.clone());
        value
    }
}

impl ContextContributor for PromptRuntimeExtensionV3 {
    fn contribute_turn_context<'a>(
        &'a self,
        input: TurnContextContributionInput<'a>,
    ) -> ExtensionFuture<'a, Vec<PromptFragment>> {
        Box::pin(async move {
            let resolved = self
                .resolve(
                    input.thread_id.to_owned(),
                    input.turn_id.to_owned(),
                    input.model_context_window,
                    input.turn_store,
                )
                .await;
            let ResolvedContextV3::Ready(context) = resolved else {
                return Vec::new();
            };
            let state = input
                .turn_store
                .get_or_init(PromptRuntimeTurnStateV3::default);
            state.injected.store(true, Ordering::Release);
            vec![PromptFragment::developer_policy(
                context.developer_bundle().to_owned(),
                ContentItemKind("hepta.prompt_context.canonical_v3".to_owned()),
            )]
        })
    }
}

impl ModelProviderContextFinalUseContributor for PromptRuntimeExtensionV3 {
    fn is_active(&self, _thread_store: &ExtensionData, _turn_store: &ExtensionData) -> bool {
        true
    }

    fn prepare<'a>(
        &'a self,
        input: ModelProviderContextFinalUseInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<ModelProviderContextFinalUseProposal>> {
        Box::pin(async move {
            if input.request_kind != ModelProviderRequestKind::Turn || !input.generate {
                return Ok(None);
            }
            let resolved = self
                .resolve(
                    input.thread_id.to_owned(),
                    input.turn_id.to_owned(),
                    /*model_context_window*/ None,
                    input.turn_store,
                )
                .await;
            let context = match resolved {
                ResolvedContextV3::None => return Ok(None),
                ResolvedContextV3::Failed(error) => return Err(policy_error(error)),
                ResolvedContextV3::Ready(context) => context,
            };
            let state = input
                .turn_store
                .get_or_init(PromptRuntimeTurnStateV3::default);
            if !state.injected.load(Ordering::Acquire)
                || input.thread_store.level_id() != input.thread_id
                || input.turn_store.level_id() != input.turn_id
                || input.model != context.model
            {
                return Err(ModelProviderPolicyError::new(
                    "prompt_runtime_v3_scope_mismatch",
                    "canonical context was not injected into this exact provider turn",
                ));
            }
            let request = PromptRuntimeFinalUseRequestV3 {
                compilation_id: context.compilation_id.clone(),
                context_binding_digest: context.binding_digest(),
                context_attachment_digest: context.context_attachment_digest,
                context_payload_digest: context.context_payload_digest,
                source_binding_digest: context.source_binding_digest,
                execution_profile_digest: context.execution_profile_digest,
                tokenization_proof_digest: context.tokenization_proof_digest,
                serialized_token_count: context.serialized_token_count,
                attempt_id: input.attempt_id.to_owned(),
                base_logical_request_sha256: input.base_logical_request_sha256.clone(),
                thread_id: input.thread_id.to_owned(),
                turn_id: input.turn_id.to_owned(),
                provider_id: input.provider_id.to_owned(),
                model: input.model.to_owned(),
                transport: input.transport,
            };
            let proof = self.host.final_use(request.clone()).await.map_err(policy_error)?;
            proof.validate_for(&request).map_err(runtime_policy_error)?;
            state
                .proofs
                .lock()
                .await
                .insert(input.attempt_id.to_owned(), proof.clone());
            Ok(Some(ModelProviderContextFinalUseProposal::new(
                input.attempt_id,
                input.base_logical_request_sha256.clone(),
                input.thread_id,
                input.turn_id,
                input.provider_id,
                input.model,
                api_digest(context.context_payload_digest)?,
                api_digest(proof.authority_digest)?,
                api_digest(context.source_binding_digest)?,
                api_digest(context.execution_profile_digest)?,
                api_digest(context.tokenization_proof_digest)?,
                context.serialized_token_count,
            )?))
        })
    }
}

impl ModelProviderPolicyContributor for PromptRuntimeExtensionV3 {
    fn is_active(&self, _thread_store: &ExtensionData) -> bool {
        true
    }

    fn begin<'a>(
        &'a self,
        input: ModelProviderInvocationInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderPolicyDecision> {
        Box::pin(async move {
            if input.request_kind != ModelProviderRequestKind::Turn || !input.generate {
                return Ok(ModelProviderPolicyDecision::Allow {
                    lease: Box::new(NoopLeaseV3),
                });
            }
            let resolved = self
                .resolve(
                    input.thread_id.to_owned(),
                    input.turn_id.to_owned(),
                    /*model_context_window*/ None,
                    input.turn_store,
                )
                .await;
            let context = match resolved {
                ResolvedContextV3::None => {
                    return Ok(ModelProviderPolicyDecision::Allow {
                        lease: Box::new(NoopLeaseV3),
                    });
                }
                ResolvedContextV3::Failed(error) => return Err(policy_error(error)),
                ResolvedContextV3::Ready(context) => context,
            };
            let state = input
                .turn_store
                .get_or_init(PromptRuntimeTurnStateV3::default);
            let proof = state
                .proofs
                .lock()
                .await
                .remove(input.attempt_id)
                .ok_or_else(|| {
                    ModelProviderPolicyError::new(
                        "prompt_runtime_v3_final_use_missing",
                        "canonical context was not revalidated before provider request finalization",
                    )
                })?;
            let input_digest = input.ephemeral_input_sha256.ok_or_else(|| {
                ModelProviderPolicyError::new(
                    "prompt_runtime_v3_input_digest_missing",
                    "finalized provider request omitted canonical context payload binding",
                )
            })?;
            if input_digest.as_str() != context.context_payload_digest.to_string()
                || input.ephemeral_input_witness_sha256.is_none()
                || proof.attempt_id != input.attempt_id
                || proof.thread_id != input.thread_id
                || proof.turn_id != input.turn_id
                || proof.provider_id != input.provider_id
                || proof.model != input.model
            {
                return Err(ModelProviderPolicyError::new(
                    "prompt_runtime_v3_provider_binding_mismatch",
                    "canonical context final-use proof does not match the exact physical provider request",
                ));
            }
            let intent = provider_intent(&input)?;
            let dispatched_unix_ms = current_unix_ms().map_err(runtime_policy_error)?;
            self.host
                .dispatch(PromptRuntimeDispatchRecordV3 {
                    context: context.clone(),
                    proof: proof.clone(),
                    intent: intent.clone(),
                    dispatched_unix_ms,
                })
                .await
                .map_err(policy_error)?;
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(AttemptLeaseV3 {
                    host: self.host.clone(),
                    context,
                    proof,
                    intent,
                }),
            })
        })
    }
}

struct NoopLeaseV3;

impl ModelProviderAttemptLease for NoopLeaseV3 {
    fn finish(
        self: Box<Self>,
        _terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(std::future::ready(Ok(())))
    }
}

struct AttemptLeaseV3 {
    host: PromptRuntimeHostV3,
    context: PromptRuntimeContextV3,
    proof: PromptRuntimeFinalUseProofV3,
    intent: ProviderInvocationIntent,
}

impl ModelProviderAttemptLease for AttemptLeaseV3 {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            let terminal = provider_terminal(terminal)?;
            let receipt = ProviderInvocationReceipt::new(self.intent, terminal);
            receipt.validate().map_err(|detail| {
                ModelProviderPolicyError::new("prompt_runtime_v3_receipt_invalid", detail)
            })?;
            self.host
                .record(PromptRuntimeTerminalRecordV3 {
                    context: self.context,
                    proof: self.proof,
                    receipt,
                    observed_unix_ms: current_unix_ms().map_err(runtime_policy_error)?,
                })
                .await
                .map_err(policy_error)
        })
    }
}

pub fn install_prompt_runtime_v3<C: Sync>(
    builder: &mut ExtensionRegistryBuilder<C>,
    host: PromptRuntimeHostV3,
) {
    let extension = Arc::new(PromptRuntimeExtensionV3 { host });
    builder.prompt_contributor(extension.clone());
    builder.model_provider_context_final_use_contributor(extension.clone());
    builder.model_provider_policy_contributor(extension);
}

fn api_digest(digest: Digest32) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    ModelProviderSha256Digest::parse(digest.to_string())
}

fn policy_error(error: PromptRuntimeHostErrorV3) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(error.reason_code().to_owned(), error.detail().to_owned())
}

fn runtime_policy_error(error: PromptRuntimeV3Error) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(error.code(), error.to_string())
}

fn current_unix_ms() -> Result<u64, PromptRuntimeV3Error> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| PromptRuntimeV3Error::ClockUnavailable)
        .and_then(|duration| {
            u64::try_from(duration.as_millis()).map_err(|_| PromptRuntimeV3Error::ClockUnavailable)
        })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
