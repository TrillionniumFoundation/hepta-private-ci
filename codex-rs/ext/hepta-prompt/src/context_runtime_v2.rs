use std::collections::BTreeMap;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::str::FromStr;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputContributor;
use codex_extension_api::EphemeralModelInputFinalUseGuard;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::EphemeralModelInputSource;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal as ApiTerminal;
use codex_extension_api::ModelProviderTransport as ApiTransport;
use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::Mutex;

const SOURCE_ID: &str = "hepta_context_compiler_v2";
const ATTACHMENT_DOMAIN: &[u8] = b"hepta.context-compiler.runtime-attachment.v2";
const DISPATCH_DOMAIN: &[u8] = b"hepta.context-compiler.runtime-dispatch.v2";
const MAX_PAYLOAD_BYTES: usize = 16 * 1024 * 1024;
const MAX_PAYLOAD_TOKENS: u64 = 1_000_000;
const MAX_ID_BYTES: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilerRuntimePrepareRequestV2 {
    pub attempt_id: String,
    pub base_logical_request_sha256: ModelProviderSha256Digest,
    pub thread_id: String,
    pub turn_id: String,
    pub provider_id: String,
    pub model: String,
    pub model_context_window: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilerRuntimeAttachmentMetadataV2 {
    compilation_id: StableId,
    context_attachment_digest: Digest32,
    preparation_digest: Digest32,
    payload_digest: Digest32,
    provider_id_digest: Digest32,
    provider_model_digest: Digest32,
    serialized_token_count: u64,
    deadline_ms: u64,
    source_binding_digest: Digest32,
}

impl ContextCompilerRuntimeAttachmentMetadataV2 {
    #[must_use]
    pub fn compilation_id(&self) -> &StableId {
        &self.compilation_id
    }

    #[must_use]
    pub const fn context_attachment_digest(&self) -> Digest32 {
        self.context_attachment_digest
    }

    #[must_use]
    pub const fn preparation_digest(&self) -> Digest32 {
        self.preparation_digest
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub const fn provider_id_digest(&self) -> Digest32 {
        self.provider_id_digest
    }

    #[must_use]
    pub const fn provider_model_digest(&self) -> Digest32 {
        self.provider_model_digest
    }

    #[must_use]
    pub const fn serialized_token_count(&self) -> u64 {
        self.serialized_token_count
    }

    #[must_use]
    pub const fn deadline_ms(&self) -> u64 {
        self.deadline_ms
    }

    #[must_use]
    pub const fn source_binding_digest(&self) -> Digest32 {
        self.source_binding_digest
    }

    pub fn validate(&self) -> Result<(), ContextCompilerRuntimeHostErrorV2> {
        if self.context_attachment_digest.is_zero()
            || self.preparation_digest.is_zero()
            || self.payload_digest.is_zero()
            || self.provider_id_digest.is_zero()
            || self.provider_model_digest.is_zero()
            || self.source_binding_digest.is_zero()
            || self.serialized_token_count == 0
            || self.serialized_token_count > MAX_PAYLOAD_TOKENS
            || self.deadline_ms == 0
            || self.source_binding_digest != self.compute_source_binding_digest()
        {
            return Err(ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_attachment_invalid",
                "context compiler runtime attachment metadata is invalid",
            ));
        }
        Ok(())
    }

    fn compute_source_binding_digest(&self) -> Digest32 {
        let mut bytes = ATTACHMENT_DOMAIN.to_vec();
        push_id(&mut bytes, &self.compilation_id);
        for digest in [
            self.context_attachment_digest,
            self.preparation_digest,
            self.payload_digest,
            self.provider_id_digest,
            self.provider_model_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.serialized_token_count.to_be_bytes());
        bytes.extend_from_slice(&self.deadline_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

/// One-shot exact provider-visible developer-policy payload.
///
/// Debug output is explicitly redacted; this type is not serializable and is
/// consumed when the extension creates the one physical-send proposal.
pub struct ContextCompilerRuntimeAttachmentV2 {
    metadata: ContextCompilerRuntimeAttachmentMetadataV2,
    serialized_payload: String,
}

impl fmt::Debug for ContextCompilerRuntimeAttachmentV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextCompilerRuntimeAttachmentV2")
            .field("metadata", &self.metadata)
            .field("payload_bytes", &self.serialized_payload.len())
            .finish()
    }
}

impl ContextCompilerRuntimeAttachmentV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        compilation_id: StableId,
        context_attachment_digest: Digest32,
        preparation_digest: Digest32,
        payload_digest: Digest32,
        provider_id_digest: Digest32,
        provider_model_digest: Digest32,
        serialized_token_count: u64,
        deadline_ms: u64,
        serialized_payload: String,
    ) -> Result<Self, ContextCompilerRuntimeHostErrorV2> {
        if serialized_payload.is_empty()
            || serialized_payload.len() > MAX_PAYLOAD_BYTES
            || serialized_payload.as_bytes().contains(&0)
            || Digest32::of_bytes(serialized_payload.as_bytes()) != payload_digest
        {
            return Err(ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_payload_invalid",
                "context compiler runtime payload is empty, oversized or digest-mismatched",
            ));
        }
        let mut metadata = ContextCompilerRuntimeAttachmentMetadataV2 {
            compilation_id,
            context_attachment_digest,
            preparation_digest,
            payload_digest,
            provider_id_digest,
            provider_model_digest,
            serialized_token_count,
            deadline_ms,
            source_binding_digest: Digest32::ZERO,
        };
        metadata.source_binding_digest = metadata.compute_source_binding_digest();
        metadata.validate()?;
        Ok(Self {
            metadata,
            serialized_payload,
        })
    }

    pub fn into_parts(self) -> (ContextCompilerRuntimeAttachmentMetadataV2, String) {
        (self.metadata, self.serialized_payload)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilerRuntimeFinalUseV2 {
    pub metadata: ContextCompilerRuntimeAttachmentMetadataV2,
    pub attempt_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub provider_id: String,
    pub model: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilerRuntimeDispatchV2 {
    metadata: ContextCompilerRuntimeAttachmentMetadataV2,
    intent: ProviderInvocationIntent,
    dispatched_unix_ms: u64,
    dispatch_digest: Digest32,
}

impl ContextCompilerRuntimeDispatchV2 {
    pub fn new(
        metadata: ContextCompilerRuntimeAttachmentMetadataV2,
        intent: ProviderInvocationIntent,
        dispatched_unix_ms: u64,
    ) -> Result<Self, ContextCompilerRuntimeHostErrorV2> {
        metadata.validate()?;
        intent.validate().map_err(|detail| {
            ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_provider_intent_invalid",
                detail,
            )
        })?;
        let expected_input = Sha256Digest::parse(metadata.payload_digest.to_string()).map_err(
            |detail| {
                ContextCompilerRuntimeHostErrorV2::new(
                    "context_compiler_runtime_payload_digest_invalid",
                    detail,
                )
            },
        )?;
        if dispatched_unix_ms == 0
            || intent.binding.ephemeral_input_sha256.as_ref() != Some(&expected_input)
            || Digest32::of_bytes(intent.binding.provider_id.as_bytes())
                != metadata.provider_id_digest
            || Digest32::of_bytes(intent.binding.model.as_bytes())
                != metadata.provider_model_digest
        {
            return Err(ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_dispatch_binding_mismatch",
                "provider intent does not bind the compiled context attachment",
            ));
        }
        let intent_bytes = intent.canonical_wire_bytes().map_err(|detail| {
            ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_provider_intent_invalid",
                detail,
            )
        })?;
        let mut bytes = DISPATCH_DOMAIN.to_vec();
        bytes.extend_from_slice(metadata.source_binding_digest.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&intent_bytes).as_array());
        bytes.extend_from_slice(&dispatched_unix_ms.to_be_bytes());
        let dispatch_digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            metadata,
            intent,
            dispatched_unix_ms,
            dispatch_digest,
        })
    }

    #[must_use]
    pub const fn metadata(&self) -> &ContextCompilerRuntimeAttachmentMetadataV2 {
        &self.metadata
    }

    #[must_use]
    pub const fn intent(&self) -> &ProviderInvocationIntent {
        &self.intent
    }

    #[must_use]
    pub const fn dispatched_unix_ms(&self) -> u64 {
        self.dispatched_unix_ms
    }

    #[must_use]
    pub const fn dispatch_digest(&self) -> Digest32 {
        self.dispatch_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilerRuntimeTerminalV2 {
    dispatch: ContextCompilerRuntimeDispatchV2,
    receipt: ProviderInvocationReceipt,
    observed_unix_ms: u64,
}

impl ContextCompilerRuntimeTerminalV2 {
    pub fn new(
        dispatch: ContextCompilerRuntimeDispatchV2,
        terminal: ProviderTerminal,
        observed_unix_ms: u64,
    ) -> Result<Self, ContextCompilerRuntimeHostErrorV2> {
        let receipt = ProviderInvocationReceipt::new(dispatch.intent.clone(), terminal);
        receipt.validate().map_err(|detail| {
            ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_provider_receipt_invalid",
                detail,
            )
        })?;
        if observed_unix_ms < dispatch.dispatched_unix_ms {
            return Err(ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_terminal_time_invalid",
                "provider terminal time precedes the durable dispatch claim",
            ));
        }
        Ok(Self {
            dispatch,
            receipt,
            observed_unix_ms,
        })
    }

    #[must_use]
    pub const fn dispatch(&self) -> &ContextCompilerRuntimeDispatchV2 {
        &self.dispatch
    }

    #[must_use]
    pub const fn receipt(&self) -> &ProviderInvocationReceipt {
        &self.receipt
    }

    #[must_use]
    pub const fn observed_unix_ms(&self) -> u64 {
        self.observed_unix_ms
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilerRuntimeHostErrorV2 {
    reason_code: String,
    detail: String,
}

impl ContextCompilerRuntimeHostErrorV2 {
    pub fn new(reason_code: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            reason_code: reason_code.into(),
            detail: detail.into(),
        }
    }

    #[must_use]
    pub fn reason_code(&self) -> &str {
        &self.reason_code
    }

    #[must_use]
    pub fn detail(&self) -> &str {
        &self.detail
    }
}

