use super::*;
use crate::session::step_context::StepContext;
use crate::session::tests::make_session_and_context_with_dynamic_tools_and_rx;
use crate::session::turn_context::TurnEnvironment;
use crate::tools::orchestrator::ToolOrchestrator;
use codex_protocol::error::CodexErrorDetails;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

struct RecordedAttempts {
    first_error: Option<ToolError>,
    sandbox_requested: Vec<bool>,
}

impl Approvable<TurnEnvironment> for RecordedAttempts {
    fn approval_action(
        &self,
        _req: &TurnEnvironment,
        _call_id: &str,
    ) -> std::io::Result<ApprovalAction> {
        Err(std::io::Error::other(
            "this approved fixture must not request approval",
        ))
    }

    fn exec_approval_requirement(&self, _req: &TurnEnvironment) -> Option<ExecApprovalRequirement> {
        Some(ExecApprovalRequirement::Skip {
            bypass_sandbox: false,
            proposed_execpolicy_amendment: None,
        })
    }

    fn should_bypass_approval(&self, _policy: AskForApproval, _already_approved: bool) -> bool {
        true
    }

    fn wants_no_sandbox_approval(&self, _policy: AskForApproval) -> bool {
        true
    }
}

impl Sandboxable for RecordedAttempts {
    fn sandbox_preference(&self) -> SandboxablePreference {
        SandboxablePreference::Auto
    }
}

impl ToolRuntime<TurnEnvironment, ()> for RecordedAttempts {
    fn turn_environment<'a>(&self, req: &'a TurnEnvironment) -> &'a TurnEnvironment {
        req
    }

    fn uses_executor_managed_process_sandbox(&self, _req: &TurnEnvironment) -> bool {
        true
    }

    async fn run(
        &mut self,
        _req: &TurnEnvironment,
        attempt: &SandboxAttempt<'_>,
        _ctx: &ToolCtx,
    ) -> Result<(), ToolError> {
        self.sandbox_requested.push(attempt.sandbox_requested);
        match self.first_error.take() {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }
}

#[tokio::test]
async fn unavailable_is_terminal_while_approved_policy_denial_can_retry() {
    let (session, turn, _events) =
        make_session_and_context_with_dynamic_tools_and_rx(Vec::new()).await;
    let context = ToolCtx {
        session,
        step_context: StepContext::for_test(Arc::clone(&turn)),
        cancellation_token: CancellationToken::new(),
        call_id: "patch-call".to_string(),
        tool_name: codex_tools::ToolName::plain("apply_patch"),
    };
    let environment = test_turn_environment(codex_exec_server::LOCAL_ENVIRONMENT_ID);
    let cases = [
        (
            ToolError::Codex(CodexErr::UnsupportedOperation(
                "sandbox unavailable".to_string(),
            )),
            vec![true],
            true,
        ),
        (
            ToolError::Codex(CodexErr::Sandbox(SandboxErr::Denied {
                output: Box::new(ExecToolCallOutput {
                    exit_code: 1,
                    stderr: StreamOutput::new("sandbox unavailable".to_string()),
                    ..Default::default()
                }),
                network_policy_decision: None,
            })),
            vec![true, false],
            false,
        ),
    ];
    for (error, expected_attempts, expected_failure) in cases {
        let mut runtime = RecordedAttempts {
            first_error: Some(error),
            sandbox_requested: Vec::new(),
        };
        let result = ToolOrchestrator::new()
            .run(
                &mut runtime,
                &environment,
                &context,
                &turn,
                AskForApproval::OnRequest,
            )
            .await;
        assert_eq!(
            (runtime.sandbox_requested, result.is_err()),
            (expected_attempts, expected_failure),
        );
        if let Err(error) = result {
            assert!(matches!(error, ToolError::Codex(error)
                if matches!(error.details(), CodexErrorDetails::UnsupportedOperation(_))));
        }
    }
}
