from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


contributors = "codex-rs/ext/extension-api/src/contributors.rs"
replace_once(
    contributors,
    "pub use model_provider_policy::ModelProviderInvocationInput;\n"
    "pub use model_provider_policy::ModelProviderPolicyDecision;\n",
    "pub use model_provider_policy::ModelProviderInvocationInput;\n"
    "pub use model_provider_policy::ModelProviderOutputBatch;\n"
    "pub use model_provider_policy::ModelProviderOutputDecision;\n"
    "pub use model_provider_policy::ModelProviderPolicyDecision;\n",
)

extension_api = "codex-rs/ext/extension-api/src/lib.rs"
replace_once(
    extension_api,
    "pub use contributors::ModelProviderInvocationInput;\n"
    "pub use contributors::ModelProviderPolicyContributor;\n",
    "pub use contributors::ModelProviderInvocationInput;\n"
    "pub use contributors::ModelProviderOutputBatch;\n"
    "pub use contributors::ModelProviderOutputDecision;\n"
    "pub use contributors::ModelProviderPolicyContributor;\n",
)

cargo = "codex-rs/ext/hepta-prompt/Cargo.toml"
replace_once(
    cargo,
    'tokio = { workspace = true, features = ["sync"] }\n',
    'tokio = { workspace = true, features = ["rt", "sync"] }\n',
)

prompt = Path("codex-rs/ext/hepta-prompt/src/lib.rs")
text = prompt.read_text(encoding="utf-8")
old_imports = "use std::sync::Arc;\nuse std::sync::atomic::AtomicBool;\n"
new_imports = (
    "use std::sync::Arc;\n"
    "use std::sync::Mutex as StdMutex;\n"
    "use std::sync::PoisonError;\n"
    "use std::sync::atomic::AtomicBool;\n"
)
if text.count(old_imports) != 1:
    raise SystemExit("prompt imports changed unexpectedly")
text = text.replace(old_imports, new_imports, 1)
if text.count("use tokio::sync::Mutex;\n") != 1:
    raise SystemExit("tokio mutex import changed unexpectedly")
text = text.replace("use tokio::sync::Mutex;\n", "use tokio::sync::oneshot;\n", 1)

start = text.index("#[derive(Clone)]\nenum ResolvedAttachment")
end = text.index("\nimpl ContextContributor for PromptRuntimeExtension", start)
replacement = r'''#[derive(Clone)]
enum ResolvedAttachment {
    None,
    Ready(PromptRuntimeAttachmentV1),
    Failed(PromptRuntimeHostError),
}

#[derive(Default)]
enum AttachmentResolutionState {
    #[default]
    Vacant,
    Stable(ResolvedAttachment),
    Resolving {
        waiters: Vec<oneshot::Sender<ResolvedAttachment>>,
    },
}

#[derive(Default)]
struct PromptRuntimeTurnState {
    resolution: StdMutex<AttachmentResolutionState>,
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
        let (receiver, previous) = {
            let mut resolution = state
                .resolution
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            match &mut *resolution {
                AttachmentResolutionState::Stable(value)
                    if !matches!(value, ResolvedAttachment::Ready(_)) =>
                {
                    return value.clone();
                }
                AttachmentResolutionState::Resolving { waiters } => {
                    let (sender, receiver) = oneshot::channel();
                    waiters.push(sender);
                    (receiver, None)
                }
                AttachmentResolutionState::Vacant
                | AttachmentResolutionState::Stable(ResolvedAttachment::Ready(_)) => {
                    let previous = match &*resolution {
                        AttachmentResolutionState::Stable(ResolvedAttachment::Ready(value)) => {
                            Some(value.clone())
                        }
                        _ => None,
                    };
                    let (sender, receiver) = oneshot::channel();
                    *resolution = AttachmentResolutionState::Resolving {
                        waiters: vec![sender],
                    };
                    (receiver, Some(previous))
                }
                AttachmentResolutionState::Stable(_) => {
                    unreachable!("terminal attachment states returned above")
                }
            }
        };

        if let Some(previous) = previous {
            Self::spawn_resolution(
                self.host.clone(),
                Arc::clone(&state),
                PromptRuntimePrepareRequest {
                    thread_id,
                    turn_id,
                    model_context_window,
                },
                previous,
            );
        }

        receiver.await.unwrap_or_else(|_| {
            ResolvedAttachment::Failed(PromptRuntimeHostError::new(
                "prompt_runtime_resolution_cancelled",
                "prompt attachment resolution did not reach a terminal state",
            ))
        })
    }

    fn spawn_resolution(
        host: PromptRuntimeHost,
        state: Arc<PromptRuntimeTurnState>,
        request: PromptRuntimePrepareRequest,
        previous: Option<PromptRuntimeAttachmentV1>,
    ) {
        tokio::spawn(async move {
            let prepared = match host.prepare(request).await {
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
            let value = match (previous, prepared) {
                (Some(previous), ResolvedAttachment::Ready(current))
                    if previous != current =>
                {
                    ResolvedAttachment::Failed(PromptRuntimeHostError::new(
                        "prompt_runtime_cached_binding_changed",
                        "an injected attachment changed; recompile in a fresh turn",
                    ))
                }
                (Some(_), ResolvedAttachment::None) => {
                    ResolvedAttachment::Failed(PromptRuntimeHostError::new(
                        "prompt_runtime_cached_attachment_removed",
                        "the owner no longer exposes the injected attachment",
                    ))
                }
                (_, value) => value,
            };
            let waiters = {
                let mut resolution = state
                    .resolution
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner);
                let AttachmentResolutionState::Resolving { waiters } =
                    std::mem::replace(
                        &mut *resolution,
                        AttachmentResolutionState::Stable(value.clone()),
                    )
                else {
                    unreachable!("only the active resolver may publish its result");
                };
                waiters
            };
            for waiter in waiters {
                let _ = waiter.send(value.clone());
            }
        });
    }
}
'''
text = text[:start] + replacement + text[end:]