impl fmt::Display for ContextCompilerRuntimeHostErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.reason_code, self.detail)
    }
}

impl std::error::Error for ContextCompilerRuntimeHostErrorV2 {}

pub type ContextCompilerRuntimePrepareFutureV2 = Pin<
    Box<
        dyn Future<
                Output = Result<
                    Option<ContextCompilerRuntimeAttachmentV2>,
                    ContextCompilerRuntimeHostErrorV2,
                >,
            > + Send
            + 'static,
    >,
>;
pub type ContextCompilerRuntimeFinalUseFutureV2 = Pin<
    Box<dyn Future<Output = Result<(), ContextCompilerRuntimeHostErrorV2>> + Send + 'static>,
>;
pub type ContextCompilerRuntimeDispatchFutureV2 = ContextCompilerRuntimeFinalUseFutureV2;
pub type ContextCompilerRuntimeRecordFutureV2 = ContextCompilerRuntimeFinalUseFutureV2;

type PrepareFn = dyn Fn(ContextCompilerRuntimePrepareRequestV2) -> ContextCompilerRuntimePrepareFutureV2
    + Send
    + Sync
    + 'static;
type FinalUseFn = dyn Fn(ContextCompilerRuntimeFinalUseV2) -> ContextCompilerRuntimeFinalUseFutureV2
    + Send
    + Sync
    + 'static;
