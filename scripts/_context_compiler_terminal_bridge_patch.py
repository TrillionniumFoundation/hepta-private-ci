#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:110]!r}")
    file_path.write_text(text.replace(old, new, 1))


# Compatibility adapter exports the exact V2 host seam to Agentd without making
# Agentd depend directly on the extension implementation crate.
replace_once(
    "codex-rs/hepta-codex-adapter/src/lib.rs",
    "pub use runtime_prompt::PromptRuntimeDispatchRecordV1;\n",
    "pub use runtime_prompt::PromptRuntimeDispatchRecordV1;\n"
    "pub use runtime_prompt::PromptRuntimeExactAttemptV2;\n"
    "pub use runtime_prompt::PromptRuntimeFinalRequestFuture;\n"
    "pub use runtime_prompt::PromptRuntimeFinalRequestV2;\n"
    "pub use runtime_prompt::PromptRuntimeFinalTerminalFuture;\n"
    "pub use runtime_prompt::PromptRuntimeFinalTerminalV2;\n",
)
replace_once(
    "codex-rs/hepta-codex-adapter/src/lib.rs",
    "pub use runtime_prompt::PromptRuntimePrepareRequest;\n",
    "pub use runtime_prompt::PromptRuntimePrepareRequest;\n"
    "pub use runtime_prompt::PromptRuntimeProviderTerminalV2;\n"
    "pub use runtime_prompt::PromptRuntimeRequestKindV2;\n"
    "pub use runtime_prompt::PromptRuntimeTransportV2;\n",
)

# Exact host-side request/transport enums are independent from extension API
# DTOs and can be persisted by the product owner.
exact_enums = r'''
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

'''
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "/// Exact canonical provider request observed after JSON encoding and before\n",
    exact_enums + "/// Exact canonical provider request observed after JSON encoding and before\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "pub type PromptRuntimeFinalRequestFuture =\n"
    "    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;\n",
    "pub type PromptRuntimeFinalRequestFuture =\n"
    "    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;\n"
    "pub type PromptRuntimeFinalTerminalFuture =\n"
    "    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "type PromptRuntimeFinalRequestFn = dyn Fn(PromptRuntimeFinalRequestV2)\n"
    "        -> PromptRuntimeFinalRequestFuture\n"
    "    + Send\n"
    "    + Sync\n"
    "    + 'static;\n",
    "type PromptRuntimeFinalRequestFn = dyn Fn(PromptRuntimeFinalRequestV2)\n"
    "        -> PromptRuntimeFinalRequestFuture\n"
    "    + Send\n"
    "    + Sync\n"
    "    + 'static;\n"
    "type PromptRuntimeFinalTerminalFn = dyn Fn(PromptRuntimeFinalTerminalV2)\n"
    "        -> PromptRuntimeFinalTerminalFuture\n"
    "    + Send\n"
    "    + Sync\n"
    "    + 'static;\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "    final_request: Option<Arc<PromptRuntimeFinalRequestFn>>,\n",
    "    final_request: Option<Arc<PromptRuntimeFinalRequestFn>>,\n"
    "    final_terminal: Option<Arc<PromptRuntimeFinalTerminalFn>>,\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            final_request: None,\n",
    "            final_request: None,\n"
    "            final_terminal: None,\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "    #[must_use]\n"
    "    fn has_final_request_observer(&self) -> bool {",
    "    #[must_use]\n"
    "    pub fn with_final_terminal_observer<F>(mut self, observer: F) -> Self\n"
    "    where\n"
    "        F: Fn(PromptRuntimeFinalTerminalV2) -> PromptRuntimeFinalTerminalFuture\n"
    "            + Send\n"
    "            + Sync\n"
    "            + 'static,\n"
    "    {\n"
    "        self.final_terminal = Some(Arc::new(observer));\n"
    "        self\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    fn has_final_request_observer(&self) -> bool {",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "    pub(crate) async fn observe_final_request(\n",
    "    #[must_use]\n"
    "    fn has_final_terminal_observer(&self) -> bool {\n"
    "        self.final_terminal.is_some()\n"
    "    }\n\n"
    "    pub(crate) async fn observe_final_request(\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "    async fn prepare(\n",
    "    async fn observe_final_terminal(\n"
    "        &self,\n"
    "        terminal: PromptRuntimeFinalTerminalV2,\n"
    "    ) -> Result<(), PromptRuntimeHostError> {\n"
    "        let observer = self.final_terminal.as_ref().ok_or_else(|| {\n"
    "            PromptRuntimeHostError::new(\n"
    "                \"prompt_runtime_exact_terminal_observer_missing\",\n"
    "                \"exact terminal observer is not installed\",\n"
    "            )\n"
    "        })?;\n"
    "        observer(terminal).await\n"
    "    }\n\n"
    "    async fn prepare(\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            .field(\"exact_final_request\", &self.final_request.is_some())\n",
    "            .field(\"exact_final_request\", &self.final_request.is_some())\n"
    "            .field(\"exact_final_terminal\", &self.final_terminal.is_some())\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            && match (&self.final_request, &other.final_request) {\n"
    "                (None, None) => true,\n"
    "                (Some(left), Some(right)) => Arc::ptr_eq(left, right),\n"
    "                _ => false,\n"
    "            }\n",
    "            && match (&self.final_request, &other.final_request) {\n"
    "                (None, None) => true,\n"
    "                (Some(left), Some(right)) => Arc::ptr_eq(left, right),\n"
    "                _ => false,\n"
    "            }\n"
    "            && match (&self.final_terminal, &other.final_terminal) {\n"
    "                (None, None) => true,\n"
    "                (Some(left), Some(right)) => Arc::ptr_eq(left, right),\n"
    "                _ => false,\n"
    "            }\n",
)

