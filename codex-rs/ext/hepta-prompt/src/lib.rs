//! Host-bound prompt delivery bridge for the real Codex provider spine.
//!
//! The host supplies an already exercise-bound prompt attachment for one turn.
//! This module contributes only developer-policy realizations to Codex prompt
//! assembly, then observes the exact physical provider attempt through the
//! existing ModelProviderPolicyContributor lease. It never opens the prompt
//! registry itself, never selects a factor, and never mints model/provider
//! authority.

#![forbid(unsafe_code)]

mod exact_body;

pub use exact_body::PromptRuntimeExactAttemptV2;
use exact_body::PromptRuntimeExactBodyObserver;

use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_api::EncodedRequestBodyObserver;
use codex_api::EncodedRequestBodyObserverAttachment;
use codex_extension_api::ContentItemKind;
use codex_extension_api::ContextContributor;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;
use codex_extension_api::PromptFragment;
use codex_extension_api::TurnContextContributionInput;
use codex_hepta_types::Digest32;
use codex_hepta_types::PromptDeliveryObservationV1;
use codex_hepta_types::PromptDeliveryRejectReasonV1;
use codex_hepta_types::StableId;
use tokio::sync::Mutex;

const ATTACHMENT_DOMAIN: &[u8] = b"hepta.runtime-codex.prompt-attachment.v1";
const MAX_DEVELOPER_FRAGMENTS: usize = 128;
const MAX_DEVELOPER_FRAGMENT_BYTES: usize = 16 * 1024 * 1024;
const MAX_DEVELOPER_TOTAL_BYTES: usize = 16 * 1024 * 1024;
const MAX_MODEL_BYTES: usize = 256;

/// One exact trusted developer-policy fragment prepared by the prompt owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeDeveloperFragmentV1 {
    pub text: String,
    pub content_digest: Digest32,
}

impl PromptRuntimeDeveloperFragmentV1 {
    pub fn new(text: impl Into<String>) -> Result<Self, PromptRuntimeError> {
        let text = text.into();
        let value = Self {
            content_digest: Digest32::of_bytes(text.as_bytes()),
            text,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        if self.text.is_empty() || self.text.len() > MAX_DEVELOPER_FRAGMENT_BYTES {
            return Err(PromptRuntimeError::InvalidAttachment(
                "developer fragment bounds",
            ));
        }
        if self.content_digest.is_zero()
            || self.content_digest != Digest32::of_bytes(self.text.as_bytes())
        {
            return Err(PromptRuntimeError::InvalidAttachment(
                "developer fragment digest",
            ));
        }
        Ok(())
    }
}

/// Exercise-bound context attachment handed to runtime.codex by its owning host.
///
/// This first runtime profile intentionally accepts only DeveloperInstruction
/// realizations. Other prompt roles must remain fail-closed until Codex exposes
/// an exact typed slot for them.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeAttachmentV1 {
    pub compilation_id: StableId,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub model: String,
    pub deadline_ms: u64,
    pub developer_fragments: Vec<PromptRuntimeDeveloperFragmentV1>,
    pub source_binding_digest: Digest32,
}