type DispatchFn = dyn Fn(ContextCompilerRuntimeDispatchV2) -> ContextCompilerRuntimeDispatchFutureV2
    + Send
    + Sync
    + 'static;
type RecordFn = dyn Fn(ContextCompilerRuntimeTerminalV2) -> ContextCompilerRuntimeRecordFutureV2
    + Send
    + Sync
    + 'static;

#[derive(Clone)]
pub struct ContextCompilerRuntimeHostV2 {
    capability_id: Arc<str>,
    prepare: Arc<PrepareFn>,
    final_use: Arc<FinalUseFn>,
    dispatch: Arc<DispatchFn>,
    record: Arc<RecordFn>,
}

impl ContextCompilerRuntimeHostV2 {
    pub fn new<P, F, D, R>(
        capability_id: impl Into<String>,
        prepare: P,
        final_use: F,
        dispatch: D,
        record: R,
    ) -> Result<Self, ContextCompilerRuntimeHostErrorV2>
    where
        P: Fn(ContextCompilerRuntimePrepareRequestV2) -> ContextCompilerRuntimePrepareFutureV2
            + Send
            + Sync
            + 'static,
        F: Fn(ContextCompilerRuntimeFinalUseV2) -> ContextCompilerRuntimeFinalUseFutureV2
            + Send
            + Sync
            + 'static,
        D: Fn(ContextCompilerRuntimeDispatchV2) -> ContextCompilerRuntimeDispatchFutureV2
            + Send
            + Sync
            + 'static,
        R: Fn(ContextCompilerRuntimeTerminalV2) -> ContextCompilerRuntimeRecordFutureV2
            + Send
            + Sync
            + 'static,
    {
        let capability_id = capability_id.into();
        StableId::new(capability_id.clone()).map_err(|_| {
            ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_capability_invalid",
                "context compiler runtime capability identity is invalid",
            )
        })?;
        Ok(Self {
            capability_id: Arc::from(capability_id),
            prepare: Arc::new(prepare),
            final_use: Arc::new(final_use),
            dispatch: Arc::new(dispatch),
            record: Arc::new(record),
        })
    }

    async fn prepare(
        &self,
        request: ContextCompilerRuntimePrepareRequestV2,
    ) -> Result<Option<ContextCompilerRuntimeAttachmentV2>, ContextCompilerRuntimeHostErrorV2> {
        (self.prepare)(request).await
    }

    async fn final_use(
        &self,
        request: ContextCompilerRuntimeFinalUseV2,
    ) -> Result<(), ContextCompilerRuntimeHostErrorV2> {
        (self.final_use)(request).await
    }

    async fn dispatch(
        &self,
        record: ContextCompilerRuntimeDispatchV2,
    ) -> Result<(), ContextCompilerRuntimeHostErrorV2> {
        (self.dispatch)(record).await
    }

    async fn record(
        &self,
        record: ContextCompilerRuntimeTerminalV2,
    ) -> Result<(), ContextCompilerRuntimeHostErrorV2> {
        (self.record)(record).await
    }
}

