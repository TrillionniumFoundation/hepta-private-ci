//! Host-bound prompt delivery bridge for the real Codex provider spine.
//!
//! The host supplies an already exercise-bound prompt attachment for one turn.
//! This module contributes only developer-policy realizations to Codex prompt
//! assembly, then observes the exact physical provider attempt through the
//! existing ModelProviderPolicyContributor lease. It never opens the prompt
//! registry itself, never selects a factor, and never mints model/provider
//! authority.

use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

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
use codex_extension_api::PromptFragment;
use codex_extension_api::TurnContextContributionInput;
use codex_hepta_types::Digest32;
use codex_hepta_types::PromptDeliveryObservationV1;
use codex_hepta_types::PromptDeliveryRejectReasonV1;
use codex_hepta_types::StableId;
use tokio::sync::Mutex;

use crate::CodexOperationIntent;
use crate::PromptProviderTerminalObservationV1;
use crate::observe_prompt_delivery_v1;

const ATTACHMENT_DOMAIN: &[u8] = b"hepta.runtime-codex.prompt-attachment.v1";
const MAX_DEVELOPER_FRAGMENTS: usize = 128;
const MAX_DEVELOPER_FRAGMENT_BYTES: usize = 64 * 1024;
const MAX_DEVELOPER_TOTAL_BYTES: usize = 1024 * 1024;
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

pub type PromptRuntimePrepareFuture = Pin<
    Box<
        dyn Future<
                Output = Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError>,
            > + Send
            + 'static,
    >,
>;
pub type PromptRuntimeRecordFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;

type PromptRuntimePrepareFn =
    dyn Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static;
type PromptRuntimeRecordFn =
    dyn Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static;

/// Host capability used by App Server. Missing capability means prompt.runtime
/// is not installed and ordinary Codex behavior is unchanged.
#[derive(Clone)]
pub struct PromptRuntimeHost {
    capability_id: Arc<str>,
    prepare: Arc<PromptRuntimePrepareFn>,
    record: Arc<PromptRuntimeRecordFn>,
}

impl PromptRuntimeHost {
    pub fn new<P, R>(
        capability_id: impl Into<String>,
        prepare: P,
        record: R,
    ) -> Result<Self, PromptRuntimeError>
    where
        P: Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static,
        R: Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static,
    {
        let capability_id = capability_id.into();
        StableId::new(capability_id.clone())
            .map_err(|_| PromptRuntimeError::InvalidAttachment("capability id"))?;
        Ok(Self {
            capability_id: Arc::from(capability_id),
            prepare: Arc::new(prepare),
            record: Arc::new(record),
        })
    }

    async fn prepare(
        &self,
        request: PromptRuntimePrepareRequest,
    ) -> Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError> {
        (self.prepare)(request).await
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
            .finish_non_exhaustive()
    }
}

impl PartialEq for PromptRuntimeHost {
    fn eq(&self, other: &Self) -> bool {
        self.capability_id == other.capability_id
            && Arc::ptr_eq(&self.prepare, &other.prepare)
            && Arc::ptr_eq(&self.record, &other.record)
    }
}

impl Eq for PromptRuntimeHost {}

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
    pub attempt_id: String,
    pub request_binding_id: String,
    pub provider_request_digest: Digest32,
    pub outcome: PromptRuntimeTerminalOutcomeV1,
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
            || self.attempt_id.is_empty()
            || self.request_binding_id.is_empty()
            || self.observed_unix_ms == 0
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
                if observation.delivered || self.terminal_reason_code.is_none() {
                    return Err(PromptRuntimeError::InvalidTerminalRecord);
                }
                validate_observation_binding(self, observation)?;
            }
            PromptRuntimeTerminalOutcomeV1::NotDispatched
            | PromptRuntimeTerminalOutcomeV1::Indeterminate => {
                if self.delivery_observation.is_some() || self.terminal_reason_code.is_none() {
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
            let provider_request_digest =
                Digest32::from_str(input.wire_semantic_sha256.as_str()).map_err(|_| {
                    ModelProviderPolicyError::new(
                        "prompt_runtime_provider_digest_invalid",
                        "host provider request digest is invalid",
                    )
                })?;
            let intent = CodexOperationIntent {
                operation_id: parse_stable_id(input.attempt_id, "attempt id")?,
                thread_id: parse_stable_id(input.thread_id, "thread id")?,
                method_id: StableId::new("provider.send").map_err(|_| {
                    ModelProviderPolicyError::new(
                        "prompt_runtime_internal_identity_invalid",
                        "runtime method identity is invalid",
                    )
                })?,
                payload_digest: provider_request_digest,
                lease_payload_digest: provider_request_digest,
                deadline_ms: attachment.deadline_ms,
            };
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(PromptRuntimeAttemptLease {
                    host: self.host.clone(),
                    attachment,
                    intent,
                    attempt_id: input.attempt_id.to_owned(),
                    request_binding_id: input.request_binding_id.to_owned(),
                    provider_request_digest,
                    dispatch_unix_ms,
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
    intent: CodexOperationIntent,
    attempt_id: String,
    request_binding_id: String,
    provider_request_digest: Digest32,
    dispatch_unix_ms: u64,
}

impl ModelProviderAttemptLease for PromptRuntimeAttemptLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            let observed_unix_ms = current_unix_ms().map_err(runtime_policy_error)?;
            let (outcome, terminal_reason_code, delivery_observation) =
                self.map_terminal(terminal).map_err(runtime_policy_error)?;
            let record = PromptRuntimeTerminalRecordV1 {
                compilation_id: self.attachment.compilation_id.clone(),
                context_attachment_digest: self.attachment.context_attachment_digest,
                context_payload_digest: self.attachment.context_payload_digest,
                source_binding_digest: self.attachment.source_binding_digest,
                attempt_id: self.attempt_id,
                request_binding_id: self.request_binding_id,
                provider_request_digest: self.provider_request_digest,
                outcome,
                terminal_reason_code,
                delivery_observation,
                observed_unix_ms,
            };
            record.validate().map_err(runtime_policy_error)?;
            self.host.record(record).await.map_err(|error| {
                ModelProviderPolicyError::new(
                    error.reason_code().to_owned(),
                    error.detail().to_owned(),
                )
            })
        })
    }
}

