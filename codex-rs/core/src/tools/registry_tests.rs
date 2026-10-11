use super::*;
use crate::hook_mcp_executor::CoreHookMcpExecutor;
use crate::session::session::Session;
use crate::session::step_context::StepContext;
use codex_mcp::McpRuntime;
use codex_protocol::DEFAULT_FUNCTION_NAMESPACE;
use futures::future::BoxFuture;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct TestHandler {
    tool_name: codex_tools::ToolName,
}

impl ToolExecutor<ToolInvocation> for TestHandler {
    fn tool_name(&self) -> codex_tools::ToolName {
        self.tool_name.clone()
    }

    fn spec(&self) -> codex_tools::ToolSpec {
        test_spec(&self.tool_name)
    }

    fn handle(&self, _invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async {
            Ok(
                Box::new(crate::tools::context::FunctionToolOutput::from_text(
                    "ok".to_string(),
                    Some(true),
                )) as Box<dyn crate::tools::context::ToolOutput>,
            )
        })
    }
}

impl CoreToolRuntime for TestHandler {}

struct ReadinessTestHandler {
    handler: TestHandler,
    readiness_waits: Arc<AtomicUsize>,
}

impl ToolExecutor<ToolInvocation> for ReadinessTestHandler {
    fn tool_name(&self) -> codex_tools::ToolName {
        self.handler.tool_name()
    }

    fn spec(&self) -> codex_tools::ToolSpec {
        self.handler.spec()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        self.handler.handle(invocation)
    }
}

impl CoreToolRuntime for ReadinessTestHandler {
    fn wait_until_ready<'a>(&'a self, _session: &'a Arc<Session>) -> Option<BoxFuture<'a, ()>> {
        Some(Box::pin(async {
            self.readiness_waits.fetch_add(1, Ordering::Relaxed);
        }))
    }
}

#[derive(Clone)]
enum LifecycleTestResult {
    Ok { success: bool },
    Err,
}

struct LifecycleTestHandler {
    tool_name: codex_tools::ToolName,
    result: LifecycleTestResult,
}

impl ToolExecutor<ToolInvocation> for LifecycleTestHandler {
    fn tool_name(&self) -> codex_tools::ToolName {
        self.tool_name.clone()
    }

    fn spec(&self) -> codex_tools::ToolSpec {
        test_spec(&self.tool_name)
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        assert_eq!(
            invocation.tool_name,
            self.tool_name.clone().with_default_namespace()
        );
        Box::pin(self.handle_call())
    }
}

impl LifecycleTestHandler {
    async fn handle_call(
        &self,
    ) -> Result<Box<dyn crate::tools::context::ToolOutput>, FunctionCallError> {
        match self.result.clone() {
            LifecycleTestResult::Ok { success } => Ok(Box::new(
                crate::tools::context::FunctionToolOutput::from_text(
                    "ok".to_string(),
                    Some(success),
                ),
            )
                as Box<dyn crate::tools::context::ToolOutput>),
            LifecycleTestResult::Err => Err(FunctionCallError::RespondToModel(
                "handler failed".to_string(),
            )),
        }
    }
}

impl CoreToolRuntime for LifecycleTestHandler {}

struct CountingTestHandler {
    handler: LifecycleTestHandler,
    calls: Arc<AtomicUsize>,
}

impl ToolExecutor<ToolInvocation> for CountingTestHandler {
    fn tool_name(&self) -> codex_tools::ToolName {
        self.handler.tool_name()
    }

    fn spec(&self) -> codex_tools::ToolSpec {
        self.handler.spec()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        self.handler.handle(invocation)
    }
}

impl CoreToolRuntime for CountingTestHandler {}

fn test_spec(tool_name: &codex_tools::ToolName) -> codex_tools::ToolSpec {
    codex_tools::ToolSpec::Function(codex_tools::ResponsesApiTool {
        name: tool_name.name.clone(),
        description: "Test tool.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: codex_tools::JsonSchema::default(),
        output_schema: None,
    })
}

#[derive(Debug, PartialEq, Eq)]
enum RecordedToolLifecycle {
    Start {
        call_id: String,
        tool_name: codex_tools::ToolName,
    },
    Finish {
        call_id: String,
        tool_name: codex_tools::ToolName,
        outcome: codex_extension_api::ToolCallOutcome,
    },
}

struct ToolLifecycleRecorder {
    records: Arc<std::sync::Mutex<Vec<RecordedToolLifecycle>>>,
}

#[derive(Clone, Copy)]
enum ToolPolicyTestBehavior {
    BlockAdmission,
    BlockAuthorization,
    FailTerminal,
    Inactive,
}

#[derive(Debug, Eq, PartialEq)]
enum RecordedToolPolicy {
    Admission {
        call_id: String,
        payload: String,
    },
    Authorization {
        call_id: String,
        payload: String,
    },
    Terminal {
        call_id: String,
        outcome: codex_extension_api::ToolCallOutcome,
        host_accepted: bool,
    },
}