impl fmt::Debug for ContextCompilerRuntimeHostV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextCompilerRuntimeHostV2")
            .field("capability_id", &self.capability_id)
            .finish_non_exhaustive()
    }
}

impl PartialEq for ContextCompilerRuntimeHostV2 {
    fn eq(&self, other: &Self) -> bool {
        self.capability_id == other.capability_id
            && Arc::ptr_eq(&self.prepare, &other.prepare)
            && Arc::ptr_eq(&self.final_use, &other.final_use)
            && Arc::ptr_eq(&self.dispatch, &other.dispatch)
            && Arc::ptr_eq(&self.record, &other.record)
    }
}

impl Eq for ContextCompilerRuntimeHostV2 {}

#[derive(Clone)]
struct PreparedAttemptV2 {
    metadata: ContextCompilerRuntimeAttachmentMetadataV2,
    thread_id: String,
    turn_id: String,
    provider_id: String,
    model: String,
}

#[derive(Default)]
struct ContextCompilerRuntimeTurnStateV2 {
    attempts: Mutex<BTreeMap<String, PreparedAttemptV2>>,
}

#[derive(Clone)]
struct ContextCompilerRuntimeExtensionV2 {
    host: ContextCompilerRuntimeHostV2,
}

impl EphemeralModelInputContributor for ContextCompilerRuntimeExtensionV2 {
    fn is_active(&self, _thread_store: &ExtensionData, _turn_store: &ExtensionData) -> bool {
        true
    }

