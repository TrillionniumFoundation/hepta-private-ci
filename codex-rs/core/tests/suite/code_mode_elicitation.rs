#![allow(clippy::unwrap_used)]

use std::time::Duration;

use anyhow::Result;
use codex_core::TurnInputRequest;
use codex_core::config::Config;
use codex_features::Feature;
use codex_protocol::config_types::CollaborationMode;
use codex_protocol::config_types::ModeKind;
use codex_protocol::config_types::Settings;
use codex_protocol::models::PermissionProfile;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::ReviewDecision;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::request_permissions::PermissionGrantScope;
use codex_protocol::request_permissions::RequestPermissionsResponse;
use codex_protocol::user_input::UserInput;
use core_test_support::responses;
use core_test_support::responses::ResponseMock;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_custom_tool_call;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::sse;
use core_test_support::skip_if_no_network;
use core_test_support::skip_if_wine_exec;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::test_codex;
use core_test_support::test_codex::turn_permission_fields;
use core_test_support::wait_for_event;
use core_test_support::wait_for_event_match;
use core_test_support::wait_for_event_with_timeout;
use wiremock::MockServer;

const YIELD_TIME_MS: u64 = 1_000;
const TURN_COMPLETE_TIMEOUT: Duration = Duration::from_secs(30);

struct CodeModeElicitationHarness {
    _server: MockServer,
    test: TestCodex,
    follow_up: ResponseMock,
    turn_id: String,
}

impl CodeModeElicitationHarness {
    async fn start(
        code: &str,
        permission_profile: PermissionProfile,
        configure: impl FnOnce(&mut Config) + Send + 'static,
    ) -> Result<Self> {
        let server = responses::start_mock_server().await;
        let mut builder =
            test_codex()
                .with_model("test-gpt-5.1-codex")
                .with_config(move |config| {
                    let _ = config.features.enable(Feature::CodeMode);
                    configure(config);
                });
        let test = builder.build_with_auto_env(&server).await?;
        let follow_up = mount_code_mode_responses(&server, code).await;
        let turn_id = submit_turn(&test, permission_profile).await?;
        Ok(Self {
            _server: server,
            test,
            follow_up,
            turn_id,
        })
    }

    async fn assert_result_held(&self) {
        tokio::time::sleep(Duration::from_millis(YIELD_TIME_MS + 250)).await;
        assert!(
            self.follow_up.requests().is_empty(),
            "captured exec result should not return during a user elicitation"
        );
    }

    async fn finish(self) {
        wait_for_event_with_timeout(
            &self.test.codex,
            |event| match event {
                EventMsg::TurnComplete(event) => event.turn_id == self.turn_id,
                _ => false,
            },
            TURN_COMPLETE_TIMEOUT,
        )
        .await;
        self.follow_up.single_request();
    }
}

async fn mount_code_mode_responses(server: &MockServer, code: &str) -> ResponseMock {
    responses::mount_sse_once(
        server,
        sse(vec![
            ev_response_created("resp-1"),
            ev_custom_tool_call("call-1", "exec", code),
            ev_completed("resp-1"),
        ]),
    )
    .await;
    responses::mount_sse_once(
        server,
        sse(vec![
            ev_assistant_message("msg-1", "done"),
            ev_completed("resp-2"),
        ]),
    )
    .await
}

async fn submit_turn(test: &TestCodex, permission_profile: PermissionProfile) -> Result<String> {
    let (sandbox_policy, permission_profile) =
        turn_permission_fields(permission_profile, test.config.cwd.as_path());
    test.codex
        .start_or_steer_turn(
            TurnInputRequest::user_input(vec![UserInput::Text {
                text: "run a code-mode tool that needs user input".into(),
                text_elements: Vec::new(),
            }])
            .with_thread_settings(ThreadSettingsOverrides {
                approval_policy: Some(AskForApproval::OnRequest),
                sandbox_policy: Some(sandbox_policy),
                permission_profile,
                collaboration_mode: Some(CollaborationMode {
                    mode: ModeKind::Default,
                    settings: Settings {
                        model: test.session_configured.model.clone(),
                        reasoning_effort: None,
                        developer_instructions: None,
                    },
                }),
                ..Default::default()
            }),
        )
        .await?;

    Ok(wait_for_event_match(&test.codex, |event| match event {
        EventMsg::TurnStarted(event) => Some(event.turn_id.clone()),
        _ => None,
    })
    .await)
}