struct ToolPolicyRecorder {
    behavior: ToolPolicyTestBehavior,
    records: Arc<std::sync::Mutex<Vec<RecordedToolPolicy>>>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AttemptPhase {
    Admission,
    Authorization,
    Terminal(codex_extension_api::ToolCallOutcome),
}

#[derive(Debug, Eq, PartialEq)]
struct AttemptRecord {
    attempt_id: String,
    call_id: String,
    phase: AttemptPhase,
}

struct AttemptPolicyRecorder {
    records: Arc<std::sync::Mutex<Vec<AttemptRecord>>>,
}

impl codex_extension_api::ToolPolicyContributor for AttemptPolicyRecorder {
    fn admit<'a>(
        &'a self,
        input: codex_extension_api::ToolPolicyInput<'a>,
    ) -> codex_extension_api::ToolPolicyFuture<'a, codex_extension_api::ToolPolicyDecision> {
        let records = Arc::clone(&self.records);
        let record = AttemptRecord {
            attempt_id: input.attempt_id.to_string(),
            call_id: input.call_id.to_string(),
            phase: AttemptPhase::Admission,
        };
        Box::pin(async move {
            records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(record);
            Ok(codex_extension_api::ToolPolicyDecision::Allow)
        })
    }

    fn authorize<'a>(
        &'a self,
        input: codex_extension_api::ToolPolicyInput<'a>,
    ) -> codex_extension_api::ToolPolicyFuture<'a, codex_extension_api::ToolPolicyDecision> {
        let records = Arc::clone(&self.records);
        let record = AttemptRecord {
            attempt_id: input.attempt_id.to_string(),
            call_id: input.call_id.to_string(),
            phase: AttemptPhase::Authorization,
        };
        Box::pin(async move {
            records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(record);
            Ok(codex_extension_api::ToolPolicyDecision::Allow)
        })
    }

    fn on_terminal<'a>(
        &'a self,
        input: codex_extension_api::ToolPolicyTerminalInput<'a>,
    ) -> codex_extension_api::ToolPolicyFuture<'a, ()> {
        let records = Arc::clone(&self.records);
        let record = AttemptRecord {
            attempt_id: input.attempt_id.to_string(),
            call_id: input.call_id.to_string(),
            phase: AttemptPhase::Terminal(input.outcome),
        };
        Box::pin(async move {
            records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(record);
            Ok(())
        })
    }
}

impl codex_extension_api::ToolPolicyContributor for ToolPolicyRecorder {
    fn is_active(&self, _thread_store: &codex_extension_api::ExtensionData) -> bool {
        !matches!(self.behavior, ToolPolicyTestBehavior::Inactive)
    }

    fn admit<'a>(
        &'a self,
        input: codex_extension_api::ToolPolicyInput<'a>,
    ) -> codex_extension_api::ToolPolicyFuture<'a, codex_extension_api::ToolPolicyDecision> {
        let behavior = self.behavior;
        let records = Arc::clone(&self.records);
        let call_id = input.call_id.to_string();
        let payload = recorded_payload(input.payload);
        Box::pin(async move {
            records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(RecordedToolPolicy::Admission { call_id, payload });
            Ok(match behavior {
                ToolPolicyTestBehavior::BlockAdmission => {
                    codex_extension_api::ToolPolicyDecision::Block {
                        reason_code: "test_admission_block".to_string(),
                        message: "blocked during admission".to_string(),
                    }
                }
                _ => codex_extension_api::ToolPolicyDecision::Allow,
            })
        })
    }

    fn authorize<'a>(
        &'a self,
        input: codex_extension_api::ToolPolicyInput<'a>,
    ) -> codex_extension_api::ToolPolicyFuture<'a, codex_extension_api::ToolPolicyDecision> {
        let behavior = self.behavior;
        let records = Arc::clone(&self.records);
        let call_id = input.call_id.to_string();
        let payload = recorded_payload(input.payload);
        Box::pin(async move {
            records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(RecordedToolPolicy::Authorization { call_id, payload });
            Ok(match behavior {
                ToolPolicyTestBehavior::BlockAuthorization => {
                    codex_extension_api::ToolPolicyDecision::Block {
                        reason_code: "test_authorization_block".to_string(),
                        message: "blocked during authorization".to_string(),
                    }
                }
                _ => codex_extension_api::ToolPolicyDecision::Allow,
            })
        })
    }

    fn on_terminal<'a>(
        &'a self,
        input: codex_extension_api::ToolPolicyTerminalInput<'a>,
    ) -> codex_extension_api::ToolPolicyFuture<'a, ()> {
        let behavior = self.behavior;
        let records = Arc::clone(&self.records);
        let record = RecordedToolPolicy::Terminal {
            call_id: input.call_id.to_string(),
            outcome: input.outcome,
            host_accepted: input.host_accepted,
        };
        Box::pin(async move {
            records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(record);
            if matches!(behavior, ToolPolicyTestBehavior::FailTerminal) {
                Err(codex_extension_api::ToolPolicyError::new(
                    "test_terminal_failure",
                    "terminal sink failed",
                ))
            } else {
                Ok(())
            }
        })
    }
}

fn recorded_payload(payload: &ToolPayload) -> String {
    match payload {
        ToolPayload::Function { arguments } => arguments.clone(),
        ToolPayload::ToolSearch { arguments } => {
            serde_json::to_string(arguments).expect("serialize tool-search payload")
        }
        ToolPayload::Custom { input } => input.clone(),
    }
}

fn install_rewriting_pre_tool_hook(
    session: &Session,
    turn: &crate::session::turn_context::TurnContext,
) {
    let plugin_root = turn.config.codex_home.clone();
    std::fs::create_dir_all(plugin_root.as_path()).expect("create hook test root");
    let script_path = plugin_root.join("rewrite_pre_tool.py");
    let hook_output = serde_json::json!({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": { "message": "rewritten" },
        }
    })
    .to_string();
    std::fs::write(script_path.as_path(), format!("print({hook_output:?})\n"))
        .expect("write rewriting hook");
    let python = if cfg!(windows) { "python" } else { "python3" };
    let script_arg = if cfg!(windows) {
        format!("\"{}\"", script_path.display())
    } else {
        format!(
            "'{}'",
            script_path.display().to_string().replace('\'', "'\\''")
        )
    };
    let source_path = plugin_root.join("hooks/hooks.json");
    let plugin_hook_source = codex_plugin::PluginHookSource {
        plugin_id: codex_plugin::PluginId::parse("tool-policy-test@local")
            .expect("valid plugin id"),
        plugin_root: plugin_root.clone(),
        plugin_data_root: plugin_root.join("data"),
        source_path,
        source_relative_path: "hooks/hooks.json".to_string(),
        hooks: codex_config::HookEventsToml {
            pre_tool_use: vec![codex_config::MatcherGroup {
                matcher: None,
                hooks: vec![codex_config::HookHandlerConfig::Command {
                    command: format!("{python} {script_arg}"),
                    command_windows: None,
                    timeout_sec: Some(5),
                    r#async: false,
                    status_message: None,
                    additional_context_limit: None,
                }],
            }],
            ..Default::default()
        },
    };
    let (hooks, _async_hook_results) = codex_hooks::Hooks::new(
        codex_hooks::HooksConfig {
            feature_enabled: true,
            bypass_hook_trust: true,
            plugin_hook_sources: vec![plugin_hook_source],
            ..Default::default()
        },
        session.thread_id(),
        Arc::new(CoreHookMcpExecutor {
            runtime: Arc::new(McpRuntime::empty(turn.config.prefix_mcp_tool_names())),
            thread_id: session.thread_id(),
            session: Arc::new(std::sync::OnceLock::new()),
        }),
    )
    .expect("initialize plugin tool-policy test hooks");
    session.services.hooks.store(Arc::new(hooks));
}