impl PromptRuntimeAttachmentV1 {
    pub fn new(
        compilation_id: StableId,
        context_attachment_digest: Digest32,
        context_payload_digest: Digest32,
        model: impl Into<String>,
        deadline_ms: u64,
        developer_fragments: Vec<PromptRuntimeDeveloperFragmentV1>,
    ) -> Result<Self, PromptRuntimeError> {
        let mut value = Self {
            compilation_id,
            context_attachment_digest,
            context_payload_digest,
            model: model.into(),
            deadline_ms,
            developer_fragments,
            source_binding_digest: Digest32::ZERO,
        };
        value.source_binding_digest = value.compute_binding_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        if self.context_attachment_digest.is_zero()
            || self.context_payload_digest.is_zero()
            || self.source_binding_digest.is_zero()
        {
            return Err(PromptRuntimeError::InvalidAttachment("empty digest"));
        }
        if self.model.is_empty()
            || self.model.len() > MAX_MODEL_BYTES
            || self.model.as_bytes().contains(&0)
            || self.deadline_ms == 0
            || self.developer_fragments.is_empty()
            || self.developer_fragments.len() > MAX_DEVELOPER_FRAGMENTS
        {
            return Err(PromptRuntimeError::InvalidAttachment("attachment bounds"));
        }
        let mut total_bytes = 0usize;
        for fragment in &self.developer_fragments {
            fragment.validate()?;
            total_bytes = total_bytes
                .checked_add(fragment.text.len())
                .ok_or(PromptRuntimeError::InvalidAttachment("attachment size"))?;
        }
        if total_bytes > MAX_DEVELOPER_TOTAL_BYTES {
            return Err(PromptRuntimeError::InvalidAttachment("attachment size"));
        }
        if self.source_binding_digest != self.compute_binding_digest() {
            return Err(PromptRuntimeError::InvalidAttachment("binding digest"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_binding_digest(&self) -> Digest32 {
        let mut bytes = ATTACHMENT_DOMAIN.to_vec();
        push_id(&mut bytes, &self.compilation_id);
        bytes.extend_from_slice(self.context_attachment_digest.as_array());
        bytes.extend_from_slice(self.context_payload_digest.as_array());
        push_text(&mut bytes, &self.model);
        bytes.extend_from_slice(&self.deadline_ms.to_be_bytes());
        bytes.extend_from_slice(
            &u32::try_from(self.developer_fragments.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for fragment in &self.developer_fragments {
            bytes.extend_from_slice(fragment.content_digest.as_array());
            bytes.extend_from_slice(
                &u64::try_from(fragment.text.len())
                    .unwrap_or(u64::MAX)
                    .to_be_bytes(),
            );
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Turn identity supplied to the embedding-owned prompt attachment factory.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimePrepareRequest {
    pub thread_id: String,
    pub turn_id: String,
    pub model_context_window: Option<i64>,
}

/// Stable host callback error. Details must not contain raw prompt/provider data.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeHostError {
    reason_code: String,
    detail: String,
}

impl PromptRuntimeHostError {
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

impl fmt::Display for PromptRuntimeHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.reason_code, self.detail)
    }
}

impl std::error::Error for PromptRuntimeHostError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeRequestKindV2 {
    Turn,
    Prewarm,
    Compaction,
    Memory,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeTransportV2 {
    Http,
    WebSocket,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptRuntimeProviderTerminalV2 {
    Completed {
        response_id_digest: Digest32,
        response_items_digest: Digest32,
        token_usage_digest: Digest32,
        end_turn: Option<bool>,
    },
    CompletedUnary {
        response_items_digest: Digest32,
    },
    Rejected {
        reason_code: String,
    },
    NotDispatched {
        reason_code: String,
    },
    Indeterminate {
        reason_code: String,
        partial_response_digest: Option<Digest32>,
    },
}

/// Exact terminal material retained before the compatibility V1 projection
/// discards provider response digests.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeFinalTerminalV2 {
    pub attachment: PromptRuntimeAttachmentV1,
    pub attempt: PromptRuntimeExactAttemptV2,
    pub terminal: PromptRuntimeProviderTerminalV2,
    pub observed_unix_ms: u64,
}

/// Exact canonical provider request observed after JSON encoding and before
/// compression/signing. The callback must complete successfully before Core
/// crosses the physical transport boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeFinalRequestV2 {
    pub attachment: PromptRuntimeAttachmentV1,
    pub attempt: PromptRuntimeExactAttemptV2,
    pub canonical_request: Vec<u8>,
}

pub type PromptRuntimePrepareFuture = Pin<
    Box<
        dyn Future<Output = Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError>>
            + Send
            + 'static,
    >,
>;
pub type PromptRuntimeDispatchFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;
pub type PromptRuntimeRecordFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;
pub type PromptRuntimeFinalRequestFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;
pub type PromptRuntimeFinalTerminalFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;

type PromptRuntimePrepareFn =
    dyn Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static;
type PromptRuntimeDispatchFn =
    dyn Fn(PromptRuntimeDispatchRecordV1) -> PromptRuntimeDispatchFuture + Send + Sync + 'static;
type PromptRuntimeRecordFn =
    dyn Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static;
type PromptRuntimeFinalRequestFn =
    dyn Fn(PromptRuntimeFinalRequestV2) -> PromptRuntimeFinalRequestFuture + Send + Sync + 'static;
type PromptRuntimeFinalTerminalFn = dyn Fn(PromptRuntimeFinalTerminalV2) -> PromptRuntimeFinalTerminalFuture
    + Send
    + Sync
    + 'static;

/// Host capability used by App Server. Missing capability means prompt.runtime
/// is not installed and ordinary Codex behavior is unchanged.
#[derive(Clone)]
pub struct PromptRuntimeHost {
    capability_id: Arc<str>,
    prepare: Arc<PromptRuntimePrepareFn>,
    dispatch: Arc<PromptRuntimeDispatchFn>,
    record: Arc<PromptRuntimeRecordFn>,
    final_request: Option<Arc<PromptRuntimeFinalRequestFn>>,
    final_terminal: Option<Arc<PromptRuntimeFinalTerminalFn>>,
}

impl PromptRuntimeHost {
    pub fn new<P, D, R>(
        capability_id: impl Into<String>,
        prepare: P,
        dispatch: D,
        record: R,
    ) -> Result<Self, PromptRuntimeError>
    where
        P: Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static,
        D: Fn(PromptRuntimeDispatchRecordV1) -> PromptRuntimeDispatchFuture + Send + Sync + 'static,
        R: Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static,
    {
        let capability_id = capability_id.into();
        StableId::new(capability_id.clone())
            .map_err(|_| PromptRuntimeError::InvalidAttachment("capability id"))?;
        Ok(Self {
            capability_id: Arc::from(capability_id),
            prepare: Arc::new(prepare),
            dispatch: Arc::new(dispatch),
            record: Arc::new(record),
            final_request: None,
            final_terminal: None,
        })
    }

    #[must_use]
    pub fn with_final_request_observer<F>(mut self, observer: F) -> Self
    where
        F: Fn(PromptRuntimeFinalRequestV2) -> PromptRuntimeFinalRequestFuture
            + Send
            + Sync
            + 'static,
    {
        self.final_request = Some(Arc::new(observer));
        self
    }

    #[must_use]
    pub fn with_final_terminal_observer<F>(mut self, observer: F) -> Self
    where
        F: Fn(PromptRuntimeFinalTerminalV2) -> PromptRuntimeFinalTerminalFuture
            + Send
            + Sync
            + 'static,
    {
        self.final_terminal = Some(Arc::new(observer));
        self
    }

    #[must_use]
    fn has_final_request_observer(&self) -> bool {
        self.final_request.is_some()
    }

    #[must_use]
    fn has_final_terminal_observer(&self) -> bool {
        self.final_terminal.is_some()
    }

    pub(crate) async fn observe_final_request(
        &self,
        request: PromptRuntimeFinalRequestV2,
    ) -> Result<(), PromptRuntimeHostError> {
        let observer = self.final_request.as_ref().ok_or_else(|| {
            PromptRuntimeHostError::new(
                "prompt_runtime_exact_observer_missing",
                "exact final request observer is not installed",
            )
        })?;
        observer(request).await
    }

    async fn observe_final_terminal(
        &self,
        terminal: PromptRuntimeFinalTerminalV2,
    ) -> Result<(), PromptRuntimeHostError> {
        let observer = self.final_terminal.as_ref().ok_or_else(|| {
            PromptRuntimeHostError::new(
                "prompt_runtime_exact_terminal_observer_missing",
                "exact terminal observer is not installed",
            )
        })?;
        observer(terminal).await
    }

    async fn prepare(
        &self,
        request: PromptRuntimePrepareRequest,
    ) -> Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError> {
        (self.prepare)(request).await
    }

    async fn dispatch(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<(), PromptRuntimeHostError> {
        (self.dispatch)(record).await
    }

    async fn record(
        &self,
        record: PromptRuntimeTerminalRecordV1,
    ) -> Result<(), PromptRuntimeHostError> {
        (self.record)(record).await
    }
}

impl fmt::Debug for PromptRuntimeHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRuntimeHost")
            .field("capability_id", &self.capability_id)
            .field("exact_final_request", &self.final_request.is_some())
            .field("exact_final_terminal", &self.final_terminal.is_some())
            .finish_non_exhaustive()
    }
}

impl PartialEq for PromptRuntimeHost {
    fn eq(&self, other: &Self) -> bool {
        self.capability_id == other.capability_id
            && Arc::ptr_eq(&self.prepare, &other.prepare)
            && Arc::ptr_eq(&self.dispatch, &other.dispatch)
            && Arc::ptr_eq(&self.record, &other.record)
            && match (&self.final_request, &other.final_request) {
                (None, None) => true,
                (Some(left), Some(right)) => Arc::ptr_eq(left, right),
                _ => false,
            }
            && match (&self.final_terminal, &other.final_terminal) {
                (None, None) => true,
                (Some(left), Some(right)) => Arc::ptr_eq(left, right),
                _ => false,
            }
    }
}

impl Eq for PromptRuntimeHost {}

/// Durable pre-send claim for one physical provider attempt.
///
/// The owning host records this before the provider effect boundary is crossed.
/// A crash after this claim but before a terminal record is therefore
/// reconciled as unknown/indeterminate and must never authorize blind retry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeDispatchRecordV1 {
    pub compilation_id: StableId,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub source_binding_digest: Digest32,
    pub thread_id: String,
    pub turn_id: String,
    pub attempt_id: String,
    pub request_binding_id: String,
    pub provider_request_digest: Digest32,
    pub dispatched_unix_ms: u64,
}

impl PromptRuntimeDispatchRecordV1 {
    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        if self.context_attachment_digest.is_zero()
            || self.context_payload_digest.is_zero()
            || self.source_binding_digest.is_zero()
            || self.provider_request_digest.is_zero()
            || self.thread_id.is_empty()
            || self.thread_id.len() > 256
            || self.turn_id.is_empty()
            || self.turn_id.len() > 256
            || self.attempt_id.is_empty()
            || self.attempt_id.len() > 256
            || self.request_binding_id.is_empty()
            || self.request_binding_id.len() > 256
            || self.dispatched_unix_ms == 0
        {
            return Err(PromptRuntimeError::InvalidProviderBinding);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeTerminalOutcomeV1 {
    Delivered,
    Rejected,
    NotDispatched,
    Indeterminate,
}

/// Terminal evidence linking one source-bound prompt attachment to the exact
/// physical provider request digest observed by Core.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeTerminalRecordV1 {
    pub compilation_id: StableId,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub source_binding_digest: Digest32,
    pub thread_id: String,
    pub turn_id: String,
    pub attempt_id: String,
    pub request_binding_id: String,
    pub provider_request_digest: Digest32,
    pub outcome: PromptRuntimeTerminalOutcomeV1,
    pub end_turn: Option<bool>,
    pub terminal_reason_code: Option<String>,
    pub delivery_observation: Option<PromptDeliveryObservationV1>,
    pub observed_unix_ms: u64,
}

impl PromptRuntimeTerminalRecordV1 {
    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        if self.context_attachment_digest.is_zero()
            || self.context_payload_digest.is_zero()
            || self.source_binding_digest.is_zero()
            || self.provider_request_digest.is_zero()
            || self.thread_id.is_empty()
            || self.thread_id.len() > 256
            || self.turn_id.is_empty()
            || self.turn_id.len() > 256
            || self.attempt_id.is_empty()
            || self.attempt_id.len() > 256
            || self.request_binding_id.is_empty()
            || self.request_binding_id.len() > 256
            || self.observed_unix_ms == 0
            || self.terminal_reason_code.as_ref().is_some_and(|reason| {
                reason.is_empty() || reason.len() > 256 || reason.as_bytes().contains(&0)
            })
        {
            return Err(PromptRuntimeError::InvalidTerminalRecord);
        }
        match self.outcome {
            PromptRuntimeTerminalOutcomeV1::Delivered => {
                let observation = self
                    .delivery_observation
                    .as_ref()
                    .ok_or(PromptRuntimeError::InvalidTerminalRecord)?;
                if !observation.delivered || self.terminal_reason_code.is_some() {
                    return Err(PromptRuntimeError::InvalidTerminalRecord);
                }
                validate_observation_binding(self, observation)?;
            }
            PromptRuntimeTerminalOutcomeV1::Rejected => {
                let observation = self
                    .delivery_observation
                    .as_ref()
                    .ok_or(PromptRuntimeError::InvalidTerminalRecord)?;
                if observation.delivered
                    || self.terminal_reason_code.is_none()
                    || self.end_turn.is_some()
                {
                    return Err(PromptRuntimeError::InvalidTerminalRecord);
                }
                validate_observation_binding(self, observation)?;
            }
            PromptRuntimeTerminalOutcomeV1::NotDispatched
            | PromptRuntimeTerminalOutcomeV1::Indeterminate => {
                if self.delivery_observation.is_some()
                    || self.terminal_reason_code.is_none()
                    || self.end_turn.is_some()
                {
                    return Err(PromptRuntimeError::InvalidTerminalRecord);
                }
            }
        }
        Ok(())
    }
}

fn validate_observation_binding(
    record: &PromptRuntimeTerminalRecordV1,
    observation: &PromptDeliveryObservationV1,
) -> Result<(), PromptRuntimeError> {
    observation
        .validate()
        .map_err(|_| PromptRuntimeError::InvalidTerminalRecord)?;
    if observation.compilation_id != record.compilation_id
        || observation.provider_request_digest != record.provider_request_digest
    {
        return Err(PromptRuntimeError::InvalidTerminalRecord);
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeError {
    InvalidAttachment(&'static str),
    InvalidProviderBinding,
    InvalidTerminalRecord,
    ClockUnavailable,
}

impl fmt::Display for PromptRuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PromptRuntimeError {}

#[derive(Clone)]
enum ResolvedAttachment {
    None,
    Ready(PromptRuntimeAttachmentV1),
    Failed(PromptRuntimeHostError),
}

#[derive(Default)]
struct PromptRuntimeTurnState {
    resolved: Mutex<Option<ResolvedAttachment>>,
    exact_observer: OnceLock<Arc<PromptRuntimeExactBodyObserver>>,
    observer_conflict: AtomicBool,
    injected: AtomicBool,
}

#[derive(Clone)]
struct PromptRuntimeExtension {
    host: PromptRuntimeHost,
}

impl PromptRuntimeExtension {
    async fn resolve(
        &self,
        thread_id: String,
        turn_id: String,
        model_context_window: Option<i64>,
        turn_store: &ExtensionData,
    ) -> ResolvedAttachment {
        let state = turn_store.get_or_init(PromptRuntimeTurnState::default);
        let mut resolved = state.resolved.lock().await;
        if let Some(value) = resolved.as_ref() {
            return value.clone();
        }
        let value = match self
            .host
            .prepare(PromptRuntimePrepareRequest {
                thread_id,
                turn_id,
                model_context_window,
            })
            .await
        {
            Ok(Some(attachment)) => match attachment.validate() {
                Ok(()) => ResolvedAttachment::Ready(attachment),
                Err(error) => ResolvedAttachment::Failed(PromptRuntimeHostError::new(
                    "prompt_runtime_attachment_invalid",
                    error.to_string(),
                )),
            },
            Ok(None) => ResolvedAttachment::None,
            Err(error) => ResolvedAttachment::Failed(error),
        };
        *resolved = Some(value.clone());
        value
    }
}

impl ContextContributor for PromptRuntimeExtension {
    fn contribute_turn_context<'a>(
        &'a self,
        input: TurnContextContributionInput<'a>,
    ) -> ExtensionFuture<'a, Vec<PromptFragment>> {
        Box::pin(async move {
            let resolved = self
                .resolve(
                    input.thread_id.to_string(),
                    input.turn_id.to_owned(),
                    input.model_context_window,
                    input.turn_store,
                )
                .await;
            let ResolvedAttachment::Ready(attachment) = resolved else {
                return Vec::new();
            };
            let state = input
                .turn_store
                .get_or_init(PromptRuntimeTurnState::default);
            if self.host.has_final_request_observer() {
                let observer = Arc::clone(state.exact_observer.get_or_init(|| {
                    Arc::new(PromptRuntimeExactBodyObserver::new(
                        self.host.clone(),
                        attachment.clone(),
                    ))
                }));
                let observer_trait: Arc<dyn EncodedRequestBodyObserver> = observer;
                let compatible_existing = input
                    .turn_store
                    .get::<EncodedRequestBodyObserverAttachment>()
                    .is_some_and(|existing| Arc::ptr_eq(&existing.observer(), &observer_trait));
                if !compatible_existing {
                    let inserted = input.turn_store.insert_if(
                        EncodedRequestBodyObserverAttachment::new(Arc::clone(&observer_trait)),
                        |existing| existing.is_none(),
                    );
                    if !inserted {
                        let compatible_after_race = input
                            .turn_store
                            .get::<EncodedRequestBodyObserverAttachment>()
                            .is_some_and(|existing| {
                                Arc::ptr_eq(&existing.observer(), &observer_trait)
                            });
                        if !compatible_after_race {
                            state.observer_conflict.store(true, Ordering::Release);
                            return Vec::new();
                        }
                    }
                }
            }
            state.injected.store(true, Ordering::Release);
            attachment
                .developer_fragments
                .iter()
                .enumerate()
                .map(|(index, fragment)| {
                    PromptFragment::developer_policy(
                        fragment.text.clone(),
                        ContentItemKind(format!(
                            "hepta.prompt_registry.developer_instruction.{index}"
                        )),
                    )
                })
                .collect()
        })
    }
}

impl ModelProviderPolicyContributor for PromptRuntimeExtension {
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
                    lease: Box::new(PromptRuntimeNoopLease),
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
            let attachment = match resolved {
                ResolvedAttachment::None => {
                    return Ok(ModelProviderPolicyDecision::Allow {
                        lease: Box::new(PromptRuntimeNoopLease),
                    });
                }
                ResolvedAttachment::Failed(error) => {
                    return Err(ModelProviderPolicyError::new(
                        error.reason_code().to_owned(),
                        error.detail().to_owned(),
                    ));
                }
                ResolvedAttachment::Ready(attachment) => attachment,
            };
            let state = input
                .turn_store
                .get_or_init(PromptRuntimeTurnState::default);
            if state.observer_conflict.load(Ordering::Acquire) {
                return Ok(ModelProviderPolicyDecision::Block {
                    reason_code: "prompt_runtime_exact_observer_conflict".to_owned(),
                    message: "another exact request observer already owns this turn".to_owned(),
                });
            }
            if !state.injected.load(Ordering::Acquire) {
                return Ok(ModelProviderPolicyDecision::Block {
                    reason_code: "prompt_runtime_attachment_not_injected".to_owned(),
                    message: "a source-bound prompt attachment existed but was not assembled into the turn context"
                        .to_owned(),
                });
            }
            if input.thread_store.level_id() != input.thread_id
                || input.turn_store.level_id() != input.turn_id
                || input.model != attachment.model
            {
                return Err(ModelProviderPolicyError::new(
                    "prompt_runtime_scope_mismatch",
                    "prompt attachment does not match the physical provider attempt",
                ));
            }
            let dispatch_unix_ms = current_unix_ms().map_err(runtime_policy_error)?;
            if dispatch_unix_ms >= attachment.deadline_ms {
                return Ok(ModelProviderPolicyDecision::Block {
                    reason_code: "prompt_runtime_attachment_expired".to_owned(),
                    message: "prompt attachment expired before physical provider send".to_owned(),
                });
            }
            let provider_request_digest = Digest32::from_str(input.wire_semantic_sha256.as_str())
                .map_err(|_| {
                ModelProviderPolicyError::new(
                    "prompt_runtime_provider_digest_invalid",
                    "host provider request digest is invalid",
                )
            })?;
            parse_stable_id(input.attempt_id, "attempt id")?;
            parse_stable_id(input.thread_id, "thread id")?;
            let exact_observer = if self.host.has_final_request_observer() {
                if input.transport != ModelProviderTransport::Http {
                    return Ok(ModelProviderPolicyDecision::Block {
                        reason_code: "prompt_runtime_exact_body_requires_http".to_owned(),
                        message: "exact final request proof is defined at the canonical HTTP body boundary"
                            .to_owned(),
                    });
                }
                let observer = state.exact_observer.get().cloned().ok_or_else(|| {
                    ModelProviderPolicyError::new(
                        "prompt_runtime_exact_observer_missing",
                        "context assembly did not install the exact body observer",
                    )
                })?;
                let request_kind = match input.request_kind {
                    ModelProviderRequestKind::Turn => PromptRuntimeRequestKindV2::Turn,
                    ModelProviderRequestKind::Prewarm => PromptRuntimeRequestKindV2::Prewarm,
                    ModelProviderRequestKind::Compaction => PromptRuntimeRequestKindV2::Compaction,
                    ModelProviderRequestKind::Memory => PromptRuntimeRequestKindV2::Memory,
                };
                let transport = match input.transport {
                    ModelProviderTransport::Http => PromptRuntimeTransportV2::Http,
                    ModelProviderTransport::WebSocket => PromptRuntimeTransportV2::WebSocket,
                };
                let attempt = PromptRuntimeExactAttemptV2 {
                    thread_id: input.thread_id.to_owned(),
                    turn_id: input.turn_id.to_owned(),
                    attempt_id: input.attempt_id.to_owned(),
                    request_binding_id: input.request_binding_id.to_owned(),
                    request_kind,
                    provider_id: input.provider_id.to_owned(),
                    provider_config_digest: parse_policy_digest(
                        input.provider_config_sha256,
                        "provider config",
                    )?,
                    model: input.model.to_owned(),
                    transport,
                    endpoint_digest: parse_policy_digest(input.endpoint_sha256, "endpoint")?,
                    logical_request_digest: parse_policy_digest(
                        input.logical_request_sha256,
                        "logical request",
                    )?,
                    provider_wire_semantic_digest: provider_request_digest,
                    ephemeral_input_digest: input
                        .ephemeral_input_sha256
                        .map(|digest| parse_policy_digest(digest, "ephemeral input"))
                        .transpose()?,
                    ephemeral_input_witness_digest: input
                        .ephemeral_input_witness_sha256
                        .map(|digest| parse_policy_digest(digest, "ephemeral input witness"))
                        .transpose()?,
                    previous_response_id_digest: input
                        .previous_response_id_sha256
                        .map(|digest| parse_policy_digest(digest, "previous response"))
                        .transpose()?,
                    generate: input.generate,
                };
                observer.bind_attempt(attempt.clone()).map_err(|error| {
                    ModelProviderPolicyError::new(
                        error.reason_code().to_owned(),
                        error.detail().to_owned(),
                    )
                })?;
                Some((observer, attempt))
            } else {
                None
            };
            let dispatch_record = PromptRuntimeDispatchRecordV1 {
                compilation_id: attachment.compilation_id.clone(),
                context_attachment_digest: attachment.context_attachment_digest,
                context_payload_digest: attachment.context_payload_digest,
                source_binding_digest: attachment.source_binding_digest,
                thread_id: input.thread_id.to_owned(),
                turn_id: input.turn_id.to_owned(),
                attempt_id: input.attempt_id.to_owned(),
                request_binding_id: input.request_binding_id.to_owned(),
                provider_request_digest,
                dispatched_unix_ms: dispatch_unix_ms,
            };
            dispatch_record.validate().map_err(runtime_policy_error)?;
            if let Err(error) = self.host.dispatch(dispatch_record).await {
                if let Some((observer, attempt)) = &exact_observer {
                    observer.cancel_attempt(attempt);
                }
                return Err(ModelProviderPolicyError::new(
                    error.reason_code().to_owned(),
                    error.detail().to_owned(),
                ));
            }
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(PromptRuntimeAttemptLease {
                    host: self.host.clone(),
                    attachment,
                    thread_id: input.thread_id.to_owned(),
                    turn_id: input.turn_id.to_owned(),
                    attempt_id: input.attempt_id.to_owned(),
                    request_binding_id: input.request_binding_id.to_owned(),
                    provider_request_digest,
                    dispatch_unix_ms,
                    exact_observer,
                }),
            })
        })
    }
}