impl PromptRuntimeAttemptLease {
    fn map_terminal(
        &self,
        terminal: ModelProviderTerminal,
    ) -> Result<
        (
            PromptRuntimeTerminalOutcomeV1,
            Option<String>,
            Option<PromptDeliveryObservationV1>,
        ),
        PromptRuntimeError,
    > {
        match terminal {
            ModelProviderTerminal::Completed { .. } => {
                let observation = observe_prompt_delivery_v1(
                    self.dispatch_unix_ms,
                    &self.intent,
                    self.attachment.compilation_id.clone(),
                    PromptProviderTerminalObservationV1 {
                        terminal_observed: true,
                        observed_provider_request_digest: self.provider_request_digest,
                        delivered: true,
                        rejected_reason: None,
                        observed_token_positions: None,
                        truncation_observed: false,
                    },
                )
                .map_err(|_| PromptRuntimeError::InvalidTerminalRecord)?;
                Ok((
                    PromptRuntimeTerminalOutcomeV1::Delivered,
                    None,
                    Some(observation),
                ))
            }
            ModelProviderTerminal::Rejected { reason_code } => {
                let rejection_reason = rejection_reason(&reason_code)?;
                let observation = observe_prompt_delivery_v1(
                    self.dispatch_unix_ms,
                    &self.intent,
                    self.attachment.compilation_id.clone(),
                    PromptProviderTerminalObservationV1 {
                        terminal_observed: true,
                        observed_provider_request_digest: self.provider_request_digest,
                        delivered: false,
                        rejected_reason: Some(rejection_reason),
                        observed_token_positions: None,
                        truncation_observed: false,
                    },
                )
                .map_err(|_| PromptRuntimeError::InvalidTerminalRecord)?;
                Ok((
                    PromptRuntimeTerminalOutcomeV1::Rejected,
                    Some(reason_code),
                    Some(observation),
                ))
            }
            ModelProviderTerminal::NotDispatched { reason_code } => Ok((
                PromptRuntimeTerminalOutcomeV1::NotDispatched,
                Some(reason_code),
                None,
            )),
            ModelProviderTerminal::Indeterminate { reason_code, .. } => Ok((
                PromptRuntimeTerminalOutcomeV1::Indeterminate,
                Some(reason_code),
                None,
            )),
            ModelProviderTerminal::CompletedUnary { .. } => Ok((
                PromptRuntimeTerminalOutcomeV1::Indeterminate,
                Some("unexpected_unary_terminal_for_turn".to_owned()),
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

fn rejection_reason(reason_code: &str) -> Result<PromptDeliveryRejectReasonV1, PromptRuntimeError> {
    let id = StableId::new(reason_code.to_owned()).unwrap_or_else(|_| {
        StableId::new(Digest32::of_bytes(reason_code.as_bytes()).to_string())
            .expect("digest hex is a valid stable identifier")
    });
    PromptDeliveryRejectReasonV1::new(id).map_err(|_| PromptRuntimeError::InvalidTerminalRecord)
}

fn parse_stable_id(
    value: &str,
    field: &'static str,
) -> Result<StableId, ModelProviderPolicyError> {
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
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
#[path = "runtime_prompt_tests.rs"]
mod tests;
