#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value)


def replace_once(path: str, old: str, new: str) -> None:
    value = read(path)
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, found {count}: {old[:140]!r}")
    write(path, value.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str, flags: int = 0) -> None:
    value = read(path)
    updated, count = re.subn(pattern, replacement, value, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{path}: expected one regex match, found {count}: {pattern[:140]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Prompt extension protocol: durable dispatch generation, opaque fence token,
# digest-only output decisions, output accounting, and explicit terminal state.
# ---------------------------------------------------------------------------
path = "codex-rs/ext/hepta-prompt/src/lib.rs"
replace_once(
    path,
    "use codex_extension_api::ModelProviderInvocationInput;\n",
    "use codex_extension_api::ModelProviderInvocationInput;\nuse codex_extension_api::ModelProviderOutputBatch;\nuse codex_extension_api::ModelProviderOutputDecision;\n",
)
replace_once(
    path,
    "const ATTACHMENT_DOMAIN: &[u8] = b\"hepta.runtime-codex.prompt-attachment.v1\";\n",
    """const ATTACHMENT_DOMAIN: &[u8] = b"hepta.runtime-codex.prompt-attachment.v1";
const FENCE_TOKEN_DOMAIN: &[u8] = b"hepta.runtime-codex.prompt-fence-token.v1";
const OUTPUT_CHAIN_DOMAIN: &[u8] = b"hepta.runtime-codex.prompt-output-chain.v1";
const MAX_OUTPUT_REASON_BYTES: usize = 256;
const MAX_OUTPUT_MESSAGE_BYTES: usize = 1024;
""",
)
replace_once(
    path,
    """pub type PromptRuntimeDispatchFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;
pub type PromptRuntimeRecordFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;

type PromptRuntimePrepareFn =
    dyn Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static;
type PromptRuntimeDispatchFn =
    dyn Fn(PromptRuntimeDispatchRecordV1) -> PromptRuntimeDispatchFuture + Send + Sync + 'static;
type PromptRuntimeRecordFn =
    dyn Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static;
""",
    """pub type PromptRuntimeDispatchFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;
pub type PromptRuntimeFencedDispatchFuture = Pin<
    Box<
        dyn Future<Output = Result<PromptRuntimeFenceTokenV1, PromptRuntimeHostError>>
            + Send
            + 'static,
    >,
>;
pub type PromptRuntimeOutputFuture = Pin<
    Box<
        dyn Future<Output = Result<PromptRuntimeOutputDecisionV1, PromptRuntimeHostError>>
            + Send
            + 'static,
    >,
>;
pub type PromptRuntimeRecordFuture =
    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;

type PromptRuntimePrepareFn =
    dyn Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static;
type PromptRuntimeFencedDispatchFn = dyn Fn(
        PromptRuntimeDispatchRecordV1,
    ) -> PromptRuntimeFencedDispatchFuture
    + Send
    + Sync
    + 'static;
type PromptRuntimeOutputFn =
    dyn Fn(PromptRuntimeOutputRequestV1) -> PromptRuntimeOutputFuture + Send + Sync + 'static;
type PromptRuntimeRecordFn =
    dyn Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static;
""",
)
replace_once(
    path,
    """pub struct PromptRuntimeHost {
    capability_id: Arc<str>,
    prepare: Arc<PromptRuntimePrepareFn>,
    dispatch: Arc<PromptRuntimeDispatchFn>,
    record: Arc<PromptRuntimeRecordFn>,
}
""",
    """pub struct PromptRuntimeHost {
    capability_id: Arc<str>,
    prepare: Arc<PromptRuntimePrepareFn>,
    dispatch: Arc<PromptRuntimeFencedDispatchFn>,
    output: Arc<PromptRuntimeOutputFn>,
    record: Arc<PromptRuntimeRecordFn>,
}
""",
)
regex_once(
    path,
    r"impl PromptRuntimeHost \{\n    pub fn new<P, D, R>\(.*?\n    async fn prepare\(",
    """impl PromptRuntimeHost {
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
        let dispatch = Arc::new(dispatch);
        Self::new_with_output_fence(
            capability_id,
            prepare,
            move |record: PromptRuntimeDispatchRecordV1| -> PromptRuntimeFencedDispatchFuture {
                let dispatch = Arc::clone(&dispatch);
                let legacy_generation = record.dispatched_unix_ms.max(1);
                Box::pin(async move {
                    let token = PromptRuntimeFenceTokenV1::from_dispatch(
                        &record,
                        legacy_generation,
                    )?;
                    dispatch(record).await?;
                    Ok(token)
                })
            },
            |_request: PromptRuntimeOutputRequestV1| -> PromptRuntimeOutputFuture {
                Box::pin(std::future::ready(Ok(PromptRuntimeOutputDecisionV1::Allow)))
            },
            record,
        )
    }

    pub fn new_with_output_fence<P, D, O, R>(
        capability_id: impl Into<String>,
        prepare: P,
        dispatch: D,
        output: O,
        record: R,
    ) -> Result<Self, PromptRuntimeError>
    where
        P: Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static,
        D: Fn(PromptRuntimeDispatchRecordV1) -> PromptRuntimeFencedDispatchFuture
            + Send
            + Sync
            + 'static,
        O: Fn(PromptRuntimeOutputRequestV1) -> PromptRuntimeOutputFuture + Send + Sync + 'static,
        R: Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static,
    {
        let capability_id = capability_id.into();
        StableId::new(capability_id.clone())
            .map_err(|_| PromptRuntimeError::InvalidAttachment("capability id"))?;
        Ok(Self {
            capability_id: Arc::from(capability_id),
            prepare: Arc::new(prepare),
            dispatch: Arc::new(dispatch),
            output: Arc::new(output),
            record: Arc::new(record),
        })
    }

    async fn prepare(""",
    flags=re.S,
)
replace_once(
    path,
    """    async fn dispatch(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<(), PromptRuntimeHostError> {
        (self.dispatch)(record).await
    }

    async fn record(
""",
    """    async fn dispatch(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<PromptRuntimeFenceTokenV1, PromptRuntimeHostError> {
        let expected = record.clone();
        let token = (self.dispatch)(record).await?;
        token.validate().map_err(runtime_host_protocol_error)?;
        if !token.matches_dispatch(&expected) {
            return Err(runtime_host_protocol_error(
                PromptRuntimeError::InvalidFenceToken,
            ));
        }
        Ok(token)
    }

    async fn authorize_output(
        &self,
        request: PromptRuntimeOutputRequestV1,
    ) -> Result<PromptRuntimeOutputDecisionV1, PromptRuntimeHostError> {
        request.validate().map_err(runtime_host_protocol_error)?;
        let decision = (self.output)(request).await?;
        decision.validate().map_err(runtime_host_protocol_error)?;
        Ok(decision)
    }

    async fn record(
""",
)
replace_once(
    path,
    """            && Arc::ptr_eq(&self.prepare, &other.prepare)
            && Arc::ptr_eq(&self.dispatch, &other.dispatch)
            && Arc::ptr_eq(&self.record, &other.record)
""",
    """            && Arc::ptr_eq(&self.prepare, &other.prepare)
            && Arc::ptr_eq(&self.dispatch, &other.dispatch)
            && Arc::ptr_eq(&self.output, &other.output)
            && Arc::ptr_eq(&self.record, &other.record)
""",
)

# Insert protocol types after dispatch-record validation.
marker = """impl PromptRuntimeDispatchRecordV1 {
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
"""
insert = marker + """

/// Durable generation and exact immutable binding for one admitted physical
/// provider attempt. The token is opaque to Core and carries no prompt bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeFenceTokenV1 {
    pub dispatch_generation: u64,
    pub compilation_id: StableId,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub source_binding_digest: Digest32,
    pub thread_id: String,
    pub turn_id: String,
    pub attempt_id: String,
    pub request_binding_id: String,
    pub provider_request_digest: Digest32,
    pub token_digest: Digest32,
}

impl PromptRuntimeFenceTokenV1 {
    pub fn from_dispatch(
        record: &PromptRuntimeDispatchRecordV1,
        dispatch_generation: u64,
    ) -> Result<Self, PromptRuntimeError> {
        record.validate()?;
        if dispatch_generation == 0 {
            return Err(PromptRuntimeError::InvalidFenceToken);
        }
        let mut value = Self {
            dispatch_generation,
            compilation_id: record.compilation_id.clone(),
            context_attachment_digest: record.context_attachment_digest,
            context_payload_digest: record.context_payload_digest,
            source_binding_digest: record.source_binding_digest,
            thread_id: record.thread_id.clone(),
            turn_id: record.turn_id.clone(),
            attempt_id: record.attempt_id.clone(),
            request_binding_id: record.request_binding_id.clone(),
            provider_request_digest: record.provider_request_digest,
            token_digest: Digest32::ZERO,
        };
        value.token_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        if self.dispatch_generation == 0
            || self.context_attachment_digest.is_zero()
            || self.context_payload_digest.is_zero()
            || self.source_binding_digest.is_zero()
            || self.provider_request_digest.is_zero()
            || self.token_digest.is_zero()
            || self.thread_id.is_empty()
            || self.thread_id.len() > 256
            || self.turn_id.is_empty()
            || self.turn_id.len() > 256
            || self.attempt_id.is_empty()
            || self.attempt_id.len() > 256
            || self.request_binding_id.is_empty()
            || self.request_binding_id.len() > 256
            || self.token_digest != self.compute_digest()
        {
            return Err(PromptRuntimeError::InvalidFenceToken);
        }
        Ok(())
    }

    #[must_use]
    pub fn matches_dispatch(&self, record: &PromptRuntimeDispatchRecordV1) -> bool {
        self.compilation_id == record.compilation_id
            && self.context_attachment_digest == record.context_attachment_digest
            && self.context_payload_digest == record.context_payload_digest
            && self.source_binding_digest == record.source_binding_digest
            && self.thread_id == record.thread_id
            && self.turn_id == record.turn_id
            && self.attempt_id == record.attempt_id
            && self.request_binding_id == record.request_binding_id
            && self.provider_request_digest == record.provider_request_digest
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = FENCE_TOKEN_DOMAIN.to_vec();
        bytes.extend_from_slice(&self.dispatch_generation.to_be_bytes());
        push_id(&mut bytes, &self.compilation_id);
        bytes.extend_from_slice(self.context_attachment_digest.as_array());
        bytes.extend_from_slice(self.context_payload_digest.as_array());
        bytes.extend_from_slice(self.source_binding_digest.as_array());
        push_text(&mut bytes, &self.thread_id);
        push_text(&mut bytes, &self.turn_id);
        push_text(&mut bytes, &self.attempt_id);
        push_text(&mut bytes, &self.request_binding_id);
        bytes.extend_from_slice(self.provider_request_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

/// One digest-only event authorization request at the final Core release edge.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeOutputRequestV1 {
    pub fence: PromptRuntimeFenceTokenV1,
    pub sequence: u64,
    pub event_digest: Digest32,
    pub encoded_bytes: u64,
    pub observed_unix_ms: u64,
}

impl PromptRuntimeOutputRequestV1 {
    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        self.fence.validate()?;
        if self.sequence == 0
            || self.event_digest.is_zero()
            || self.encoded_bytes == 0
            || self.observed_unix_ms == 0
        {
            return Err(PromptRuntimeError::InvalidOutputRecord);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptRuntimeOutputDecisionV1 {
    Allow,
    DropAfterFence {
        reason_code: String,
        message: String,
    },
}

impl PromptRuntimeOutputDecisionV1 {
    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        if let Self::DropAfterFence {
            reason_code,
            message,
        } = self
            && (reason_code.is_empty()
                || reason_code.len() > MAX_OUTPUT_REASON_BYTES
                || reason_code.as_bytes().contains(&0)
                || message.is_empty()
                || message.len() > MAX_OUTPUT_MESSAGE_BYTES
                || message.as_bytes().contains(&0))
        {
            return Err(PromptRuntimeError::InvalidOutputRecord);
        }
        Ok(())
    }

    fn reason_code(&self) -> Option<&str> {
        match self {
            Self::Allow => None,
            Self::DropAfterFence { reason_code, .. } => Some(reason_code),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeOutputSummaryV1 {
    pub observed_batches: u64,
    pub observed_bytes: u64,
    pub allowed_batches: u64,
    pub allowed_bytes: u64,
    pub dropped_after_fence_batches: u64,
    pub dropped_after_fence_bytes: u64,
    pub last_sequence: u64,
    pub chain_digest: Digest32,
    pub first_drop_sequence: Option<u64>,
    pub first_drop_event_digest: Option<Digest32>,
    pub first_drop_reason_code: Option<String>,
}

impl Default for PromptRuntimeOutputSummaryV1 {
    fn default() -> Self {
        Self {
            observed_batches: 0,
            observed_bytes: 0,
            allowed_batches: 0,
            allowed_bytes: 0,
            dropped_after_fence_batches: 0,
            dropped_after_fence_bytes: 0,
            last_sequence: 0,
            chain_digest: Digest32::ZERO,
            first_drop_sequence: None,
            first_drop_event_digest: None,
            first_drop_reason_code: None,
        }
    }
}

impl PromptRuntimeOutputSummaryV1 {
    fn observe(
        &mut self,
        request: &PromptRuntimeOutputRequestV1,
        decision: &PromptRuntimeOutputDecisionV1,
    ) -> Result<(), PromptRuntimeError> {
        request.validate()?;
        decision.validate()?;
        if request.sequence != self.last_sequence.saturating_add(1) {
            return Err(PromptRuntimeError::InvalidOutputRecord);
        }
        let observed_batches = self
            .observed_batches
            .checked_add(1)
            .ok_or(PromptRuntimeError::InvalidOutputRecord)?;
        let observed_bytes = self
            .observed_bytes
            .checked_add(request.encoded_bytes)
            .ok_or(PromptRuntimeError::InvalidOutputRecord)?;
        let mut bytes = OUTPUT_CHAIN_DOMAIN.to_vec();
        bytes.extend_from_slice(self.chain_digest.as_array());
        bytes.extend_from_slice(request.fence.token_digest.as_array());
        bytes.extend_from_slice(&request.sequence.to_be_bytes());
        bytes.extend_from_slice(request.event_digest.as_array());
        bytes.extend_from_slice(&request.encoded_bytes.to_be_bytes());
        match decision {
            PromptRuntimeOutputDecisionV1::Allow => {
                bytes.push(0);
                self.allowed_batches = self
                    .allowed_batches
                    .checked_add(1)
                    .ok_or(PromptRuntimeError::InvalidOutputRecord)?;
                self.allowed_bytes = self
                    .allowed_bytes
                    .checked_add(request.encoded_bytes)
                    .ok_or(PromptRuntimeError::InvalidOutputRecord)?;
            }
            PromptRuntimeOutputDecisionV1::DropAfterFence { reason_code, .. } => {
                bytes.push(1);
                push_text(&mut bytes, reason_code);
                self.dropped_after_fence_batches = self
                    .dropped_after_fence_batches
                    .checked_add(1)
                    .ok_or(PromptRuntimeError::InvalidOutputRecord)?;
                self.dropped_after_fence_bytes = self
                    .dropped_after_fence_bytes
                    .checked_add(request.encoded_bytes)
                    .ok_or(PromptRuntimeError::InvalidOutputRecord)?;
                if self.first_drop_sequence.is_none() {
                    self.first_drop_sequence = Some(request.sequence);
                    self.first_drop_event_digest = Some(request.event_digest);
                    self.first_drop_reason_code = Some(reason_code.clone());
                }
            }
        }
        self.observed_batches = observed_batches;
        self.observed_bytes = observed_bytes;
        self.last_sequence = request.sequence;
        self.chain_digest = Digest32::of_bytes(&bytes);
        self.validate()
    }

    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        if self.observed_batches
            != self
                .allowed_batches
                .checked_add(self.dropped_after_fence_batches)
                .ok_or(PromptRuntimeError::InvalidOutputRecord)?
            || self.observed_bytes
                != self
                    .allowed_bytes
                    .checked_add(self.dropped_after_fence_bytes)
                    .ok_or(PromptRuntimeError::InvalidOutputRecord)?
            || self.last_sequence != self.observed_batches
        {
            return Err(PromptRuntimeError::InvalidOutputRecord);
        }
        if self.observed_batches == 0 {
            if !self.chain_digest.is_zero()
                || self.first_drop_sequence.is_some()
                || self.first_drop_event_digest.is_some()
                || self.first_drop_reason_code.is_some()
            {
                return Err(PromptRuntimeError::InvalidOutputRecord);
            }
        } else if self.chain_digest.is_zero() {
            return Err(PromptRuntimeError::InvalidOutputRecord);
        }
        let has_drop = self.dropped_after_fence_batches > 0;
        if has_drop
            != (self.first_drop_sequence.is_some()
                && self.first_drop_event_digest.is_some()
                && self.first_drop_reason_code.is_some())
            || self.first_drop_sequence.is_some_and(|value| value > self.last_sequence)
            || self.first_drop_event_digest.is_some_and(|value| value.is_zero())
            || self.first_drop_reason_code.as_ref().is_some_and(|value| {
                value.is_empty()
                    || value.len() > MAX_OUTPUT_REASON_BYTES
                    || value.as_bytes().contains(&0)
            })
        {
            return Err(PromptRuntimeError::InvalidOutputRecord);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeDeliveryStateV1 {
    RejectedBeforeDispatch,
    DispatchedProviderUnknown,
    ProviderRejected,
    ProviderCompletedOutputFenced,
    PartiallyStreamed,
    FullyObserved,
    RecoveryReconciled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeOutputTerminalV1 {
    pub fence_token_digest: Digest32,
    pub delivery_state: PromptRuntimeDeliveryStateV1,
    pub summary: PromptRuntimeOutputSummaryV1,
}

impl PromptRuntimeOutputTerminalV1 {
    pub fn validate(&self) -> Result<(), PromptRuntimeError> {
        if self.fence_token_digest.is_zero() {
            return Err(PromptRuntimeError::InvalidOutputRecord);
        }
        self.summary.validate()
    }
}
"""
replace_once(path, marker, insert)

# Add optional output evidence to terminal contract and validation.
replace_once(
    path,
    """    pub terminal_reason_code: Option<String>,
    pub delivery_observation: Option<PromptDeliveryObservationV1>,
    pub observed_unix_ms: u64,
""",
    """    pub terminal_reason_code: Option<String>,
    pub delivery_observation: Option<PromptDeliveryObservationV1>,
    pub output_terminal: Option<PromptRuntimeOutputTerminalV1>,
    pub observed_unix_ms: u64,
""",
)
replace_once(
    path,
    """        match self.outcome {
            PromptRuntimeTerminalOutcomeV1::Delivered => {
""",
    """        if let Some(output) = &self.output_terminal {
            output.validate()?;
            let state_matches = match self.outcome {
                PromptRuntimeTerminalOutcomeV1::Delivered => matches!(
                    output.delivery_state,
                    PromptRuntimeDeliveryStateV1::ProviderCompletedOutputFenced
                        | PromptRuntimeDeliveryStateV1::PartiallyStreamed
                        | PromptRuntimeDeliveryStateV1::FullyObserved
                        | PromptRuntimeDeliveryStateV1::RecoveryReconciled
                ),
                PromptRuntimeTerminalOutcomeV1::Rejected => matches!(
                    output.delivery_state,
                    PromptRuntimeDeliveryStateV1::ProviderRejected
                        | PromptRuntimeDeliveryStateV1::RecoveryReconciled
                ),
                PromptRuntimeTerminalOutcomeV1::NotDispatched => output.delivery_state
                    == PromptRuntimeDeliveryStateV1::RejectedBeforeDispatch,
                PromptRuntimeTerminalOutcomeV1::Indeterminate => output.delivery_state
                    == PromptRuntimeDeliveryStateV1::DispatchedProviderUnknown,
            };
            if !state_matches {
                return Err(PromptRuntimeError::InvalidOutputRecord);
            }
        }
        match self.outcome {
            PromptRuntimeTerminalOutcomeV1::Delivered => {
""",
)
replace_once(
    path,
    """    InvalidProviderBinding,
    InvalidTerminalRecord,
    ClockUnavailable,
""",
    """    InvalidProviderBinding,
    InvalidFenceToken,
    InvalidOutputRecord,
    InvalidTerminalRecord,
    ClockUnavailable,
""",
)

# Dispatch now yields the durable token, and the lease owns output accounting.
replace_once(
    path,
    """            self.host.dispatch(dispatch_record).await.map_err(|error| {
                ModelProviderPolicyError::new(
                    error.reason_code().to_owned(),
                    error.detail().to_owned(),
                )
            })?;
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(PromptRuntimeAttemptLease {
""",
    """            let fence_token = self.host.dispatch(dispatch_record).await.map_err(|error| {
                ModelProviderPolicyError::new(
                    error.reason_code().to_owned(),
                    error.detail().to_owned(),
                )
            })?;
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(PromptRuntimeAttemptLease {
""",
)
replace_once(
    path,
    """                    provider_request_digest,
                    dispatch_unix_ms,
                }),
""",
    """                    provider_request_digest,
                    dispatch_unix_ms,
                    fence_token,
                    output_summary: PromptRuntimeOutputSummaryV1::default(),
                    output_fence: None,
                }),
""",
)
replace_once(
    path,
    """    provider_request_digest: Digest32,
    dispatch_unix_ms: u64,
}

impl ModelProviderAttemptLease for PromptRuntimeAttemptLease {
    fn finish(
""",
    """    provider_request_digest: Digest32,
    dispatch_unix_ms: u64,
    fence_token: PromptRuntimeFenceTokenV1,
    output_summary: PromptRuntimeOutputSummaryV1,
    output_fence: Option<(String, String)>,
}

impl ModelProviderAttemptLease for PromptRuntimeAttemptLease {
    fn authorize_output<'a>(
        &'a mut self,
        batch: ModelProviderOutputBatch,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderOutputDecision> {
        Box::pin(async move {
            batch.validate()?;
            let event_digest = Digest32::from_str(batch.event_sha256.as_str()).map_err(|_| {
                ModelProviderPolicyError::new(
                    "prompt_runtime_output_digest_invalid",
                    "Core supplied an invalid provider output digest",
                )
            })?;
            let request = PromptRuntimeOutputRequestV1 {
                fence: self.fence_token.clone(),
                sequence: batch.sequence,
                event_digest,
                encoded_bytes: batch.encoded_bytes,
                observed_unix_ms: current_unix_ms().map_err(runtime_policy_error)?,
            };
            let decision = match &self.output_fence {
                Some((reason_code, message)) => PromptRuntimeOutputDecisionV1::DropAfterFence {
                    reason_code: reason_code.clone(),
                    message: message.clone(),
                },
                None => self.host.authorize_output(request.clone()).await.map_err(|error| {
                    ModelProviderPolicyError::new(
                        error.reason_code().to_owned(),
                        error.detail().to_owned(),
                    )
                })?,
            };
            self.output_summary
                .observe(&request, &decision)
                .map_err(runtime_policy_error)?;
            match decision {
                PromptRuntimeOutputDecisionV1::Allow => Ok(ModelProviderOutputDecision::Allow),
                PromptRuntimeOutputDecisionV1::DropAfterFence {
                    reason_code,
                    message,
                } => {
                    if self.output_fence.is_none() {
                        self.output_fence = Some((reason_code.clone(), message.clone()));
                    }
                    Ok(ModelProviderOutputDecision::Drop {
                        reason_code,
                        message,
                    })
                }
            }
        })
    }

    fn finish(
""",
)
replace_once(
    path,
    """            let (outcome, terminal_reason_code, end_turn, delivery_observation) =
                self.map_terminal(terminal).map_err(runtime_policy_error)?;
""",
    """            let (
                outcome,
                terminal_reason_code,
                end_turn,
                delivery_observation,
                output_terminal,
            ) = self.map_terminal(terminal).map_err(runtime_policy_error)?;
""",
)
replace_once(
    path,
    """                terminal_reason_code,
                delivery_observation,
                observed_unix_ms,
""",
    """                terminal_reason_code,
                delivery_observation,
                output_terminal: Some(output_terminal),
                observed_unix_ms,
""",
)
# Replace map_terminal wholesale.
regex_once(
    path,
    r"    fn map_terminal\(\n        &self,\n        terminal: ModelProviderTerminal,\n    \) -> Result<.*?\n    \}\n\}\n\npub fn install_prompt_runtime",
    """    fn map_terminal(
        &self,
        terminal: ModelProviderTerminal,
    ) -> Result<
        (
            PromptRuntimeTerminalOutcomeV1,
            Option<String>,
            Option<bool>,
            Option<PromptDeliveryObservationV1>,
            PromptRuntimeOutputTerminalV1,
        ),
        PromptRuntimeError,
    > {
        self.output_summary.validate()?;
        let output = |delivery_state| PromptRuntimeOutputTerminalV1 {
            fence_token_digest: self.fence_token.token_digest,
            delivery_state,
            summary: self.output_summary.clone(),
        };
        match terminal {
            ModelProviderTerminal::Completed { end_turn, .. } => {
                let observation = self.delivery_observation(true, None)?;
                let delivery_state = if self.output_summary.dropped_after_fence_batches == 0 {
                    PromptRuntimeDeliveryStateV1::FullyObserved
                } else if self.output_summary.allowed_batches == 0 {
                    PromptRuntimeDeliveryStateV1::ProviderCompletedOutputFenced
                } else {
                    PromptRuntimeDeliveryStateV1::PartiallyStreamed
                };
                Ok((
                    PromptRuntimeTerminalOutcomeV1::Delivered,
                    None,
                    end_turn,
                    Some(observation),
                    output(delivery_state),
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
                    output(PromptRuntimeDeliveryStateV1::ProviderRejected),
                ))
            }
            ModelProviderTerminal::NotDispatched { reason_code } => Ok((
                PromptRuntimeTerminalOutcomeV1::NotDispatched,
                Some(reason_code),
                None,
                None,
                output(PromptRuntimeDeliveryStateV1::RejectedBeforeDispatch),
            )),
            ModelProviderTerminal::Indeterminate { reason_code, .. } => Ok((
                PromptRuntimeTerminalOutcomeV1::Indeterminate,
                Some(reason_code),
                None,
                None,
                output(PromptRuntimeDeliveryStateV1::DispatchedProviderUnknown),
            )),
            ModelProviderTerminal::CompletedUnary { .. } => Ok((
                PromptRuntimeTerminalOutcomeV1::Indeterminate,
                Some("unexpected_unary_terminal_for_turn".to_owned()),
                None,
                None,
                output(PromptRuntimeDeliveryStateV1::DispatchedProviderUnknown),
            )),
        }
    }
}

pub fn install_prompt_runtime""",
    flags=re.S,
)
replace_once(
    path,
    """fn runtime_policy_error(error: PromptRuntimeError) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new("prompt_runtime_terminal_invalid", error.to_string())
}
""",
    """fn runtime_policy_error(error: PromptRuntimeError) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new("prompt_runtime_terminal_invalid", error.to_string())
}

fn runtime_host_protocol_error(error: PromptRuntimeError) -> PromptRuntimeHostError {
    PromptRuntimeHostError::new("prompt_runtime_host_protocol_invalid", error.to_string())
}
""",
)

# ---------------------------------------------------------------------------
# Adapter reexports for Agentd and product callers.
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-codex-adapter/src/lib.rs"
replace_once(
    path,
    """pub use runtime_prompt::PromptRuntimeDispatchFuture;
pub use runtime_prompt::PromptRuntimeDispatchRecordV1;
""",
    """pub use runtime_prompt::PromptRuntimeDeliveryStateV1;
pub use runtime_prompt::PromptRuntimeDispatchFuture;
pub use runtime_prompt::PromptRuntimeDispatchRecordV1;
pub use runtime_prompt::PromptRuntimeFenceTokenV1;
pub use runtime_prompt::PromptRuntimeFencedDispatchFuture;
""",
)
replace_once(
    path,
    """pub use runtime_prompt::PromptRuntimePrepareRequest;
pub use runtime_prompt::PromptRuntimeRecordFuture;
""",
    """pub use runtime_prompt::PromptRuntimeOutputDecisionV1;
pub use runtime_prompt::PromptRuntimeOutputFuture;
pub use runtime_prompt::PromptRuntimeOutputRequestV1;
pub use runtime_prompt::PromptRuntimeOutputSummaryV1;
pub use runtime_prompt::PromptRuntimeOutputTerminalV1;
pub use runtime_prompt::PromptRuntimePrepareRequest;
pub use runtime_prompt::PromptRuntimeRecordFuture;
""",
)

# ---------------------------------------------------------------------------
# Agentd: derive a durable monotonic dispatch generation from the append-only
# dispatch order, validate every output callback against that token, re-run
# current-use validation under the registry guard, and persist terminal output
# evidence with a V1 -> V2 migration.
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
replace_once(
    path,
    "use codex_hepta_codex_adapter::PromptRuntimeDispatchRecordV1;\n",
    """use codex_hepta_codex_adapter::PromptRuntimeDeliveryStateV1;
use codex_hepta_codex_adapter::PromptRuntimeDispatchRecordV1;
use codex_hepta_codex_adapter::PromptRuntimeFenceTokenV1;
use codex_hepta_codex_adapter::PromptRuntimeFencedDispatchFuture;
""",
)
replace_once(
    path,
    "use codex_hepta_codex_adapter::PromptRuntimeHostError;\n",
    """use codex_hepta_codex_adapter::PromptRuntimeHostError;
use codex_hepta_codex_adapter::PromptRuntimeOutputDecisionV1;
use codex_hepta_codex_adapter::PromptRuntimeOutputFuture;
use codex_hepta_codex_adapter::PromptRuntimeOutputRequestV1;
use codex_hepta_codex_adapter::PromptRuntimeOutputSummaryV1;
use codex_hepta_codex_adapter::PromptRuntimeOutputTerminalV1;
""",
)
replace_once(
    path,
    "const PROMPT_RUNTIME_SCHEMA: u32 = 1;\n",
    "const LEGACY_PROMPT_RUNTIME_SCHEMA: u32 = 1;\nconst PROMPT_RUNTIME_SCHEMA: u32 = 2;\n",
)
replace_once(
    path,
    """    TerminalBindingMismatch,
    TerminalConflict,
""",
    """    TerminalBindingMismatch,
    OutputBindingMismatch,
    TerminalConflict,
""",
)

# Existing unit-returning dispatch becomes a compatibility wrapper; fenced
# dispatch is the single implementation.
regex_once(
    path,
    r"    fn record_dispatch\(\n        &self,\n        record: PromptRuntimeDispatchRecordV1,\n    \) -> Result<\(\), PromptRuntimeHostError> \{\n.*?\n    \}\n\n    fn record\(",
    """    fn record_dispatch(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<(), PromptRuntimeHostError> {
        self.record_dispatch_fenced(record).map(|_| ())
    }

    fn record_dispatch_fenced(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<PromptRuntimeFenceTokenV1, PromptRuntimeHostError> {
        record.validate().map_err(|error| {
            PromptRuntimeHostError::new("agentd_prompt_runtime_dispatch_invalid", error.to_string())
        })?;
        self.commit_state(|state| {
            if let Some(existing) = state.dispatch_records.get(&record.attempt_id) {
                return if existing == &record {
                    dispatch_fence_token(state, existing)
                } else {
                    Err(AgentdPromptRuntimeError::DispatchConflict)
                };
            }
            let key = dispatch_key(&record);
            if has_unresolved_dispatch(state, &key) {
                return Err(AgentdPromptRuntimeError::IndeterminatePending);
            }
            let Some(staged) = state.staged.get(&key) else {
                return Err(AgentdPromptRuntimeError::TerminalBindingMismatch);
            };
            if !dispatch_matches_attachment(&record, staged) {
                return Err(AgentdPromptRuntimeError::TerminalBindingMismatch);
            }
            if state.dispatch_records.len() >= MAX_DISPATCH_RECORDS {
                return Err(AgentdPromptRuntimeError::CapacityExceeded);
            }
            state
                .dispatch_records
                .insert(record.attempt_id.clone(), record.clone());
            state.dispatch_order.push_back(record.attempt_id.clone());
            dispatch_fence_token(state, &record)
        })
        .map_err(host_error)
    }

    fn output_binding(
        &self,
        request: &PromptRuntimeOutputRequestV1,
    ) -> Result<(PromptRuntimeDispatchRecordV1, PromptRuntimeAttachmentV1), PromptRuntimeHostError>
    {
        request.validate().map_err(|error| {
            PromptRuntimeHostError::new("agentd_prompt_runtime_output_invalid", error.to_string())
        })?;
        self.ensure_available().map_err(host_error)?;
        let state = self.state.lock().map_err(|_| {
            PromptRuntimeHostError::new(
                "agentd_prompt_runtime_state_poisoned",
                "Agentd prompt runtime state lock is poisoned",
            )
        })?;
        let dispatch = state
            .dispatch_records
            .get(&request.fence.attempt_id)
            .ok_or_else(|| host_error(AgentdPromptRuntimeError::OutputBindingMismatch))?;
        let expected = dispatch_fence_token(&state, dispatch).map_err(host_error)?;
        if expected != request.fence
            || state
                .terminal_records
                .get(&dispatch.attempt_id)
                .is_some_and(|terminal| {
                    terminal.outcome != PromptRuntimeTerminalOutcomeV1::Indeterminate
                })
        {
            return Err(host_error(AgentdPromptRuntimeError::OutputBindingMismatch));
        }
        let attachment = state
            .staged
            .get(&dispatch_key(dispatch))
            .filter(|attachment| dispatch_matches_attachment(dispatch, attachment))
            .cloned()
            .ok_or_else(|| host_error(AgentdPromptRuntimeError::OutputBindingMismatch))?;
        Ok((dispatch.clone(), attachment))
    }

    fn record(""",
    flags=re.S,
)

# Normalize recovered terminals and bind their output token to durable dispatch.
replace_once(
    path,
    """    fn record(&self, record: PromptRuntimeTerminalRecordV1) -> Result<(), PromptRuntimeHostError> {
        record.validate().map_err(|error| {
""",
    """    fn record(
        &self,
        mut record: PromptRuntimeTerminalRecordV1,
    ) -> Result<(), PromptRuntimeHostError> {
        record.validate().map_err(|error| {
""",
)
replace_once(
    path,
    """            if !terminal_matches_dispatch(&record, dispatch) {
                return Err(AgentdPromptRuntimeError::TerminalBindingMismatch);
            }

            let key = dispatch_key(dispatch);
            if let Some(existing) = state.terminal_records.get(&record.attempt_id) {
""",
    """            if !terminal_matches_dispatch(&record, dispatch) {
                return Err(AgentdPromptRuntimeError::TerminalBindingMismatch);
            }
            if let Some(output) = &record.output_terminal {
                let expected = dispatch_fence_token(state, dispatch)?;
                if output.fence_token_digest != expected.token_digest {
                    return Err(AgentdPromptRuntimeError::OutputBindingMismatch);
                }
            }

            let key = dispatch_key(dispatch);
            if let Some(existing) = state.terminal_records.get(&record.attempt_id) {
                if existing.outcome == PromptRuntimeTerminalOutcomeV1::Indeterminate
                    && matches!(
                        record.outcome,
                        PromptRuntimeTerminalOutcomeV1::Delivered
                            | PromptRuntimeTerminalOutcomeV1::Rejected
                    )
                    && let Some(output) = &mut record.output_terminal
                {
                    output.delivery_state = PromptRuntimeDeliveryStateV1::RecoveryReconciled;
                    output
                        .validate()
                        .map_err(|_| AgentdPromptRuntimeError::OutputBindingMismatch)?;
                }
""",
)

# Pipeline host uses real fenced dispatch and output current-use callbacks.
replace_once(
    path,
    """        let prepare_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHost::new(
""",
    """        let prepare_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let output_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHost::new_with_output_fence(
""",
    # This first occurrence is generic owner, not pipeline. Undo below by replacing only
)
# The first occurrence above is AgentdPromptRuntimeOwner::host and should stay legacy.
# Restore it, then replace the second occurrence specifically.
value = read(path)
first_new = """        let prepare_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let output_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHost::new_with_output_fence(
"""
legacy = """        let prepare_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHost::new(
"""
if value.count(first_new) != 1:
    raise SystemExit("unable to restore generic prompt runtime host")
value = value.replace(first_new, legacy, 1)
# Replace the remaining pipeline host exact block.
old_pipeline = """        let prepare_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHost::new(
            PROMPT_RUNTIME_CAPABILITY_ID,
            move |request: PromptRuntimePrepareRequest| -> PromptRuntimePrepareFuture {
                let owner = Arc::clone(&prepare_owner);
                Box::pin(async move { owner.prepare_final_use(request) })
            },
            move |record: PromptRuntimeDispatchRecordV1| -> PromptRuntimeDispatchFuture {
                let owner = Arc::clone(&dispatch_owner);
                Box::pin(async move { owner.record_dispatch_final_use(record) })
            },
            move |record: PromptRuntimeTerminalRecordV1| -> PromptRuntimeRecordFuture {
"""
new_pipeline = """        let prepare_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let output_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        PromptRuntimeHost::new_with_output_fence(
            PROMPT_RUNTIME_CAPABILITY_ID,
            move |request: PromptRuntimePrepareRequest| -> PromptRuntimePrepareFuture {
                let owner = Arc::clone(&prepare_owner);
                Box::pin(async move { owner.prepare_final_use(request) })
            },
            move |record: PromptRuntimeDispatchRecordV1| -> PromptRuntimeFencedDispatchFuture {
                let owner = Arc::clone(&dispatch_owner);
                Box::pin(async move { owner.record_dispatch_final_use(record) })
            },
            move |request: PromptRuntimeOutputRequestV1| -> PromptRuntimeOutputFuture {
                let owner = Arc::clone(&output_owner);
                Box::pin(async move { owner.authorize_output_final_use(request) })
            },
            move |record: PromptRuntimeTerminalRecordV1| -> PromptRuntimeRecordFuture {
"""
if value.count(old_pipeline) != 1:
    raise SystemExit(f"pipeline host exact block mismatch: {value.count(old_pipeline)}")
write(path, value.replace(old_pipeline, new_pipeline, 1))

replace_once(
    path,
    """    fn record_dispatch_final_use(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<(), PromptRuntimeHostError> {
""",
    """    fn record_dispatch_final_use(
        &self,
        record: PromptRuntimeDispatchRecordV1,
    ) -> Result<PromptRuntimeFenceTokenV1, PromptRuntimeHostError> {
""",
)
replace_once(
    path,
    """        self.runtime.record_dispatch(record)
    }

    fn record_terminal_final_use(
""",
    """        self.runtime.record_dispatch_fenced(record)
    }

    fn authorize_output_final_use(
        &self,
        request: PromptRuntimeOutputRequestV1,
    ) -> Result<PromptRuntimeOutputDecisionV1, PromptRuntimeHostError> {
        let (dispatch, attachment) = self.runtime.output_binding(&request)?;
        let now_unix_ms = prompt_host_now_unix_ms()?;
        if request.observed_unix_ms > now_unix_ms
            || request.observed_unix_ms < dispatch.dispatched_unix_ms
        {
            return Err(PromptRuntimeHostError::new(
                "agentd_prompt_output_clock_invalid",
                "provider output observation is outside the trusted host interval",
            ));
        }
        let key = PromptFinalUseKeyV1::new(&dispatch.thread_id, &dispatch.turn_id)
            .map_err(final_use_store_host_error)?;
        let lease = self
            .final_use
            .get(&key)
            .map_err(final_use_store_host_error)?
            .ok_or_else(|| {
                PromptRuntimeHostError::new(
                    "agentd_prompt_final_use_missing",
                    "provider output has no durable prompt final-use lease",
                )
            })?;
        let registry = self.registry.lock().map_err(|_| {
            PromptRuntimeHostError::new(
                "agentd_prompt_registry_state_poisoned",
                "prompt registry owner lock is poisoned",
            )
        })?;
        match self.final_use_validator.validate(
            &lease,
            &registry,
            &PromptFinalUseBoundaryV1 {
                compilation_id: &attachment.compilation_id,
                context_attachment_digest: attachment.context_attachment_digest,
                context_payload_digest: attachment.context_payload_digest,
                now_unix_ms,
            },
        ) {
            Ok(()) => Ok(PromptRuntimeOutputDecisionV1::Allow),
            Err(error) => Ok(PromptRuntimeOutputDecisionV1::DropAfterFence {
                reason_code: error.code().to_owned(),
                message: "prompt selection is no longer current at the final output boundary"
                    .to_owned(),
            }),
        }
    }

    fn record_terminal_final_use(
""",
)
replace_once(
    path,
    """    ) -> Result<(), PromptRuntimeHostError> {
        let key = PromptFinalUseKeyV1::new(&record.thread_id, &record.turn_id)
            .map_err(final_use_store_host_error)?;
        let clear = terminal_clears_stage(&record);
""",
    """    ) -> Result<(), PromptRuntimeHostError> {
        if record.output_terminal.is_none() {
            return Err(PromptRuntimeHostError::new(
                "agentd_prompt_output_terminal_missing",
                "product terminal record is missing final-output evidence",
            ));
        }
        let key = PromptFinalUseKeyV1::new(&record.thread_id, &record.turn_id)
            .map_err(final_use_store_host_error)?;
        let clear = terminal_clears_stage(&record);
""",
)

# Durable token derivation from append-only dispatch order.
replace_once(
    path,
    """fn dispatch_key(record: &PromptRuntimeDispatchRecordV1) -> PromptRuntimeKey {
""",
    """fn dispatch_fence_token(
    state: &PromptRuntimeState,
    record: &PromptRuntimeDispatchRecordV1,
) -> Result<PromptRuntimeFenceTokenV1, AgentdPromptRuntimeError> {
    let position = state
        .dispatch_order
        .iter()
        .position(|attempt| attempt == &record.attempt_id)
        .ok_or(AgentdPromptRuntimeError::OutputBindingMismatch)?;
    let generation = u64::try_from(position)
        .ok()
        .and_then(|value| value.checked_add(1))
        .ok_or(AgentdPromptRuntimeError::CapacityExceeded)?;
    PromptRuntimeFenceTokenV1::from_dispatch(record, generation)
        .map_err(|_| AgentdPromptRuntimeError::OutputBindingMismatch)
}

fn dispatch_key(record: &PromptRuntimeDispatchRecordV1) -> PromptRuntimeKey {
""",
)

# Stored terminal V2 output evidence; V1 remains readable.
replace_once(
    path,
    """    delivery_observation: Option<StoredObservation>,
    observed_unix_ms: u64,
}
""",
    """    delivery_observation: Option<StoredObservation>,
    #[serde(default)]
    output_terminal: Option<StoredOutputTerminal>,
    observed_unix_ms: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredOutputTerminal {
    fence_token_digest: [u8; 32],
    delivery_state: u8,
    summary: StoredOutputSummary,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredOutputSummary {
    observed_batches: u64,
    observed_bytes: u64,
    allowed_batches: u64,
    allowed_bytes: u64,
    dropped_after_fence_batches: u64,
    dropped_after_fence_bytes: u64,
    last_sequence: u64,
    chain_digest: [u8; 32],
    first_drop_sequence: Option<u64>,
    first_drop_event_digest: Option<[u8; 32]>,
    first_drop_reason_code: Option<String>,
}
""",
)
replace_once(
    path,
    """    if stored.schema != PROMPT_RUNTIME_SCHEMA
        || stored.staged.len() > MAX_STAGED_TURNS
""",
    """    if !matches!(
        stored.schema,
        LEGACY_PROMPT_RUNTIME_SCHEMA | PROMPT_RUNTIME_SCHEMA
    ) || stored.staged.len() > MAX_STAGED_TURNS
""",
)
replace_once(
    path,
    """        delivery_observation: value.delivery_observation.as_ref().map(stored_observation),
        observed_unix_ms: value.observed_unix_ms,
""",
    """        delivery_observation: value.delivery_observation.as_ref().map(stored_observation),
        output_terminal: value.output_terminal.as_ref().map(stored_output_terminal),
        observed_unix_ms: value.observed_unix_ms,
""",
)
replace_once(
    path,
    """        delivery_observation: stored
            .delivery_observation
            .map(restore_observation)
            .transpose()?,
        observed_unix_ms: stored.observed_unix_ms,
""",
    """        delivery_observation: stored
            .delivery_observation
            .map(restore_observation)
            .transpose()?,
        output_terminal: stored
            .output_terminal
            .map(restore_output_terminal)
            .transpose()?,
        observed_unix_ms: stored.observed_unix_ms,
""",
)
replace_once(
    path,
    """fn stored_observation(value: &PromptDeliveryObservationV1) -> StoredObservation {
""",
    """fn stored_output_terminal(value: &PromptRuntimeOutputTerminalV1) -> StoredOutputTerminal {
    StoredOutputTerminal {
        fence_token_digest: value.fence_token_digest.into_array(),
        delivery_state: delivery_state_code(value.delivery_state),
        summary: StoredOutputSummary {
            observed_batches: value.summary.observed_batches,
            observed_bytes: value.summary.observed_bytes,
            allowed_batches: value.summary.allowed_batches,
            allowed_bytes: value.summary.allowed_bytes,
            dropped_after_fence_batches: value.summary.dropped_after_fence_batches,
            dropped_after_fence_bytes: value.summary.dropped_after_fence_bytes,
            last_sequence: value.summary.last_sequence,
            chain_digest: value.summary.chain_digest.into_array(),
            first_drop_sequence: value.summary.first_drop_sequence,
            first_drop_event_digest: value
                .summary
                .first_drop_event_digest
                .map(Digest32::into_array),
            first_drop_reason_code: value.summary.first_drop_reason_code.clone(),
        },
    }
}

fn restore_output_terminal(
    stored: StoredOutputTerminal,
) -> Result<PromptRuntimeOutputTerminalV1, AgentdPromptRuntimeError> {
    let value = PromptRuntimeOutputTerminalV1 {
        fence_token_digest: Digest32::from_array(stored.fence_token_digest),
        delivery_state: decode_delivery_state(stored.delivery_state)?,
        summary: PromptRuntimeOutputSummaryV1 {
            observed_batches: stored.summary.observed_batches,
            observed_bytes: stored.summary.observed_bytes,
            allowed_batches: stored.summary.allowed_batches,
            allowed_bytes: stored.summary.allowed_bytes,
            dropped_after_fence_batches: stored.summary.dropped_after_fence_batches,
            dropped_after_fence_bytes: stored.summary.dropped_after_fence_bytes,
            last_sequence: stored.summary.last_sequence,
            chain_digest: Digest32::from_array(stored.summary.chain_digest),
            first_drop_sequence: stored.summary.first_drop_sequence,
            first_drop_event_digest: stored
                .summary
                .first_drop_event_digest
                .map(Digest32::from_array),
            first_drop_reason_code: stored.summary.first_drop_reason_code,
        },
    };
    value
        .validate()
        .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
    Ok(value)
}

fn stored_observation(value: &PromptDeliveryObservationV1) -> StoredObservation {
""",
)
replace_once(
    path,
    """fn decode_terminal_outcome(
    value: u8,
) -> Result<PromptRuntimeTerminalOutcomeV1, AgentdPromptRuntimeError> {
""",
    """const fn delivery_state_code(value: PromptRuntimeDeliveryStateV1) -> u8 {
    match value {
        PromptRuntimeDeliveryStateV1::RejectedBeforeDispatch => 0,
        PromptRuntimeDeliveryStateV1::DispatchedProviderUnknown => 1,
        PromptRuntimeDeliveryStateV1::ProviderRejected => 2,
        PromptRuntimeDeliveryStateV1::ProviderCompletedOutputFenced => 3,
        PromptRuntimeDeliveryStateV1::PartiallyStreamed => 4,
        PromptRuntimeDeliveryStateV1::FullyObserved => 5,
        PromptRuntimeDeliveryStateV1::RecoveryReconciled => 6,
    }
}

fn decode_delivery_state(
    value: u8,
) -> Result<PromptRuntimeDeliveryStateV1, AgentdPromptRuntimeError> {
    match value {
        0 => Ok(PromptRuntimeDeliveryStateV1::RejectedBeforeDispatch),
        1 => Ok(PromptRuntimeDeliveryStateV1::DispatchedProviderUnknown),
        2 => Ok(PromptRuntimeDeliveryStateV1::ProviderRejected),
        3 => Ok(PromptRuntimeDeliveryStateV1::ProviderCompletedOutputFenced),
        4 => Ok(PromptRuntimeDeliveryStateV1::PartiallyStreamed),
        5 => Ok(PromptRuntimeDeliveryStateV1::FullyObserved),
        6 => Ok(PromptRuntimeDeliveryStateV1::RecoveryReconciled),
        _ => Err(AgentdPromptRuntimeError::CorruptState),
    }
}

fn decode_terminal_outcome(
    value: u8,
) -> Result<PromptRuntimeTerminalOutcomeV1, AgentdPromptRuntimeError> {
""",
)

# Existing source/test terminal literals are legacy-compatible by construction.
for literal_path in [
    "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs",
]:
    value = read(literal_path)
    value = value.replace(
        "\n        observed_unix_ms:",
        "\n        output_terminal: None,\n        observed_unix_ms:",
    )
    write(literal_path, value)

# The source's restored terminal construction and any pre-existing helper
# construction not handled above require the new optional field only when they
# still lack it. This is intentionally narrow.
value = read(path)
needle = """        delivery_observation: Some(observation),
        observed_unix_ms,
"""
if needle in value:
    value = value.replace(
        needle,
        """        delivery_observation: Some(observation),
        output_terminal: None,
        observed_unix_ms,
""",
    )
write(path, value)

print("prompt.registry runtime/output fence source edits applied")