    fn contribute<'a>(
        &'a self,
        input: EphemeralModelInputContext<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<EphemeralModelInputProposal>> {
        Box::pin(async move {
            if input.request_kind != ModelProviderRequestKind::Turn || !input.generate {
                return Ok(None);
            }
            let prepared = self
                .host
                .prepare(ContextCompilerRuntimePrepareRequestV2 {
                    attempt_id: input.attempt_id.to_owned(),
                    base_logical_request_sha256: input.base_logical_request_sha256.clone(),
                    thread_id: input.thread_id.to_owned(),
                    turn_id: input.turn_id.to_owned(),
                    provider_id: input.provider_id.to_owned(),
                    model: input.model.to_owned(),
                    model_context_window: input.model_context_window,
                })
                .await
                .map_err(policy_error)?;
            let Some(prepared) = prepared else {
                return Ok(None);
            };
            let (metadata, payload) = prepared.into_parts();
            metadata.validate().map_err(policy_error)?;
            let now = current_unix_ms().map_err(policy_error)?;
            if now >= metadata.deadline_ms
                || Digest32::of_bytes(input.provider_id.as_bytes()) != metadata.provider_id_digest
                || Digest32::of_bytes(input.model.as_bytes()) != metadata.provider_model_digest
                || input
                    .model_context_window
                    .is_some_and(|window| window <= 0 || metadata.serialized_token_count > window as u64)
            {
                return Err(ModelProviderPolicyError::new(
                    "context_compiler_runtime_prepare_binding_mismatch",
                    "prepared context does not match the physical provider attempt",
                ));
            }
            let attempt = PreparedAttemptV2 {
                metadata: metadata.clone(),
                thread_id: input.thread_id.to_owned(),
                turn_id: input.turn_id.to_owned(),
                provider_id: input.provider_id.to_owned(),
                model: input.model.to_owned(),
            };
            let state = input
                .turn_store
                .get_or_init(ContextCompilerRuntimeTurnStateV2::default);
            let mut attempts = state.attempts.lock().await;
            if let Some(existing) = attempts.get(input.attempt_id) {
                if existing.metadata != attempt.metadata
                    || existing.thread_id != attempt.thread_id
                    || existing.turn_id != attempt.turn_id
                    || existing.provider_id != attempt.provider_id
                    || existing.model != attempt.model
                {
                    return Err(ModelProviderPolicyError::new(
                        "context_compiler_runtime_attempt_conflict",
                        "one physical attempt cannot bind two context preparations",
                    ));
                }
            } else {
                attempts.insert(input.attempt_id.to_owned(), attempt);
            }
            drop(attempts);

            let source = EphemeralModelInputSource::parse(SOURCE_ID)?;
            let source_binding = ModelProviderSha256Digest::parse(
                metadata.source_binding_digest.to_string(),
            )?;
            let content_digest =
                ModelProviderSha256Digest::parse(metadata.payload_digest.to_string())?;
            let claimed_token_count = u32::try_from(metadata.serialized_token_count).map_err(|_| {
                ModelProviderPolicyError::new(
                    "context_compiler_runtime_token_count_invalid",
                    "compiled context token count exceeds the runtime contract",
                )
            })?;
            let guard = ContextCompilerFinalUseGuardV2 {
                host: self.host.clone(),
                request: ContextCompilerRuntimeFinalUseV2 {
                    metadata,
                    attempt_id: input.attempt_id.to_owned(),
                    thread_id: input.thread_id.to_owned(),
                    turn_id: input.turn_id.to_owned(),
                    provider_id: input.provider_id.to_owned(),
                    model: input.model.to_owned(),
                },
            };
            EphemeralModelInputProposal::new_developer_policy(
                source,
                input.attempt_id,
                input.base_logical_request_sha256.clone(),
                input.thread_id,
                input.turn_id,
                source_binding,
                content_digest,
                payload,
                claimed_token_count,
            )
            .map(|proposal| Some(proposal.with_final_use_guard(Box::new(guard))))
        })
    }
}