struct PromptRuntimeNoopLease;

impl ModelProviderAttemptLease for PromptRuntimeNoopLease {
    fn finish(
        self: Box<Self>,
        _terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(std::future::ready(Ok(())))
    }
}

struct PromptRuntimeAttemptLease {
    host: PromptRuntimeHost,
    attachment: PromptRuntimeAttachmentV1,
    thread_id: String,
    turn_id: String,
    attempt_id: String,
    request_binding_id: String,
    provider_request_digest: Digest32,
    dispatch_unix_ms: u64,
    exact_observer: Option<(
        Arc<PromptRuntimeExactBodyObserver>,
        PromptRuntimeExactAttemptV2,
    )>,
}

impl ModelProviderAttemptLease for PromptRuntimeAttemptLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            let observed_unix_ms = current_unix_ms().map_err(runtime_policy_error)?;
            let exact_terminal = self
                .exact_observer
                .as_ref()
                .map(|(_, attempt)| {
                    map_exact_terminal(&terminal).map(|terminal| PromptRuntimeFinalTerminalV2 {
                        attachment: self.attachment.clone(),
                        attempt: attempt.clone(),
                        terminal,
                        observed_unix_ms,
                    })
                })
                .transpose()
                .map_err(runtime_policy_error)?;
            let (outcome, terminal_reason_code, end_turn, delivery_observation) =
                self.map_terminal(terminal).map_err(runtime_policy_error)?;
            let record = PromptRuntimeTerminalRecordV1 {
                compilation_id: self.attachment.compilation_id.clone(),
                context_attachment_digest: self.attachment.context_attachment_digest,
                context_payload_digest: self.attachment.context_payload_digest,
                source_binding_digest: self.attachment.source_binding_digest,
                thread_id: self.thread_id,
                turn_id: self.turn_id,
                attempt_id: self.attempt_id,
                request_binding_id: self.request_binding_id,
                provider_request_digest: self.provider_request_digest,
                outcome,
                end_turn,
                terminal_reason_code,
                delivery_observation,
                observed_unix_ms,
            };
            record.validate().map_err(runtime_policy_error)?;
            if let Some(exact_terminal) = exact_terminal {
                if !self.host.has_final_terminal_observer() {
                    return Err(ModelProviderPolicyError::new(
                        "prompt_runtime_exact_terminal_observer_missing",
                        "exact request proof was active without an exact terminal owner",
                    ));
                }
                self.host
                    .observe_final_terminal(exact_terminal)
                    .await
                    .map_err(|error| {
                        ModelProviderPolicyError::new(
                            error.reason_code().to_owned(),
                            error.detail().to_owned(),
                        )
                    })?;
            }
            self.host.record(record).await.map_err(|error| {
                ModelProviderPolicyError::new(
                    error.reason_code().to_owned(),
                    error.detail().to_owned(),
                )
            })?;
            if let Some((observer, attempt)) = &self.exact_observer {
                observer
                    .record_terminal(attempt, outcome)
                    .map_err(|reason| {
                        ModelProviderPolicyError::new(
                            reason,
                            "exact terminal requires reconciliation",
                        )
                    })?;
            }
            Ok(())
        })
    }
}

