use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use codex_extension_api::ContextContributor;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderExactTokenizationState;
use codex_extension_api::ModelProviderExactTokenizerHost;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::PromptFragment;
use codex_extension_api::TurnContextContributionInput;

use crate::PromptRuntimeDispatchFuture;
use crate::PromptRuntimeDispatchRecordV1;
use crate::PromptRuntimeError;
use crate::PromptRuntimePrepareFuture;
use crate::PromptRuntimePrepareRequest;
use crate::PromptRuntimeRecordFuture;
use crate::PromptRuntimeTerminalRecordV1;
use crate::compatibility;

/// Host capability for the source-bound prompt runtime plus the exact model
/// tokenizer that must see the frozen canonical provider request.
#[derive(Clone)]
pub struct PromptRuntimeHost {
    runtime: compatibility::PromptRuntimeHost,
    exact_tokenizer: Option<ModelProviderExactTokenizerHost>,
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
        Ok(Self {
            runtime: compatibility::PromptRuntimeHost::new(
                capability_id,
                prepare,
                dispatch,
                record,
            )?,
            exact_tokenizer: None,
        })
    }

    pub fn new_provider_bound<P, D, R>(
        capability_id: impl Into<String>,
        prepare: P,
        dispatch: D,
        record: R,
        exact_tokenizer: ModelProviderExactTokenizerHost,
    ) -> Result<Self, PromptRuntimeError>
    where
        P: Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static,
        D: Fn(PromptRuntimeDispatchRecordV1) -> PromptRuntimeDispatchFuture + Send + Sync + 'static,
        R: Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static,
    {
        Ok(Self::new(capability_id, prepare, dispatch, record)?
            .with_exact_tokenizer(exact_tokenizer))
    }

    #[must_use]
    pub fn with_exact_tokenizer(
        mut self,
        exact_tokenizer: ModelProviderExactTokenizerHost,
    ) -> Self {
        self.exact_tokenizer = Some(exact_tokenizer);
        self
    }

    #[must_use]
    pub fn exact_tokenizer_capability_id(&self) -> Option<&str> {
        self.exact_tokenizer
            .as_ref()
            .map(ModelProviderExactTokenizerHost::capability_id)
    }
}

impl fmt::Debug for PromptRuntimeHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRuntimeHost")
            .field("runtime", &self.runtime)
            .field(
                "exact_tokenizer_capability_id",
                &self.exact_tokenizer_capability_id(),
            )
            .finish()
    }
}

impl PartialEq for PromptRuntimeHost {
    fn eq(&self, other: &Self) -> bool {
        self.runtime == other.runtime
            && self.exact_tokenizer_capability_id()
                == other.exact_tokenizer_capability_id()
    }
}

impl Eq for PromptRuntimeHost {}

pub fn install_prompt_runtime<C: Sync>(
    builder: &mut ExtensionRegistryBuilder<C>,
    host: PromptRuntimeHost,
) {
    let PromptRuntimeHost {
        runtime,
        exact_tokenizer,
    } = host;
    compatibility::install_prompt_runtime(builder, runtime);
    if let Some(exact_tokenizer) = exact_tokenizer {
        let guard = Arc::new(ProviderBoundTokenizerGuard { exact_tokenizer });
        builder.prompt_contributor(guard.clone());
        builder.model_provider_policy_contributor(guard);
    }
}

struct ProviderBoundTokenizerGuard {
    exact_tokenizer: ModelProviderExactTokenizerHost,
}

impl ContextContributor for ProviderBoundTokenizerGuard {
    fn contribute_turn_context<'a>(
        &'a self,
        input: TurnContextContributionInput<'a>,
    ) -> ExtensionFuture<'a, Vec<PromptFragment>> {
        Box::pin(async move {
            let expected_capability = self.exact_tokenizer.capability_id();
            input.turn_store.insert_if(
                self.exact_tokenizer.clone(),
                |current: Option<&ModelProviderExactTokenizerHost>| {
                    current.is_none_or(|current| {
                        current.capability_id() == expected_capability
                    })
                },
            );
            Vec::new()
        })
    }
}

impl ModelProviderPolicyContributor for ProviderBoundTokenizerGuard {
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
                    lease: Box::new(ExactTokenizerNoopLease),
                });
            }
            let Some(installed) = input
                .turn_store
                .get::<ModelProviderExactTokenizerHost>()
            else {
                return Ok(block(
                    "prompt_runtime_exact_tokenizer_missing",
                    "source-bound prompt delivery requires an exact tokenizer host",
                ));
            };
            if installed.capability_id() != self.exact_tokenizer.capability_id() {
                return Ok(block(
                    "prompt_runtime_exact_tokenizer_conflict",
                    "turn tokenizer capability differs from the prompt runtime authority",
                ));
            }
            let Some(state) = input
                .turn_store
                .get::<ModelProviderExactTokenizationState>()
            else {
                return Ok(block(
                    "prompt_runtime_exact_tokenization_missing",
                    "the frozen provider request was not tokenized",
                ));
            };
            let Some(receipt) = state.get(input.attempt_id) else {
                return Ok(block(
                    "prompt_runtime_exact_tokenization_missing",
                    "no exact tokenization receipt exists for this physical attempt",
                ));
            };
            if receipt.tokenizer_capability_id()
                != self.exact_tokenizer.capability_id()
                || receipt.descriptor().provider_id() != input.provider_id
                || receipt.descriptor().model() != input.model
                || receipt.wire_semantic_sha256().as_str()
                    != input.wire_semantic_sha256.as_str()
                || receipt.final_request_sha256().as_str()
                    != input.wire_semantic_sha256.as_str()
                || receipt.token_count() == 0
                || receipt.final_request_bytes() == 0
            {
                return Ok(block(
                    "prompt_runtime_exact_tokenization_binding_mismatch",
                    "exact tokenization receipt does not bind this provider request",
                ));
            }
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(ExactTokenizerNoopLease),
            })
        })
    }
}

fn block(reason_code: &str, message: &str) -> ModelProviderPolicyDecision {
    ModelProviderPolicyDecision::Block {
        reason_code: reason_code.to_owned(),
        message: message.to_owned(),
    }
}

struct ExactTokenizerNoopLease;

impl ModelProviderAttemptLease for ExactTokenizerNoopLease {
    fn finish(
        self: Box<Self>,
        _terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(std::future::ready(Ok(())))
    }
}
