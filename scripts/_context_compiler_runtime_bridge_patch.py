#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1))


replace_once(
    "codex-rs/ext/hepta-prompt/Cargo.toml",
    "[dependencies]\n",
    "[dependencies]\ncodex-api = { workspace = true }\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "#![forbid(unsafe_code)]\n",
    "#![forbid(unsafe_code)]\n\nmod exact_body;\n\npub use exact_body::PromptRuntimeExactAttemptV2;\nuse exact_body::PromptRuntimeExactBodyObserver;\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "use std::sync::Arc;\n",
    "use std::sync::Arc;\nuse std::sync::OnceLock;\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "use codex_extension_api::ContentItemKind;\n",
    "use codex_api::EncodedRequestBodyObserver;\n"
    "use codex_api::EncodedRequestBodyObserverAttachment;\n"
    "use codex_extension_api::ContentItemKind;\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "use codex_extension_api::ModelProviderTerminal;\n",
    "use codex_extension_api::ModelProviderTerminal;\n"
    "use codex_extension_api::ModelProviderTransport;\n",
)

# Public, payload-bearing object passed only to the embedding-owned callback.
# It is never exposed through the provider-policy DTO.
final_request_struct = r'''
/// Exact canonical provider request observed after JSON encoding and before
/// compression/signing. The callback must complete successfully before Core
/// crosses the physical transport boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeFinalRequestV2 {
    pub attachment: PromptRuntimeAttachmentV1,
    pub attempt: PromptRuntimeExactAttemptV2,
    pub canonical_request: Vec<u8>,
}

'''
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "pub type PromptRuntimePrepareFuture = Pin<\n",
    final_request_struct + "pub type PromptRuntimePrepareFuture = Pin<\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "pub type PromptRuntimeRecordFuture =\n"
    "    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;\n",
    "pub type PromptRuntimeRecordFuture =\n"
    "    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;\n"
    "pub type PromptRuntimeFinalRequestFuture =\n"
    "    Pin<Box<dyn Future<Output = Result<(), PromptRuntimeHostError>> + Send + 'static>>;\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "type PromptRuntimeRecordFn =\n"
    "    dyn Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static;\n",
    "type PromptRuntimeRecordFn =\n"
    "    dyn Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static;\n"
    "type PromptRuntimeFinalRequestFn = dyn Fn(PromptRuntimeFinalRequestV2)\n"
    "        -> PromptRuntimeFinalRequestFuture\n"
    "    + Send\n"
    "    + Sync\n"
    "    + 'static;\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "    record: Arc<PromptRuntimeRecordFn>,\n",
    "    record: Arc<PromptRuntimeRecordFn>,\n"
    "    final_request: Option<Arc<PromptRuntimeFinalRequestFn>>,\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            record: Arc::new(record),\n"
    "        })",
    "            record: Arc::new(record),\n"
    "            final_request: None,\n"
    "        })",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "    async fn prepare(\n",
    "    #[must_use]\n"
    "    pub fn with_final_request_observer<F>(mut self, observer: F) -> Self\n"
    "    where\n"
    "        F: Fn(PromptRuntimeFinalRequestV2) -> PromptRuntimeFinalRequestFuture\n"
    "            + Send\n"
    "            + Sync\n"
    "            + 'static,\n"
    "    {\n"
    "        self.final_request = Some(Arc::new(observer));\n"
    "        self\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    fn has_final_request_observer(&self) -> bool {\n"
    "        self.final_request.is_some()\n"
    "    }\n\n"
    "    pub(crate) async fn observe_final_request(\n"
    "        &self,\n"
    "        request: PromptRuntimeFinalRequestV2,\n"
    "    ) -> Result<(), PromptRuntimeHostError> {\n"
    "        let observer = self.final_request.as_ref().ok_or_else(|| {\n"
    "            PromptRuntimeHostError::new(\n"
    "                \"prompt_runtime_exact_observer_missing\",\n"
    "                \"exact final request observer is not installed\",\n"
    "            )\n"
    "        })?;\n"
    "        observer(request).await\n"
    "    }\n\n"
    "    async fn prepare(\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            .field(\"capability_id\", &self.capability_id)\n",
    "            .field(\"capability_id\", &self.capability_id)\n"
    "            .field(\"exact_final_request\", &self.final_request.is_some())\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            && Arc::ptr_eq(&self.record, &other.record)\n",
    "            && Arc::ptr_eq(&self.record, &other.record)\n"
    "            && match (&self.final_request, &other.final_request) {\n"
    "                (None, None) => true,\n"
    "                (Some(left), Some(right)) => Arc::ptr_eq(left, right),\n"
    "                _ => false,\n"
    "            }\n",
)