# Populate the complete attempt from the already authenticated provider-policy
# seam. Every digest remains secret-free and is parsed before binding.
old_attempt = r'''                let attempt = PromptRuntimeExactAttemptV2 {
                    thread_id: input.thread_id.to_owned(),
                    turn_id: input.turn_id.to_owned(),
                    attempt_id: input.attempt_id.to_owned(),
                    request_binding_id: input.request_binding_id.to_owned(),
                    provider_id: input.provider_id.to_owned(),
                    model: input.model.to_owned(),
                    provider_wire_semantic_digest: provider_request_digest,
                };
'''
new_attempt = r'''                let request_kind = match input.request_kind {
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
'''
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    old_attempt,
    new_attempt,
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "                    dispatch_unix_ms,\n"
    "                }),",
    "                    dispatch_unix_ms,\n"
    "                    exact_attempt: exact_observer.map(|(_, attempt)| attempt),\n"
    "                }),",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "    dispatch_unix_ms: u64,\n"
    "}",
    "    dispatch_unix_ms: u64,\n"
    "    exact_attempt: Option<PromptRuntimeExactAttemptV2>,\n"
    "}",
)

# Preserve all provider terminal digests before the V1 projection. Persisting the
# exact V2 receipt precedes compatibility V1 finalization; a later V1 failure
# leaves the durable dispatch unresolved and therefore cannot authorize retry.
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            let (outcome, terminal_reason_code, end_turn, delivery_observation) =\n"
    "                self.map_terminal(terminal).map_err(runtime_policy_error)?;",
    "            let exact_terminal = self\n"
    "                .exact_attempt\n"
    "                .as_ref()\n"
    "                .map(|attempt| {\n"
    "                    map_exact_terminal(&terminal).map(|terminal| PromptRuntimeFinalTerminalV2 {\n"
    "                        attachment: self.attachment.clone(),\n"
    "                        attempt: attempt.clone(),\n"
    "                        terminal,\n"
    "                        observed_unix_ms,\n"
    "                    })\n"
    "                })\n"
    "                .transpose()\n"
    "                .map_err(runtime_policy_error)?;\n"
    "            let (outcome, terminal_reason_code, end_turn, delivery_observation) =\n"
    "                self.map_terminal(terminal).map_err(runtime_policy_error)?;",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            record.validate().map_err(runtime_policy_error)?;\n"
    "            self.host.record(record).await.map_err(|error| {",
    "            record.validate().map_err(runtime_policy_error)?;\n"
    "            if let Some(exact_terminal) = exact_terminal {\n"
    "                if !self.host.has_final_terminal_observer() {\n"
    "                    return Err(ModelProviderPolicyError::new(\n"
    "                        \"prompt_runtime_exact_terminal_observer_missing\",\n"
    "                        \"exact request proof was active without an exact terminal owner\",\n"
    "                    ));\n"
    "                }\n"
    "                self.host.observe_final_terminal(exact_terminal).await.map_err(|error| {\n"
    "                    ModelProviderPolicyError::new(\n"
    "                        error.reason_code().to_owned(),\n"
    "                        error.detail().to_owned(),\n"
    "                    )\n"
    "                })?;\n"
    "            }\n"
    "            self.host.record(record).await.map_err(|error| {",
)

terminal_helpers = r'''
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
        Digest32::from_str(digest.as_str())
            .map_err(|_| PromptRuntimeError::InvalidTerminalRecord)
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
            partial_response_digest: partial_response_sha256
                .as_ref()
                .map(parse)
                .transpose()?,
        }),
    }
}

'''
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "fn rejection_reason(reason_code: &str) -> Result<PromptDeliveryRejectReasonV1, PromptRuntimeError> {",
    terminal_helpers + "fn rejection_reason(reason_code: &str) -> Result<PromptDeliveryRejectReasonV1, PromptRuntimeError> {",
)