struct ContextCompilerFinalUseGuardV2 {
    host: ContextCompilerRuntimeHostV2,
    request: ContextCompilerRuntimeFinalUseV2,
}

impl EphemeralModelInputFinalUseGuard for ContextCompilerFinalUseGuardV2 {
    fn revalidate(self: Box<Self>) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move { self.host.final_use(self.request).await.map_err(policy_error) })
    }
}

impl ModelProviderPolicyContributor for ContextCompilerRuntimeExtensionV2 {
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
                    lease: Box::new(ContextCompilerNoopLeaseV2),
                });
            }
            let state = input
                .turn_store
                .get_or_init(ContextCompilerRuntimeTurnStateV2::default);
            let prepared = state.attempts.lock().await.get(input.attempt_id).cloned();
            let Some(prepared) = prepared else {
                return Ok(ModelProviderPolicyDecision::Allow {
                    lease: Box::new(ContextCompilerNoopLeaseV2),
                });
            };
            if input.thread_id != prepared.thread_id
                || input.turn_id != prepared.turn_id
                || input.provider_id != prepared.provider_id
                || input.model != prepared.model
                || input.thread_store.level_id() != input.thread_id
                || input.turn_store.level_id() != input.turn_id
            {
                return Err(ModelProviderPolicyError::new(
                    "context_compiler_runtime_scope_mismatch",
                    "compiled context attempt does not match provider scope",
                ));
            }
            let expected_input = prepared.metadata.payload_digest.to_string();
            if input.ephemeral_input_sha256.map(ModelProviderSha256Digest::as_str)
                != Some(expected_input.as_str())
                || input.ephemeral_input_witness_sha256.is_none()
            {
                return Err(ModelProviderPolicyError::new(
                    "context_compiler_runtime_provider_input_mismatch",
                    "provider request does not contain the exact compiled context bytes and host witness",
                ));
            }
            let now = current_unix_ms().map_err(policy_error)?;
            if now >= prepared.metadata.deadline_ms {
                return Ok(ModelProviderPolicyDecision::Block {
                    reason_code: "context_compiler_runtime_attachment_expired".to_owned(),
                    message: "compiled context expired before provider dispatch".to_owned(),
                });
            }
            let intent = provider_intent(&input)?;
            let dispatch = ContextCompilerRuntimeDispatchV2::new(
                prepared.metadata,
                intent,
                now,
            )
            .map_err(policy_error)?;
            self.host
                .dispatch(dispatch.clone())
                .await
                .map_err(policy_error)?;
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(ContextCompilerAttemptLeaseV2 {
                    host: self.host.clone(),
                    dispatch,
                }),
            })
        })
    }
}

struct ContextCompilerNoopLeaseV2;

impl ModelProviderAttemptLease for ContextCompilerNoopLeaseV2 {
    fn finish(
        self: Box<Self>,
        _terminal: ApiTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(std::future::ready(Ok(())))
    }
}

struct ContextCompilerAttemptLeaseV2 {
    host: ContextCompilerRuntimeHostV2,
    dispatch: ContextCompilerRuntimeDispatchV2,
}