fn dispatch_error(
    result: Result<AnyToolResult, FunctionCallError>,
    context: &str,
) -> FunctionCallError {
    match result {
        Ok(_) => panic!("{context}"),
        Err(error) => error,
    }
}

impl codex_extension_api::ToolLifecycleContributor for ToolLifecycleRecorder {
    fn on_tool_start<'a>(
        &'a self,
        input: codex_extension_api::ToolStartInput<'a>,
    ) -> codex_extension_api::ToolLifecycleFuture<'a> {
        let records = Arc::clone(&self.records);
        let record = RecordedToolLifecycle::Start {
            call_id: input.call_id.to_string(),
            tool_name: input.tool_name.clone(),
        };
        Box::pin(async move {
            records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(record);
        })
    }

    fn on_tool_finish<'a>(
        &'a self,
        input: codex_extension_api::ToolFinishInput<'a>,
    ) -> codex_extension_api::ToolLifecycleFuture<'a> {
        let records = Arc::clone(&self.records);
        let record = RecordedToolLifecycle::Finish {
            call_id: input.call_id.to_string(),
            tool_name: input.tool_name.clone(),
            outcome: input.outcome,
        };
        Box::pin(async move {
            records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(record);
        })
    }
}

#[test]
fn handler_normalizes_only_the_default_namespace() {
    let namespace = "mcp__codex_apps__gmail";
    let tool_name = "gmail_get_recent_emails";
    let plain_name = codex_tools::ToolName::plain(tool_name);
    let namespaced_name = codex_tools::ToolName::namespaced(namespace, tool_name);
    let plain_handler = Arc::new(TestHandler {
        tool_name: plain_name.clone(),
    }) as Arc<dyn CoreToolRuntime>;
    let namespaced_handler = Arc::new(TestHandler {
        tool_name: namespaced_name.clone(),
    }) as Arc<dyn CoreToolRuntime>;
    let registry =
        ToolRegistry::from_tools([Arc::clone(&plain_handler), Arc::clone(&namespaced_handler)]);

    let plain = registry.tool(&plain_name);
    let default_namespaced = registry.tool(&codex_tools::ToolName::namespaced(
        DEFAULT_FUNCTION_NAMESPACE,
        tool_name,
    ));
    let empty_namespaced = registry.tool(&codex_tools::ToolName::namespaced("", tool_name));
    let namespaced = registry.tool(&namespaced_name);
    let missing_namespaced = registry.tool(&codex_tools::ToolName::namespaced(
        "mcp__codex_apps__calendar",
        tool_name,
    ));

    assert_eq!(plain.is_some(), true);
    assert_eq!(namespaced.is_some(), true);
    assert_eq!(missing_namespaced.is_none(), true);
    assert!(
        plain
            .as_ref()
            .is_some_and(|handler| Arc::ptr_eq(handler, &plain_handler))
    );
    assert!(
        default_namespaced
            .as_ref()
            .is_some_and(|handler| Arc::ptr_eq(handler, &plain_handler))
    );
    assert!(
        empty_namespaced
            .as_ref()
            .is_some_and(|handler| Arc::ptr_eq(handler, &plain_handler))
    );
    assert!(
        namespaced
            .as_ref()
            .is_some_and(|handler| Arc::ptr_eq(handler, &namespaced_handler))
    );
}

#[test]
fn registry_rejects_default_namespace_alias_collisions() {
    let plain_name = codex_tools::ToolName::plain("lookup");
    let namespaced_name = codex_tools::ToolName::namespaced(DEFAULT_FUNCTION_NAMESPACE, "lookup");

    for [first_name, duplicate_name] in [
        [plain_name.clone(), namespaced_name.clone()],
        [namespaced_name, plain_name],
    ] {
        let winner = Arc::new(TestHandler {
            tool_name: first_name.clone(),
        }) as Arc<dyn CoreToolRuntime>;
        let mut registry = ToolRegistry::from_tools([Arc::clone(&winner)]);

        assert!(!registry.register_external(Arc::new(TestHandler {
            tool_name: duplicate_name.clone(),
        })));
        assert!(
            registry
                .tool(&duplicate_name)
                .is_some_and(|handler| Arc::ptr_eq(&handler, &winner))
        );
        assert_eq!(
            registry.tool_exposure(&duplicate_name),
            Some(ToolExposure::Direct)
        );
        assert_eq!(
            registry.supports_parallel_tool_calls(&duplicate_name),
            Some(false)
        );
        assert!(
            registry
                .remove(&duplicate_name)
                .is_some_and(|handler| Arc::ptr_eq(&handler, &winner))
        );
        assert!(registry.tool(&first_name).is_none());
    }
}