impl PromptRuntimeAttemptLease {
    // This lease is created by the physical ModelProviderPolicyContributor,
    // not by an App Server client DTO. The sealed terminal callback supplies
    // the observation; the stored attempt owns its exact request digest.
    fn delivery_observation(
        &self,
        delivered: bool,
        rejected_reason: Option<PromptDeliveryRejectReasonV1>,
    ) -> Result<PromptDeliveryObservationV1, PromptRuntimeError> {
        if self.dispatch_unix_ms >= self.attachment.deadline_ms {
            return Err(PromptRuntimeError::InvalidTerminalRecord);
        }
        let observation = PromptDeliveryObservationV1 {
            compilation_id: self.attachment.compilation_id.clone(),
            provider_request_digest: self.provider_request_digest,
            delivered,
            rejected_reason,
            observed_token_positions: None,
            truncation_observed: false,
        };
        observation
            .validate()
            .map_err(|_| PromptRuntimeError::InvalidTerminalRecord)?;
        Ok(observation)
    }

    fn map_terminal(
        &self,
        terminal: ModelProviderTerminal,
    ) -> Result<
        (
            PromptRuntimeTerminalOutcomeV1,
            Option<String>,
            Option<bool>,
            Option<PromptDeliveryObservationV1>,
        ),
        PromptRuntimeError,
    > {
        match terminal {
            ModelProviderTerminal::Completed { end_turn, .. } => {
                let observation = self.delivery_observation(true, None)?;
                Ok((
                    PromptRuntimeTerminalOutcomeV1::Delivered,
                    None,
                    end_turn,
                    Some(observation),
                ))
            }
            ModelProviderTerminal::Rejected { reason_code } => {
                let rejection_reason = rejection_reason(&reason_code)?;
                let observation = self.delivery_observation(false, Some(rejection_reason))?;
                Ok((
                    PromptRuntimeTerminalOutcomeV1::Rejected,
                    Some(reason_code),
                    None,
                    Some(observation),
                ))
            }
            ModelProviderTerminal::NotDispatched { reason_code } => Ok((
                PromptRuntimeTerminalOutcomeV1::NotDispatched,
                Some(reason_code),
                None,
                None,
            )),
            ModelProviderTerminal::Indeterminate { reason_code, .. } => Ok((
                PromptRuntimeTerminalOutcomeV1::Indeterminate,
                Some(reason_code),
                None,
                None,
            )),
            ModelProviderTerminal::CompletedUnary { .. } => Ok((
                PromptRuntimeTerminalOutcomeV1::Indeterminate,
                Some("unexpected_unary_terminal_for_turn".to_owned()),
                None,
                None,
            )),
        }
    }
}