#[cfg_attr(windows, ignore = "no exec_command on Windows")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn code_mode_holds_yielded_result_during_command_approval() -> Result<()> {
    skip_if_wine_exec!(
        Ok(()),
        "command approvals currently require a host-native cwd"
    );
    skip_if_no_network!(Ok(()));

    let harness = CodeModeElicitationHarness::start(
        r#"// @exec: {"yield_time_ms": 1000}
await tools.exec_command({
  cmd: "printf code_mode_approval_marker",
  sandbox_permissions: "require_escalated",
  justification: "test command approval",
});"#,
        PermissionProfile::read_only(),
        |_| {},
    )
    .await?;
    let approval = wait_for_event_match(&harness.test.codex, |event| match event {
        EventMsg::ExecApprovalRequest(approval) => Some(approval.clone()),
        _ => None,
    })
    .await;

    harness.assert_result_held().await;
    harness
        .test
        .codex
        .submit(Op::ExecApproval {
            id: approval.effective_approval_id(),
            turn_id: Some(harness.turn_id.clone()),
            decision: ReviewDecision::Approved,
        })
        .await?;
    harness.finish().await;
    Ok(())
}

// This observer never consumes an event, spawns a process, or changes a deadline.
// A helper file's metadata does not establish that a sandbox process started.
#[cfg(windows)]
struct PatchApprovalDiagnostics<'a> {
    harness: &'a CodeModeElicitationHarness,
    started_at: std::time::Instant,
    phase: std::cell::Cell<&'static str>,
    phase_started_at: std::cell::Cell<std::time::Instant>,
}

#[cfg(windows)]
impl<'a> PatchApprovalDiagnostics<'a> {
    fn new(harness: &'a CodeModeElicitationHarness, started_at: std::time::Instant) -> Self {
        let diagnostics = Self {
            harness,
            started_at,
            phase: std::cell::Cell::new("turn_started"),
            phase_started_at: std::cell::Cell::new(std::time::Instant::now()),
        };
        diagnostics.log(format_args!("pid={}", std::process::id()));
        diagnostics.fixture_metadata();
        diagnostics
    }

    fn log(&self, detail: std::fmt::Arguments<'_>) {
        use std::io::Write;

        // Ignore stderr errors so observing an unwind cannot cause a second panic.
        let _ = writeln!(
            std::io::stderr().lock(),
            "patch_approval_diag elapsed_ms={} phase={} phase_elapsed_ms={} turn_id={} {detail}",
            self.started_at.elapsed().as_millis(),
            self.phase.get(),
            self.phase_started_at.get().elapsed().as_millis(),
            self.harness.turn_id,
        );
    }

    fn phase(&self, phase: &'static str) {
        self.phase.set(phase);
        self.phase_started_at.set(std::time::Instant::now());
        self.log(format_args!("phase_entered"));
    }

    fn event(&self, event: &EventMsg) {
        match event {
            EventMsg::PatchApplyBegin(event) => self.log(format_args!(
                "event=PatchApplyBegin call_id={} event_turn_id={} auto_approved={}",
                event.call_id, event.turn_id, event.auto_approved,
            )),
            EventMsg::PatchApplyEnd(event) => self.log(format_args!(
                "event=PatchApplyEnd call_id={} event_turn_id={} success={} status={:?} stderr={:?}",
                event.call_id,
                event.turn_id,
                event.success,
                event.status,
                event.stderr.chars().take(1_024).collect::<String>(),
            )),
            EventMsg::Error(event) => self.log(format_args!(
                "event=Error info={:?} message={:?}",
                event.codex_error_info,
                event.message.chars().take(1_024).collect::<String>(),
            )),
            _ => {}
        }
    }

    fn file_metadata(&self, label: &str, path: &std::path::Path) {
        let metadata = std::fs::metadata(path)
            .map(|metadata| (metadata.is_file(), metadata.len(), metadata.modified()));
        self.log(format_args!(
            "metadata={label} path={path:?} state={metadata:?}"
        ));
    }

    fn fixture_metadata(&self) {
        let started_at = std::time::Instant::now();
        self.log(format_args!(
            "fixture_home={:?} executor_cwd={:?} host_fixture_cwd={:?}",
            self.harness.test.codex_home_path(),
            self.harness.test.config.cwd,
            self.harness.test.cwd_path(),
        ));
        // Direct-spawn Windows helpers resolve process home, independently of
        // TestCodex's fixture home. Read known file attributes only, never logs.
        match (
            std::env::current_exe(),
            codex_utils_home_dir::find_codex_home(),
        ) {
            (Ok(source), Ok(home)) => {
                self.file_metadata("current_exe", &source);
                if let Some(file_name) = source.file_name() {
                    let helper =
                        codex_windows_sandbox::sandbox_bin_dir(home.as_path()).join(file_name);
                    self.file_metadata("expected_materialized_exe", &helper);
                }
            }
            (source, home) => self.log(format_args!(
                "helper_path_observation current_exe={source:?} process_home={home:?}"
            )),
        }
        self.file_metadata(
            "host_fixture_target",
            &self
                .harness
                .test
                .workspace_path("code_mode_patch_approval.txt"),
        );
        self.log(format_args!(
            "metadata_observation_ms={}",
            started_at.elapsed().as_millis(),
        ));
    }
}