#[test]
fn registry_preserves_external_winners_and_trusted_synthetic_order() {
    let handler = |tool_name| Arc::new(TestHandler { tool_name }) as Arc<dyn CoreToolRuntime>;
    let [first_name, second_name, synthetic_name] =
        ["first", "second", "synthetic"].map(codex_tools::ToolName::plain);
    let first_handler = handler(first_name.clone());

    let mut registry = ToolRegistry::from_tools([Arc::clone(&first_handler)]);
    assert!(!registry.register_external(handler(first_name.clone())));
    let canonical_first_name = first_name.clone().with_default_namespace();
    assert_eq!(registry.first_collision(), Some(&canonical_first_name));
    assert!(registry.register_external(handler(second_name.clone())));
    registry.prepend_trusted(handler(synthetic_name.clone()));

    assert_eq!(
        registry
            .entries()
            .map(|tool| tool.runtime.tool_name())
            .collect::<Vec<_>>(),
        vec![synthetic_name, first_name.clone(), second_name],
    );
    assert!(
        registry
            .remove(&first_name)
            .is_some_and(|handler| Arc::ptr_eq(&handler, &first_handler))
    );
}

#[test]
fn reserved_command_tools_reject_external_runtimes_without_a_builtin() {
    let handler = |tool_name| Arc::new(TestHandler { tool_name }) as Arc<dyn CoreToolRuntime>;
    let mut registry = ToolRegistry::default();

    for reserved_name in ["exec_command", "shell_command"] {
        let tool_name = codex_tools::ToolName::plain(reserved_name);
        let namespaced_tool_name = codex_tools::ToolName::namespaced("client", reserved_name);

        assert!(!registry.register_external(handler(tool_name.clone())));
        assert!(
            !registry
                .register_external_with_exposure(handler(tool_name.clone()), ToolExposure::Direct)
        );
        assert!(
            !registry.register_external(handler(codex_tools::ToolName::namespaced(
                DEFAULT_FUNCTION_NAMESPACE,
                reserved_name,
            )))
        );
        assert!(registry.tool(&tool_name).is_none());
        assert_eq!(registry.first_collision(), None);

        let namespaced_handler = handler(namespaced_tool_name.clone());
        assert!(registry.register_external(Arc::clone(&namespaced_handler)));
        assert!(
            registry
                .tool(&namespaced_tool_name)
                .is_some_and(|runtime| Arc::ptr_eq(&runtime, &namespaced_handler))
        );
    }
}

#[test]
fn registry_records_reserved_exec_command_when_a_matching_tool_exists() {
    let tool_name = codex_tools::ToolName::plain("exec_command");
    let trusted = Arc::new(TestHandler {
        tool_name: tool_name.clone(),
    }) as Arc<dyn CoreToolRuntime>;
    let external = Arc::new(TestHandler {
        tool_name: tool_name.clone(),
    });
    let mut registry = ToolRegistry::from_tools([trusted]);

    assert!(!registry.register_external(external));
    let canonical_tool_name = tool_name.with_default_namespace();
    assert_eq!(registry.first_collision(), Some(&canonical_tool_name));
}

#[test]
fn registry_allows_identical_names_in_different_namespaces() {
    let handler = |tool_name| Arc::new(TestHandler { tool_name }) as Arc<dyn CoreToolRuntime>;
    let mut registry = ToolRegistry::from_tools([handler(codex_tools::ToolName::namespaced(
        "first", "lookup",
    ))]);

    assert!(
        registry.register_external(handler(codex_tools::ToolName::namespaced(
            "second", "lookup",
        )))
    );
    assert_eq!(registry.first_collision(), None);
}

#[tokio::test]
async fn readiness_selects_exact_tool_with_registry_owned_exposure() {
    let (session, _turn) = crate::session::tests::make_session_and_context().await;
    let session = Arc::new(session);
    let plain_name = codex_tools::ToolName::plain("echo");
    let namespaced_name = codex_tools::ToolName::namespaced("mcp__server__", "echo");
    assert!(
        TestHandler {
            tool_name: plain_name.clone(),
        }
        .wait_until_ready(&session)
        .is_none()
    );
    let plain_readiness_waits = Arc::new(AtomicUsize::new(0));
    let namespaced_readiness_waits = Arc::new(AtomicUsize::new(0));
    let plain_handler = Arc::new(ReadinessTestHandler {
        handler: TestHandler {
            tool_name: plain_name.clone(),
        },
        readiness_waits: Arc::clone(&plain_readiness_waits),
    }) as Arc<dyn CoreToolRuntime>;
    let namespaced_handler = Arc::new(ReadinessTestHandler {
        handler: TestHandler {
            tool_name: namespaced_name.clone(),
        },
        readiness_waits: Arc::clone(&namespaced_readiness_waits),
    });
    let mut registry = ToolRegistry::from_tools([plain_handler]);
    registry.register_trusted_with_exposure(namespaced_handler, ToolExposure::DirectModelOnly);

    registry
        .tool(&plain_name)
        .expect("plain runtime should be registered")
        .wait_until_ready(&session)
        .expect("plain runtime should provide a readiness wait")
        .await;
    assert_eq!(
        [
            plain_readiness_waits.load(Ordering::Relaxed),
            namespaced_readiness_waits.load(Ordering::Relaxed),
        ],
        [1, 0]
    );

    registry
        .tool(&namespaced_name)
        .expect("namespaced runtime should be registered")
        .wait_until_ready(&session)
        .expect("namespaced runtime should forward its readiness wait")
        .await;
    assert_eq!(
        [
            plain_readiness_waits.load(Ordering::Relaxed),
            namespaced_readiness_waits.load(Ordering::Relaxed),
        ],
        [1, 1]
    );

    assert!(
        registry
            .tool(&codex_tools::ToolName::namespaced("mcp__missing__", "echo"))
            .is_none()
    );
    assert_eq!(
        [
            plain_readiness_waits.load(Ordering::Relaxed),
            namespaced_readiness_waits.load(Ordering::Relaxed),
        ],
        [1, 1]
    );
}