pub fn install_prompt_runtime<C: Sync>(
    builder: &mut ExtensionRegistryBuilder<C>,
    host: PromptRuntimeHost,
) {
    let extension = Arc::new(PromptRuntimeExtension { host });
    builder.prompt_contributor(extension.clone());
    builder.model_provider_policy_contributor(extension);
}

fn parse_policy_digest(
    value: &codex_extension_api::ModelProviderSha256Digest,
    field: &'static str,
) -> Result<Digest32, ModelProviderPolicyError> {
    Digest32::from_str(value.as_str()).map_err(|_| {
        ModelProviderPolicyError::new(
            "prompt_runtime_provider_digest_invalid",
            format!("{field} digest is invalid"),
        )
    })
}

fn map_exact_terminal(
    terminal: &ModelProviderTerminal,
) -> Result<PromptRuntimeProviderTerminalV2, PromptRuntimeError> {
    let parse = |digest: &codex_extension_api::ModelProviderSha256Digest| {
        Digest32::from_str(digest.as_str()).map_err(|_| PromptRuntimeError::InvalidTerminalRecord)
    };
    match terminal {
        ModelProviderTerminal::Completed {
            response_id_sha256,
            response_items_sha256,
            token_usage_sha256,
            end_turn,
        } => Ok(PromptRuntimeProviderTerminalV2::Completed {
            response_id_digest: parse(response_id_sha256)?,
            response_items_digest: parse(response_items_sha256)?,
            token_usage_digest: parse(token_usage_sha256)?,
            end_turn: *end_turn,
        }),
        ModelProviderTerminal::CompletedUnary {
            response_items_sha256,
        } => Ok(PromptRuntimeProviderTerminalV2::CompletedUnary {
            response_items_digest: parse(response_items_sha256)?,
        }),
        ModelProviderTerminal::Rejected { reason_code } => {
            Ok(PromptRuntimeProviderTerminalV2::Rejected {
                reason_code: reason_code.clone(),
            })
        }
        ModelProviderTerminal::NotDispatched { reason_code } => {
            Ok(PromptRuntimeProviderTerminalV2::NotDispatched {
                reason_code: reason_code.clone(),
            })
        }
        ModelProviderTerminal::Indeterminate {
            reason_code,
            partial_response_sha256,
        } => Ok(PromptRuntimeProviderTerminalV2::Indeterminate {
            reason_code: reason_code.clone(),
            partial_response_digest: partial_response_sha256.as_ref().map(parse).transpose()?,
        }),
    }
}

fn rejection_reason(reason_code: &str) -> Result<PromptDeliveryRejectReasonV1, PromptRuntimeError> {
    let id = match StableId::new(reason_code.to_owned()) {
        Ok(value) => value,
        Err(_) => StableId::new(Digest32::of_bytes(reason_code.as_bytes()).to_string())
            .map_err(|_| PromptRuntimeError::InvalidTerminalRecord)?,
    };
    PromptDeliveryRejectReasonV1::new(id).map_err(|_| PromptRuntimeError::InvalidTerminalRecord)
}

fn parse_stable_id(value: &str, field: &'static str) -> Result<StableId, ModelProviderPolicyError> {
    StableId::new(value.to_owned()).map_err(|_| {
        ModelProviderPolicyError::new(
            "prompt_runtime_scope_identity_invalid",
            format!("{field} is not a stable bounded identity"),
        )
    })
}

fn current_unix_ms() -> Result<u64, PromptRuntimeError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| PromptRuntimeError::ClockUnavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| PromptRuntimeError::ClockUnavailable)
}

fn runtime_policy_error(error: PromptRuntimeError) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new("prompt_runtime_terminal_invalid", error.to_string())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "exact_terminal_lease_tests.rs"]
mod exact_terminal_lease_tests;