old_finish = '''            let (outcome, terminal_reason_code, end_turn, delivery_observation) =
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
            };'''
new_finish = '''            let resolution = self.map_terminal(terminal).map_err(runtime_policy_error)?;
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
                outcome: resolution.outcome,
                end_turn: resolution.end_turn,
                terminal_reason_code: resolution.terminal_reason_code,
                delivery_observation: resolution.delivery_observation,
                observed_unix_ms,
            };'''
if text.count(old_finish) != 1:
    raise SystemExit("prompt finish block changed unexpectedly")
text = text.replace(old_finish, new_finish, 1)

marker = "impl PromptRuntimeAttemptLease {\n"
typed = '''struct PromptRuntimeTerminalResolution {
    outcome: PromptRuntimeTerminalOutcomeV1,
    terminal_reason_code: Option<String>,
    end_turn: Option<bool>,
    delivery_observation: Option<PromptDeliveryObservationV1>,
}

'''
if text.count(marker) != 1:
    raise SystemExit("terminal impl marker changed unexpectedly")
text = text.replace(marker, typed + marker, 1)

pattern = re.compile(
    r"    fn map_terminal\(\n"
    r"        &self,\n"
    r"        terminal: ModelProviderTerminal,\n"
    r"    \) -> Result<.*?"
    r"\n    }\n}\n\npub fn install_prompt_runtime",
    re.DOTALL,
)
new_map = '''    fn map_terminal(
        &self,
        terminal: ModelProviderTerminal,
    ) -> Result<PromptRuntimeTerminalResolution, PromptRuntimeError> {
        let resolution = match terminal {
            ModelProviderTerminal::Completed { end_turn, .. } => {
                PromptRuntimeTerminalResolution {
                    outcome: PromptRuntimeTerminalOutcomeV1::Delivered,
                    terminal_reason_code: None,
                    end_turn,
                    delivery_observation: Some(self.delivery_observation(true, None)?),
                }
            }
            ModelProviderTerminal::Rejected { reason_code } => {
                let rejection_reason = rejection_reason(&reason_code)?;
                PromptRuntimeTerminalResolution {
                    outcome: PromptRuntimeTerminalOutcomeV1::Rejected,
                    terminal_reason_code: Some(reason_code),
                    end_turn: None,
                    delivery_observation: Some(
                        self.delivery_observation(false, Some(rejection_reason))?,
                    ),
                }
            }
            ModelProviderTerminal::NotDispatched { reason_code } => {
                PromptRuntimeTerminalResolution {
                    outcome: PromptRuntimeTerminalOutcomeV1::NotDispatched,
                    terminal_reason_code: Some(reason_code),
                    end_turn: None,
                    delivery_observation: None,
                }
            }
            ModelProviderTerminal::Indeterminate { reason_code, .. } => {
                PromptRuntimeTerminalResolution {
                    outcome: PromptRuntimeTerminalOutcomeV1::Indeterminate,
                    terminal_reason_code: Some(reason_code),
                    end_turn: None,
                    delivery_observation: None,
                }
            }
            ModelProviderTerminal::CompletedUnary { .. } => {
                PromptRuntimeTerminalResolution {
                    outcome: PromptRuntimeTerminalOutcomeV1::Indeterminate,
                    terminal_reason_code: Some(
                        "unexpected_unary_terminal_for_turn".to_owned(),
                    ),
                    end_turn: None,
                    delivery_observation: None,
                }
            }
        };
        Ok(resolution)
    }
}

pub fn install_prompt_runtime'''
text, count = pattern.subn(new_map, text, count=1)
if count != 1:
    raise SystemExit("terminal mapping function changed unexpectedly")
prompt.write_text(text, encoding="utf-8")

tests = Path("codex-rs/ext/hepta-prompt/src/lib_tests.rs")
test_text = tests.read_text(encoding="utf-8")
addition = r'''

#[tokio::test]
async fn concurrent_initial_resolution_is_single_flight() {
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let counter = Arc::clone(&calls);
    let prepared = attachment();
    let host = PromptRuntimeHost::new(
        "prompt-runtime-single-flight",
        move |_| {
            counter.fetch_add(1, Ordering::AcqRel);
            let prepared = prepared.clone();
            Box::pin(async move {
                tokio::task::yield_now().await;
                Ok(Some(prepared))
            })
        },
        |_| Box::pin(std::future::ready(Ok(()))),
        |_| Box::pin(std::future::ready(Ok(()))),
    )
    .unwrap_or_else(|error| panic!("host: {error}"));
    let extension = PromptRuntimeExtension { host };
    let (_, thread_store, turn_store) = stores();
    let first = extension.resolve(
        thread_store.level_id().to_owned(),
        turn_store.level_id().to_owned(),
        None,
        &turn_store,
    );
    let second = extension.resolve(
        thread_store.level_id().to_owned(),
        turn_store.level_id().to_owned(),
        None,
        &turn_store,
    );
    let (first, second) = tokio::join!(first, second);
    assert!(matches!(first, ResolvedAttachment::Ready(_)));
    assert!(matches!(second, ResolvedAttachment::Ready(_)));
    assert_eq!(calls.load(Ordering::Acquire), 1);
}
'''
if "concurrent_initial_resolution_is_single_flight" in test_text:
    raise SystemExit("single-flight test already exists")
tests.write_text(test_text.rstrip() + addition + "\n", encoding="utf-8")