#[tokio::test]
async fn function_tools_expose_default_hook_payloads_and_rewrites() -> anyhow::Result<()> {
    let (session, turn) = crate::session::tests::make_session_and_context().await;
    let tool_name = codex_tools::ToolName::namespaced("functions.", "echo");
    let handler = TestHandler {
        tool_name: tool_name.clone(),
    };
    let invocation = ToolInvocation {
        payload: ToolPayload::Function {
            arguments: serde_json::json!({ "message": "hello" }).to_string(),
        },
        ..test_invocation(Arc::new(session), Arc::new(turn), "call-1", tool_name)
    };
    let output =
        crate::tools::context::FunctionToolOutput::from_text("echoed".to_string(), Some(true));

    assert_eq!(
        handler.pre_tool_use_payload(&invocation),
        Some(PreToolUsePayload {
            tool_name: HookToolName::new("functions.echo"),
            tool_input: serde_json::json!({ "message": "hello" }),
        })
    );
    assert_eq!(
        handler.post_tool_use_payload(&invocation, &output),
        Some(PostToolUsePayload {
            tool_name: HookToolName::new("functions.echo"),
            tool_use_id: "call-1".to_string(),
            tool_input: serde_json::json!({ "message": "hello" }),
            tool_response: serde_json::json!("echoed"),
        })
    );

    let invocation = handler
        .with_updated_hook_input(invocation, serde_json::json!({ "message": "rewritten" }))?;
    let ToolPayload::Function { arguments } = invocation.payload else {
        panic!("generic rewritten function payload should remain function-shaped");
    };
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&arguments)?,
        serde_json::json!({ "message": "rewritten" })
    );

    Ok(())
}

#[tokio::test]
async fn function_hook_input_defaults_empty_arguments_to_object() {
    let (session, turn) = crate::session::tests::make_session_and_context().await;
    let tool_name = codex_tools::ToolName::plain("echo");
    let handler = TestHandler {
        tool_name: tool_name.clone(),
    };
    let invocation = ToolInvocation {
        payload: ToolPayload::Function {
            arguments: "  ".to_string(),
        },
        ..test_invocation(Arc::new(session), Arc::new(turn), "call-1", tool_name)
    };

    assert_eq!(
        handler.pre_tool_use_payload(&invocation),
        Some(PreToolUsePayload {
            tool_name: HookToolName::new("echo"),
            tool_input: serde_json::json!({}),
        })
    );
}

#[tokio::test]
async fn spawn_agent_function_tools_use_agent_matcher_alias() {
    let (session, turn) = crate::session::tests::make_session_and_context().await;
    let session = Arc::new(session);
    let turn = Arc::new(turn);

    let hook_payloads = [
        codex_tools::ToolName::plain("spawn_agent"),
        codex_tools::ToolName::namespaced(DEFAULT_FUNCTION_NAMESPACE, "spawn_agent"),
        codex_tools::ToolName::namespaced(MULTI_AGENT_V1_NAMESPACE, "spawn_agent"),
    ]
    .into_iter()
    .map(|tool_name| {
        let handler = TestHandler {
            tool_name: tool_name.clone(),
        };
        let invocation = ToolInvocation {
            payload: ToolPayload::Function {
                arguments: serde_json::json!({ "message": "inspect this repo" }).to_string(),
            },
            ..test_invocation(Arc::clone(&session), Arc::clone(&turn), "call-1", tool_name)
        };
        handler.pre_tool_use_payload(&invocation)
    })
    .collect::<Vec<_>>();

    assert_eq!(
        hook_payloads,
        vec![
            Some(PreToolUsePayload {
                tool_name: HookToolName::spawn_agent(),
                tool_input: serde_json::json!({ "message": "inspect this repo" }),
            }),
            Some(PreToolUsePayload {
                tool_name: HookToolName::spawn_agent(),
                tool_input: serde_json::json!({ "message": "inspect this repo" }),
            }),
            Some(PreToolUsePayload {
                tool_name: HookToolName::spawn_agent(),
                tool_input: serde_json::json!({ "message": "inspect this repo" }),
            }),
        ]
    );
}

#[tokio::test]
async fn code_mode_wait_does_not_expose_default_hook_payloads() {
    let (session, turn) = crate::session::tests::make_session_and_context().await;
    let output = crate::tools::context::FunctionToolOutput::from_text("ok".to_string(), Some(true));

    let wait = crate::tools::handlers::CodeModeWaitHandler;
    let wait_invocation = test_invocation(
        Arc::new(session),
        Arc::new(turn),
        "wait-call",
        wait.tool_name(),
    );
    assert_eq!(wait.pre_tool_use_payload(&wait_invocation), None);
    assert_eq!(wait.post_tool_use_payload(&wait_invocation, &output), None);
}

#[tokio::test]
async fn write_stdin_does_not_expose_default_pre_tool_use_payload() {
    let (session, turn) = crate::session::tests::make_session_and_context().await;

    let write_stdin = crate::tools::handlers::WriteStdinHandler;
    let invocation = test_invocation(
        Arc::new(session),
        Arc::new(turn),
        "write-stdin-call",
        write_stdin.tool_name(),
    );

    assert_eq!(write_stdin.pre_tool_use_payload(&invocation), None);
}