# Retain exactly one observer instance for the turn so the context contributor,
# provider policy, and Core body callback share one state machine.
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "struct PromptRuntimeTurnState {\n"
    "    resolved: Mutex<Option<ResolvedAttachment>>,\n"
    "    injected: AtomicBool,\n"
    "}",
    "struct PromptRuntimeTurnState {\n"
    "    resolved: Mutex<Option<ResolvedAttachment>>,\n"
    "    exact_observer: OnceLock<Arc<PromptRuntimeExactBodyObserver>>,\n"
    "    observer_conflict: AtomicBool,\n"
    "    injected: AtomicBool,\n"
    "}",
)

old_context_ready = r'''            let state = input
                .turn_store
                .get_or_init(PromptRuntimeTurnState::default);
            state.injected.store(true, Ordering::Release);
            attachment
                .developer_fragments
'''
new_context_ready = r'''            let state = input
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
                    .is_some_and(|existing| {
                        Arc::ptr_eq(&existing.observer(), &observer_trait)
                    });
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
'''
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    old_context_ready,
    new_context_ready,
)

# Bind the secret-free physical attempt before the durable dispatch claim. If
# dispatch persistence fails, cancel the binding because no body can be sent.
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            if !state.injected.load(Ordering::Acquire) {\n",
    "            if state.observer_conflict.load(Ordering::Acquire) {\n"
    "                return Ok(ModelProviderPolicyDecision::Block {\n"
    "                    reason_code: \"prompt_runtime_exact_observer_conflict\".to_owned(),\n"
    "                    message: \"another exact request observer already owns this turn\"\n"
    "                        .to_owned(),\n"
    "                });\n"
    "            }\n"
    "            if !state.injected.load(Ordering::Acquire) {\n",
)
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    "            parse_stable_id(input.attempt_id, \"attempt id\")?;\n"
    "            parse_stable_id(input.thread_id, \"thread id\")?;\n"
    "            let dispatch_record = PromptRuntimeDispatchRecordV1 {",
    "            parse_stable_id(input.attempt_id, \"attempt id\")?;\n"
    "            parse_stable_id(input.thread_id, \"thread id\")?;\n"
    "            let exact_observer = if self.host.has_final_request_observer() {\n"
    "                if input.transport != ModelProviderTransport::Http {\n"
    "                    return Ok(ModelProviderPolicyDecision::Block {\n"
    "                        reason_code: \"prompt_runtime_exact_body_requires_http\".to_owned(),\n"
    "                        message: \"exact final request proof is defined at the canonical HTTP body boundary\"\n"
    "                            .to_owned(),\n"
    "                    });\n"
    "                }\n"
    "                let observer = state.exact_observer.get().cloned().ok_or_else(|| {\n"
    "                    ModelProviderPolicyError::new(\n"
    "                        \"prompt_runtime_exact_observer_missing\",\n"
    "                        \"context assembly did not install the exact body observer\",\n"
    "                    )\n"
    "                })?;\n"
    "                let attempt = PromptRuntimeExactAttemptV2 {\n"
    "                    thread_id: input.thread_id.to_owned(),\n"
    "                    turn_id: input.turn_id.to_owned(),\n"
    "                    attempt_id: input.attempt_id.to_owned(),\n"
    "                    request_binding_id: input.request_binding_id.to_owned(),\n"
    "                    provider_id: input.provider_id.to_owned(),\n"
    "                    model: input.model.to_owned(),\n"
    "                    provider_wire_semantic_digest: provider_request_digest,\n"
    "                };\n"
    "                observer.bind_attempt(attempt.clone()).map_err(|error| {\n"
    "                    ModelProviderPolicyError::new(\n"
    "                        error.reason_code().to_owned(),\n"
    "                        error.detail().to_owned(),\n"
    "                    )\n"
    "                })?;\n"
    "                Some((observer, attempt))\n"
    "            } else {\n"
    "                None\n"
    "            };\n"
    "            let dispatch_record = PromptRuntimeDispatchRecordV1 {",
)
old_dispatch = r'''            self.host.dispatch(dispatch_record).await.map_err(|error| {
                ModelProviderPolicyError::new(
                    error.reason_code().to_owned(),
                    error.detail().to_owned(),
                )
            })?;
'''
new_dispatch = r'''            if let Err(error) = self.host.dispatch(dispatch_record).await {
                if let Some((observer, attempt)) = &exact_observer {
                    observer.cancel_attempt(attempt);
                }
                return Err(ModelProviderPolicyError::new(
                    error.reason_code().to_owned(),
                    error.detail().to_owned(),
                ));
            }
'''
replace_once(
    "codex-rs/ext/hepta-prompt/src/lib.rs",
    old_dispatch,
    new_dispatch,
)