#[cfg(windows)]
impl Drop for PatchApprovalDiagnostics<'_> {
    fn drop(&mut self) {
        self.log(format_args!(
            "observer_drop panicking={}",
            std::thread::panicking(),
        ));
        // The observer borrows the harness and drops before its TempDirs. This
        // captures failure-time attributes without reading contents or changing files.
        self.fixture_metadata();
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn code_mode_holds_yielded_result_during_patch_approval() -> Result<()> {
    skip_if_no_network!(Ok(()));

    #[cfg(windows)]
    let diagnostic_started_at = std::time::Instant::now();
    let harness = CodeModeElicitationHarness::start(
        r#"// @exec: {"yield_time_ms": 1000}
await tools.apply_patch("*** Begin Patch\n*** Add File: code_mode_patch_approval.txt\n+held\n*** End Patch\n");"#,
        PermissionProfile::read_only(),
        |_| {},
    )
    .await?;
    #[cfg(windows)]
    let diagnostics = PatchApprovalDiagnostics::new(&harness, diagnostic_started_at);
    #[cfg(windows)]
    diagnostics.phase("approval_wait");
    let approval = wait_for_event_match(&harness.test.codex, |event| {
        #[cfg(windows)]
        diagnostics.event(event);
        match event {
            EventMsg::ApplyPatchApprovalRequest(approval) => Some(approval.clone()),
            _ => None,
        }
    })
    .await;
    #[cfg(windows)]
    diagnostics.log(format_args!(
        "approval_received call_id={}",
        approval.call_id
    ));

    #[cfg(windows)]
    diagnostics.phase("result_hold");
    harness.assert_result_held().await;
    #[cfg(windows)]
    diagnostics.phase("approval_submit");
    harness
        .test
        .codex
        .submit(Op::PatchApproval {
            id: approval.call_id,
            decision: ReviewDecision::Approved,
        })
        .await?;
    #[cfg(windows)]
    {
        diagnostics.log(format_args!("approval_submit_accepted"));
        diagnostics.phase("finish_wait");
        // Keep finish()'s predicate, 30-second wait and follow-up assertion.
        // Borrowing the harness lets the observer run before fixture teardown.
        wait_for_event_with_timeout(
            &harness.test.codex,
            |event| {
                diagnostics.event(event);
                match event {
                    EventMsg::TurnComplete(event) => event.turn_id == harness.turn_id,
                    _ => false,
                }
            },
            TURN_COMPLETE_TIMEOUT,
        )
        .await;
        diagnostics.phase("matching_turn_complete");
        harness.follow_up.single_request();
        diagnostics.phase("follow_up_assertion_passed");
    }
    #[cfg(not(windows))]
    harness.finish().await;
    Ok(())
}

#[cfg_attr(
    target_os = "linux",
    ignore = "request_permissions tool integration is not supported on Linux"
)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn code_mode_holds_yielded_result_during_permission_request() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let harness = CodeModeElicitationHarness::start(
        r#"// @exec: {"yield_time_ms": 1000}
await tools.request_permissions({
  reason: "test permission request",
  permissions: { network: { enabled: true } },
});"#,
        PermissionProfile::read_only(),
        |config| {
            let _ = config.features.enable(Feature::RequestPermissionsTool);
        },
    )
    .await?;
    let request = wait_for_event(&harness.test.codex, |event| {
        matches!(
            event,
            EventMsg::RequestPermissions(_) | EventMsg::TurnComplete(_) | EventMsg::Error(_)
        )
    })
    .await;
    let EventMsg::RequestPermissions(request) = request else {
        panic!("expected request_permissions before turn completion, got {request:?}");
    };

    harness.assert_result_held().await;
    harness
        .test
        .codex
        .submit(Op::RequestPermissionsResponse {
            id: request.call_id,
            response: RequestPermissionsResponse {
                permissions: Default::default(),
                scope: PermissionGrantScope::Turn,
                strict_auto_review: false,
            },
        })
        .await?;
    harness.finish().await;
    Ok(())
}