#[test]
fn post_tool_use_feedback_output_keeps_code_mode_result_typed() {
    let result = AnyToolResult {
        call_id: "call-1".to_string(),
        payload: ToolPayload::Function {
            arguments: "{}".to_string(),
        },
        result: Box::new(PostToolUseFeedbackOutput {
            original: Box::new(codex_tools::JsonToolOutput::new(
                serde_json::json!({ "typed": true }),
            )),
            model_visible: crate::tools::context::FunctionToolOutput::from_text(
                "hook feedback".to_string(),
                /*success*/ None,
            ),
        }),
        post_tool_use_payload: None,
    };

    assert_eq!(
        result.into_response(),
        ResponseInputItem::FunctionCallOutput {
            call_id: "call-1".to_string(),
            output: codex_protocol::models::FunctionCallOutputPayload::from_text(
                "hook feedback".to_string()
            ),
        }
    );

    let result = AnyToolResult {
        call_id: "call-1".to_string(),
        payload: ToolPayload::Function {
            arguments: "{}".to_string(),
        },
        result: Box::new(PostToolUseFeedbackOutput {
            original: Box::new(codex_tools::JsonToolOutput::new(
                serde_json::json!({ "typed": true }),
            )),
            model_visible: crate::tools::context::FunctionToolOutput::from_text(
                "hook feedback".to_string(),
                /*success*/ None,
            ),
        }),
        post_tool_use_payload: None,
    };

    assert_eq!(
        result.code_mode_result(),
        serde_json::json!({ "typed": true })
    );
}

#[tokio::test]
async fn dispatch_uses_canonical_tool_names_for_lifecycle_contributors() -> anyhow::Result<()> {
    let (mut session, turn) = crate::session::tests::make_session_and_context().await;
    let records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.tool_lifecycle_contributor(Arc::new(ToolLifecycleRecorder {
        records: Arc::clone(&records),
    }));
    session.services.extensions = Arc::new(builder.build());

    let ok_tool = codex_tools::ToolName::plain("ok_tool");
    let failing_tool = codex_tools::ToolName::namespaced("extensions", "failing_tool");
    let ok_handler = Arc::new(LifecycleTestHandler {
        tool_name: ok_tool.clone(),
        result: LifecycleTestResult::Ok { success: false },
    }) as Arc<dyn CoreToolRuntime>;
    let failing_handler = Arc::new(LifecycleTestHandler {
        tool_name: failing_tool.clone(),
        result: LifecycleTestResult::Err,
    }) as Arc<dyn CoreToolRuntime>;
    let registry = ToolRegistry::from_tools([ok_handler, failing_handler]);
    let session = Arc::new(session);
    let turn = Arc::new(turn);

    registry
        .dispatch_any_with_terminal_outcome(
            test_invocation(
                Arc::clone(&session),
                Arc::clone(&turn),
                "ok-call",
                codex_tools::ToolName::namespaced(DEFAULT_FUNCTION_NAMESPACE, "ok_tool"),
            ),
            /*terminal_outcome_reached*/ None,
        )
        .await?;
    let err = match registry
        .dispatch_any_with_terminal_outcome(
            test_invocation(
                Arc::clone(&session),
                Arc::clone(&turn),
                "failing-call",
                failing_tool.clone(),
            ),
            /*terminal_outcome_reached*/ None,
        )
        .await
    {
        Ok(_) => panic!("failing handler should return an error"),
        Err(err) => err,
    };
    assert_eq!(err.to_string(), "handler failed");

    let expected = vec![
        RecordedToolLifecycle::Start {
            call_id: "ok-call".to_string(),
            tool_name: ok_tool.clone().with_default_namespace(),
        },
        RecordedToolLifecycle::Finish {
            call_id: "ok-call".to_string(),
            tool_name: ok_tool.with_default_namespace(),
            outcome: codex_extension_api::ToolCallOutcome::Completed { success: false },
        },
        RecordedToolLifecycle::Start {
            call_id: "failing-call".to_string(),
            tool_name: failing_tool.clone(),
        },
        RecordedToolLifecycle::Finish {
            call_id: "failing-call".to_string(),
            tool_name: failing_tool,
            outcome: codex_extension_api::ToolCallOutcome::Failed {
                handler_executed: true,
            },
        },
    ];
    let actual = records
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .drain(..)
        .collect::<Vec<_>>();
    assert_eq!(expected, actual);

    Ok(())
}

#[tokio::test]
async fn admission_block_skips_handler_and_ordinary_lifecycle() {
    let (mut session, turn) = crate::session::tests::make_session_and_context().await;
    let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let lifecycle_records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.tool_policy_contributor(Arc::new(ToolPolicyRecorder {
        behavior: ToolPolicyTestBehavior::BlockAdmission,
        records: Arc::clone(&policy_records),
    }));
    builder.tool_lifecycle_contributor(Arc::new(ToolLifecycleRecorder {
        records: Arc::clone(&lifecycle_records),
    }));
    session.services.extensions = Arc::new(builder.build());

    let tool_name = codex_tools::ToolName::plain("blocked_tool");
    let calls = Arc::new(AtomicUsize::new(0));
    let handler = Arc::new(CountingTestHandler {
        handler: LifecycleTestHandler {
            tool_name: tool_name.clone(),
            result: LifecycleTestResult::Ok { success: true },
        },
        calls: Arc::clone(&calls),
    }) as Arc<dyn CoreToolRuntime>;
    let registry = ToolRegistry::from_tools([handler]);
    let error = dispatch_error(
        registry
            .dispatch_any_with_terminal_outcome(
                test_invocation(Arc::new(session), Arc::new(turn), "blocked-call", tool_name),
                /*terminal_outcome_reached*/ None,
            )
            .await,
        "admission must block",
    );

    assert_eq!(error.to_string(), "blocked during admission");
    assert_eq!(calls.load(Ordering::Relaxed), 0);
    assert!(
        lifecycle_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .is_empty()
    );
    assert_eq!(
        policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_slice(),
        [
            RecordedToolPolicy::Admission {
                call_id: "blocked-call".to_string(),
                payload: "{}".to_string(),
            },
            RecordedToolPolicy::Terminal {
                call_id: "blocked-call".to_string(),
                outcome: codex_extension_api::ToolCallOutcome::Blocked,
                host_accepted: false,
            },
        ]
    );
}