impl ModelProviderAttemptLease for ContextCompilerAttemptLeaseV2 {
    fn finish(
        self: Box<Self>,
        terminal: ApiTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            let observed_unix_ms = current_unix_ms().map_err(policy_error)?;
            let terminal = provider_terminal(terminal)?;
            let record = ContextCompilerRuntimeTerminalV2::new(
                self.dispatch,
                terminal,
                observed_unix_ms,
            )
            .map_err(policy_error)?;
            self.host.record(record).await.map_err(policy_error)
        })
    }
}

pub(crate) fn install_context_compiler_runtime_v2<C: Sync>(
    builder: &mut ExtensionRegistryBuilder<C>,
    host: ContextCompilerRuntimeHostV2,
) {
    let extension = Arc::new(ContextCompilerRuntimeExtensionV2 { host });
    builder.ephemeral_model_input_contributor(extension.clone());
    builder.model_provider_policy_contributor(extension);
}

fn provider_intent(
    input: &ModelProviderInvocationInput<'_>,
) -> Result<ProviderInvocationIntent, ModelProviderPolicyError> {
    if input.schema_version != MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION {
        return Err(ModelProviderPolicyError::new(
            "context_compiler_runtime_provider_schema_unsupported",
            "unsupported model-provider policy input schema version",
        ));
    }
    for (label, value) in [
        ("attempt id", input.attempt_id),
        ("request binding id", input.request_binding_id),
        ("thread id", input.thread_id),
        ("turn id", input.turn_id),
        ("provider id", input.provider_id),
        ("model", input.model),
    ] {
        if value.trim().is_empty() || value.len() > MAX_ID_BYTES {
            return Err(ModelProviderPolicyError::new(
                "context_compiler_runtime_provider_identity_invalid",
                format!("provider invocation requires a bounded non-empty {label}"),
            ));
        }
    }
    if input.ephemeral_input_sha256.is_some() != input.ephemeral_input_witness_sha256.is_some() {
        return Err(ModelProviderPolicyError::new(
            "context_compiler_runtime_ephemeral_input_incomplete",
            "context compiler provider input requires both content and witness digests",
        ));
    }
    let binding = ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: input.thread_id.to_owned(),
        turn_id: input.turn_id.to_owned(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(input.request_binding_id.as_bytes()),
        request_kind: match input.request_kind {
            ModelProviderRequestKind::Turn => ProviderRequestKind::Turn,
            ModelProviderRequestKind::Prewarm => ProviderRequestKind::Prewarm,
            ModelProviderRequestKind::Compaction => ProviderRequestKind::Compaction,
            ModelProviderRequestKind::Memory => ProviderRequestKind::Memory,
        },
        provider_id: input.provider_id.to_owned(),
        provider_config_sha256: contract_digest(input.provider_config_sha256.as_str())?,
        model: input.model.to_owned(),
        transport: match input.transport {
            ApiTransport::Http => ProviderTransport::Http,
            ApiTransport::WebSocket => ProviderTransport::WebSocket,
        },
        endpoint_sha256: contract_digest(input.endpoint_sha256.as_str())?,
        logical_request_sha256: contract_digest(input.logical_request_sha256.as_str())?,
        wire_semantic_sha256: contract_digest(input.wire_semantic_sha256.as_str())?,
        ephemeral_input_sha256: input
            .ephemeral_input_sha256
            .map(|digest| contract_digest(digest.as_str()))
            .transpose()?,
        ephemeral_input_witness_sha256: input
            .ephemeral_input_witness_sha256
            .map(|digest| contract_digest(digest.as_str()))
            .transpose()?,
        previous_response_id_sha256: input
            .previous_response_id_sha256
            .map(|digest| contract_digest(digest.as_str()))
            .transpose()?,
        generate: input.generate,
    };
    let intent = ProviderInvocationIntent::for_host_attempt_id(input.attempt_id, binding);
    intent.validate().map_err(|detail| {
        ModelProviderPolicyError::new(
            "context_compiler_runtime_provider_intent_invalid",
            detail,
        )
    })?;
    Ok(intent)
}