#[tokio::test]
async fn empty_policy_defers_terminal_claim_to_legacy_finish() -> anyhow::Result<()> {
    let (mut session, turn) = crate::session::tests::make_session_and_context().await;
    session.services.extensions = Arc::new(
        codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new().build(),
    );
    let invocation = test_invocation(
        Arc::new(session),
        Arc::new(turn),
        "no-policy-call",
        codex_tools::ToolName::plain("no_policy_tool"),
    );
    let terminal_outcome_reached = AtomicBool::new(false);
    let attempt_id = ToolDispatchAttemptId::new();
    let outcome = codex_extension_api::ToolCallOutcome::Completed { success: true };

    enforce_tool_admission(&invocation, &attempt_id).await?;
    enforce_tool_authorization(&invocation, &attempt_id).await?;
    let ownership =
        claim_tool_policy_terminal_if_registered(&invocation, &attempt_id, outcome).await?;

    assert_eq!(ownership, HandlerTerminalOwnership::DeferredToLegacyFinish);
    assert!(!terminal_outcome_reached.load(Ordering::Acquire));
    assert!(
        notify_tool_finish_if_unclaimed(
            &invocation,
            &attempt_id,
            Some(&terminal_outcome_reached),
            outcome,
        )
        .await?
    );
    assert!(terminal_outcome_reached.load(Ordering::Acquire));
    Ok(())
}

#[tokio::test]
async fn inactive_policy_defers_terminal_claim_to_legacy_finish() -> anyhow::Result<()> {
    let (mut session, turn) = crate::session::tests::make_session_and_context().await;
    let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.tool_policy_contributor(Arc::new(ToolPolicyRecorder {
        behavior: ToolPolicyTestBehavior::Inactive,
        records: Arc::clone(&policy_records),
    }));
    session.services.extensions = Arc::new(builder.build());
    let invocation = test_invocation(
        Arc::new(session),
        Arc::new(turn),
        "inactive-policy-call",
        codex_tools::ToolName::plain("inactive_policy_tool"),
    );
    let terminal_outcome_reached = AtomicBool::new(false);
    let attempt_id = ToolDispatchAttemptId::new();
    let outcome = codex_extension_api::ToolCallOutcome::Completed { success: true };

    enforce_tool_admission(&invocation, &attempt_id).await?;
    enforce_tool_authorization(&invocation, &attempt_id).await?;
    assert!(
        policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .is_empty()
    );
    let ownership =
        claim_tool_policy_terminal_if_registered(&invocation, &attempt_id, outcome).await?;

    assert_eq!(ownership, HandlerTerminalOwnership::DeferredToLegacyFinish);
    assert!(!terminal_outcome_reached.load(Ordering::Acquire));
    assert!(
        policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .is_empty()
    );
    assert!(
        notify_tool_finish_if_unclaimed(
            &invocation,
            &attempt_id,
            Some(&terminal_outcome_reached),
            outcome,
        )
        .await?
    );
    assert!(terminal_outcome_reached.load(Ordering::Acquire));
    assert!(
        policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .is_empty()
    );
    Ok(())
}

#[tokio::test]
async fn concurrent_same_action_dispatches_keep_distinct_attempt_terminals() -> anyhow::Result<()> {
    let (mut session, turn) = crate::session::tests::make_session_and_context().await;
    let records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.tool_policy_contributor(Arc::new(AttemptPolicyRecorder {
        records: Arc::clone(&records),
    }));
    session.services.extensions = Arc::new(builder.build());

    let session = Arc::new(session);
    let turn = Arc::new(turn);
    let tool_name = codex_tools::ToolName::plain("same_action_tool");
    let registry = ToolRegistry::from_tools([Arc::new(TestHandler {
        tool_name: tool_name.clone(),
    }) as Arc<dyn CoreToolRuntime>]);
    let first = registry.dispatch_any_with_terminal_outcome(
        test_invocation(
            Arc::clone(&session),
            Arc::clone(&turn),
            "same-call",
            tool_name.clone(),
        ),
        /*terminal_outcome_reached*/ None,
    );
    let second = registry.dispatch_any_with_terminal_outcome(
        test_invocation(session, turn, "same-call", tool_name),
        /*terminal_outcome_reached*/ None,
    );
    let (first, second) = tokio::join!(first, second);
    first?;
    second?;

    let mut by_attempt = std::collections::BTreeMap::<String, Vec<AttemptPhase>>::new();
    for record in records
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .drain(..)
    {
        assert_eq!(record.call_id, "same-call");
        by_attempt
            .entry(record.attempt_id)
            .or_default()
            .push(record.phase);
    }
    assert_eq!(
        by_attempt.len(),
        2,
        "each dispatch must mint one attempt ID"
    );
    for (attempt_id, phases) in by_attempt {
        assert!(
            !attempt_id.is_empty(),
            "attempt ID must be opaque and non-empty"
        );
        assert_eq!(
            phases,
            [
                AttemptPhase::Admission,
                AttemptPhase::Authorization,
                AttemptPhase::Terminal(codex_extension_api::ToolCallOutcome::Completed {
                    success: true,
                }),
            ],
            "one attempt's terminal must stay bound to its admission and authorization",
        );
    }
    Ok(())
}

#[tokio::test]
async fn authorization_observes_payload_after_pre_tool_hook_rewrite() {
    let (mut session, turn) = crate::session::tests::make_session_and_context().await;
    install_rewriting_pre_tool_hook(&session, &turn);
    let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.tool_policy_contributor(Arc::new(ToolPolicyRecorder {
        behavior: ToolPolicyTestBehavior::BlockAuthorization,
        records: Arc::clone(&policy_records),
    }));
    session.services.extensions = Arc::new(builder.build());

    let tool_name = codex_tools::ToolName::namespaced("functions.", "echo");
    let registry = ToolRegistry::from_tools([Arc::new(TestHandler {
        tool_name: tool_name.clone(),
    }) as Arc<dyn CoreToolRuntime>]);
    let invocation = ToolInvocation {
        payload: ToolPayload::Function {
            arguments: serde_json::json!({ "message": "original" }).to_string(),
        },
        ..test_invocation(
            Arc::new(session),
            Arc::new(turn),
            "rewritten-call",
            tool_name,
        )
    };

    let error = dispatch_error(
        registry
            .dispatch_any_with_terminal_outcome(invocation, /*terminal_outcome_reached*/ None)
            .await,
        "rewritten payload must reach authorization",
    );
    assert_eq!(error.to_string(), "blocked during authorization");

    let records = policy_records
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert!(matches!(
        records.as_slice(),
        [
            RecordedToolPolicy::Admission { payload: original, .. },
            RecordedToolPolicy::Authorization { payload: rewritten, .. },
            RecordedToolPolicy::Terminal { .. },
        ] if serde_json::from_str::<serde_json::Value>(original).ok()
            == Some(serde_json::json!({ "message": "original" }))
            && serde_json::from_str::<serde_json::Value>(rewritten).ok()
                == Some(serde_json::json!({ "message": "rewritten" }))
    ));
}

#[tokio::test]
async fn authorization_block_runs_start_but_skips_handler() {
    let (mut session, turn) = crate::session::tests::make_session_and_context().await;
    let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let lifecycle_records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.tool_policy_contributor(Arc::new(ToolPolicyRecorder {
        behavior: ToolPolicyTestBehavior::BlockAuthorization,
        records: Arc::clone(&policy_records),
    }));
    builder.tool_lifecycle_contributor(Arc::new(ToolLifecycleRecorder {
        records: Arc::clone(&lifecycle_records),
    }));
    session.services.extensions = Arc::new(builder.build());

    let tool_name = codex_tools::ToolName::plain("blocked_tool");
    let calls = Arc::new(AtomicUsize::new(0));
    let handler = Arc::new(CountingTestHandler {
        handler: LifecycleTestHandler {
            tool_name: tool_name.clone(),
            result: LifecycleTestResult::Ok { success: true },
        },
        calls: Arc::clone(&calls),
    }) as Arc<dyn CoreToolRuntime>;
    let registry = ToolRegistry::from_tools([handler]);
    let error = dispatch_error(
        registry
            .dispatch_any_with_terminal_outcome(
                test_invocation(
                    Arc::new(session),
                    Arc::new(turn),
                    "blocked-call",
                    tool_name.clone(),
                ),
                /*terminal_outcome_reached*/ None,
            )
            .await,
        "authorization must block",
    );

    assert_eq!(error.to_string(), "blocked during authorization");
    assert_eq!(calls.load(Ordering::Relaxed), 0);
    assert_eq!(
        lifecycle_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_slice(),
        [
            RecordedToolLifecycle::Start {
                call_id: "blocked-call".to_string(),
                tool_name: tool_name.clone(),
            },
            RecordedToolLifecycle::Finish {
                call_id: "blocked-call".to_string(),
                tool_name,
                outcome: codex_extension_api::ToolCallOutcome::Blocked,
            },
        ]
    );
    assert_eq!(
        policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_slice(),
        [
            RecordedToolPolicy::Admission {
                call_id: "blocked-call".to_string(),
                payload: "{}".to_string(),
            },
            RecordedToolPolicy::Authorization {
                call_id: "blocked-call".to_string(),
                payload: "{}".to_string(),
            },
            RecordedToolPolicy::Terminal {
                call_id: "blocked-call".to_string(),
                outcome: codex_extension_api::ToolCallOutcome::Blocked,
                host_accepted: true,
            },
        ]
    );
}

#[tokio::test]
async fn terminal_sink_failure_surfaces_after_handler_execution() {
    let (mut session, turn) = crate::session::tests::make_session_and_context().await;
    let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
    builder.tool_policy_contributor(Arc::new(ToolPolicyRecorder {
        behavior: ToolPolicyTestBehavior::FailTerminal,
        records: Arc::clone(&policy_records),
    }));
    session.services.extensions = Arc::new(builder.build());

    let tool_name = codex_tools::ToolName::plain("terminal_failure_tool");
    let calls = Arc::new(AtomicUsize::new(0));
    let handler = Arc::new(CountingTestHandler {
        handler: LifecycleTestHandler {
            tool_name: tool_name.clone(),
            result: LifecycleTestResult::Ok { success: true },
        },
        calls: Arc::clone(&calls),
    }) as Arc<dyn CoreToolRuntime>;
    let registry = ToolRegistry::from_tools([handler]);
    let error = dispatch_error(
        registry
            .dispatch_any_with_terminal_outcome(
                test_invocation(
                    Arc::new(session),
                    Arc::new(turn),
                    "terminal-call",
                    tool_name.with_default_namespace(),
                ),
                /*terminal_outcome_reached*/ None,
            )
            .await,
        "terminal persistence failure must surface",
    );

    assert!(matches!(error, FunctionCallError::Fatal(_)));
    assert_eq!(calls.load(Ordering::Relaxed), 1);
    assert!(matches!(
        policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .last(),
        Some(RecordedToolPolicy::Terminal {
            outcome: codex_extension_api::ToolCallOutcome::Completed { success: true },
            host_accepted: true,
            ..
        })
    ));
}

fn test_invocation(
    session: Arc<crate::session::session::Session>,
    turn: Arc<crate::session::turn_context::TurnContext>,
    call_id: &str,
    tool_name: codex_tools::ToolName,
) -> ToolInvocation {
    let step_context = StepContext::for_test(Arc::clone(&turn));
    ToolInvocation {
        session,
        step_context,
        turn,
        cancellation_token: tokio_util::sync::CancellationToken::new(),
        tracker: Arc::new(tokio::sync::Mutex::new(
            crate::turn_diff_tracker::TurnDiffTracker::new(),
        )),
        call_id: call_id.to_string(),
        tool_name,
        source: crate::tools::context::ToolCallSource::Direct,
        payload: ToolPayload::Function {
            arguments: "{}".to_string(),
        },
    }
}