fn provider_terminal(terminal: ApiTerminal) -> Result<ProviderTerminal, ModelProviderPolicyError> {
    Ok(match terminal {
        ApiTerminal::Completed {
            response_id_sha256,
            response_items_sha256,
            token_usage_sha256,
            end_turn,
        } => ProviderTerminal::Completed {
            response_id_sha256: contract_digest(response_id_sha256.as_str())?,
            response_items_sha256: contract_digest(response_items_sha256.as_str())?,
            token_usage_sha256: contract_digest(token_usage_sha256.as_str())?,
            end_turn,
        },
        ApiTerminal::CompletedUnary { .. } => ProviderTerminal::Indeterminate {
            reason_code: "unexpected_unary_terminal_for_turn".to_owned(),
            partial_response_sha256: None,
        },
        ApiTerminal::Rejected { reason_code } => ProviderTerminal::Rejected {
            reason_code: stable_reason_code(reason_code)?,
        },
        ApiTerminal::NotDispatched { reason_code } => ProviderTerminal::NotDispatched {
            reason_code: stable_reason_code(reason_code)?,
        },
        ApiTerminal::Indeterminate {
            reason_code,
            partial_response_sha256,
        } => ProviderTerminal::Indeterminate {
            reason_code: stable_reason_code(reason_code)?,
            partial_response_sha256: partial_response_sha256
                .map(|digest| contract_digest(digest.as_str()))
                .transpose()?,
        },
    })
}

fn stable_reason_code(value: String) -> Result<String, ModelProviderPolicyError> {
    if (1..=128).contains(&value.len())
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-' | b'.')
        })
    {
        Ok(value)
    } else {
        Err(ModelProviderPolicyError::new(
            "context_compiler_runtime_reason_code_invalid",
            "provider terminal reason code is not a stable secret-free identifier",
        ))
    }
}

fn contract_digest(value: &str) -> Result<Sha256Digest, ModelProviderPolicyError> {
    Sha256Digest::parse(value).map_err(|detail| {
        ModelProviderPolicyError::new("context_compiler_runtime_digest_invalid", detail)
    })
}

fn current_unix_ms() -> Result<u64, ContextCompilerRuntimeHostErrorV2> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| {
            ContextCompilerRuntimeHostErrorV2::new(
                "context_compiler_runtime_clock_unavailable",
                "system clock is before the Unix epoch",
            )
        })?
        .as_millis();
    u64::try_from(millis).map_err(|_| {
        ContextCompilerRuntimeHostErrorV2::new(
            "context_compiler_runtime_clock_unavailable",
            "system clock does not fit the runtime timestamp",
        )
    })
}

fn policy_error(error: ContextCompilerRuntimeHostErrorV2) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(error.reason_code, error.detail)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[allow(dead_code)]
fn parse_digest(value: &str) -> Result<Digest32, ContextCompilerRuntimeHostErrorV2> {
    Digest32::from_str(value).map_err(|_| {
        ContextCompilerRuntimeHostErrorV2::new(
            "context_compiler_runtime_digest_invalid",
            "runtime digest is not canonical hexadecimal SHA-256",
        )
    })
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    use super::ContextCompilerRuntimeAttachmentV2;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn attachment_debug_is_redacted_and_source_binding_is_closed() {
        let payload = "sensitive developer policy".to_owned();
        let attachment = ContextCompilerRuntimeAttachmentV2::new(
            StableId::new("compilation-v2".to_owned())
                .unwrap_or_else(|error| panic!("id: {error:?}")),
            digest("attachment"),
            digest("preparation"),
            Digest32::of_bytes(payload.as_bytes()),
            digest("provider"),
            digest("model"),
            7,
            u64::MAX,
            payload,
        )
        .unwrap_or_else(|error| panic!("attachment: {error}"));
        let rendered = format!("{attachment:?}");
        assert!(!rendered.contains("sensitive developer policy"));
        let (metadata, _) = attachment.into_parts();
        metadata.validate().unwrap_or_else(|error| panic!("metadata: {error}"));
    }
}
