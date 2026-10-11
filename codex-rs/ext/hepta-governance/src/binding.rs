use codex_extension_api::ToolCallOutcome;
use codex_extension_api::ToolCallSource;
use codex_extension_api::ToolPayload;
use codex_extension_api::ToolPolicyDecision;
use codex_extension_api::ToolPolicyError;
use codex_extension_api::ToolPolicyInput;
use codex_extension_api::ToolPolicyTerminalInput;
use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::GOVERNANCE_SCHEMA_VERSION;
use codex_hepta_contracts::GovernanceDecision;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::HandlerOutcome;
use codex_hepta_contracts::PolicyStamp;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::ToolAction;
use codex_hepta_contracts::ToolActionSource;

const BOOTSTRAP_POLICY_ID: &str = "hepta.bootstrap_integrity.v1";
const BOOTSTRAP_POLICY_REVISION: u64 = 1;
const BOOTSTRAP_POLICY_CONTENT: &[u8] =
    br#"{"decision":"not_evaluated","scope":"payload_digest_and_evidence_integrity"}"#;
pub(crate) fn bootstrap_policy_stamp() -> PolicyStamp {
    PolicyStamp::new(
        BOOTSTRAP_POLICY_ID,
        BOOTSTRAP_POLICY_REVISION,
        BOOTSTRAP_POLICY_CONTENT,
    )
}

pub(crate) fn tool_action(input: &ToolPolicyInput<'_>) -> Result<ToolAction, ToolPolicyError> {
    Ok(ToolAction {
        schema_version: GOVERNANCE_SCHEMA_VERSION,
        action_id: ActionId::for_tool_call(
            input.thread_store.level_id(),
            input.turn_id,
            input.call_id,
        ),
        thread_id: input.thread_store.level_id().to_string(),
        turn_id: input.turn_id.to_string(),
        call_id: input.call_id.to_string(),
        tool_name: input.tool_name.to_string(),
        source: tool_action_source(&input.source),
        payload_sha256: payload_digest(input.payload)?,
    })
}

fn tool_action_source(source: &ToolCallSource) -> ToolActionSource {
    match source {
        ToolCallSource::Direct => ToolActionSource::Direct,
        ToolCallSource::DirectPlaintextMessage => ToolActionSource::DirectPlaintextMessage,
        ToolCallSource::CodeMode {
            cell_id,
            runtime_tool_call_id,
        } => ToolActionSource::CodeMode {
            cell_id: cell_id.clone(),
            runtime_tool_call_id: runtime_tool_call_id.clone(),
        },
    }
}

fn payload_digest(payload: &ToolPayload) -> Result<Sha256Digest, ToolPolicyError> {
    let (kind, body) = match payload {
        ToolPayload::Function { arguments } => ("function", arguments.as_bytes().to_vec()),
        ToolPayload::ToolSearch { arguments } => (
            "tool_search",
            serde_json::to_vec(arguments).map_err(|error| {
                ToolPolicyError::new("hepta_payload_serialization_failed", error.to_string())
            })?,
        ),
        ToolPayload::Custom { input } => ("custom", input.as_bytes().to_vec()),
    };
    let mut canonical = Vec::with_capacity(kind.len() + body.len() + 8);
    canonical.extend_from_slice((kind.len() as u64).to_be_bytes().as_ref());
    canonical.extend_from_slice(kind.as_bytes());
    canonical.extend_from_slice(&body);
    Ok(Sha256Digest::for_bytes(&canonical))
}

pub(crate) fn same_action_identity(left: &ToolAction, right: &ToolAction) -> bool {
    left.action_id == right.action_id
        && left.thread_id == right.thread_id
        && left.turn_id == right.turn_id
        && left.call_id == right.call_id
        && left.tool_name == right.tool_name
        && left.source == right.source
}

pub(crate) fn terminal_matches_action(
    input: &ToolPolicyTerminalInput<'_>,
    action: &ToolAction,
) -> bool {
    action.schema_version == GOVERNANCE_SCHEMA_VERSION
        && action.action_id
            == ActionId::for_tool_call(input.thread_store.level_id(), input.turn_id, input.call_id)
        && action.thread_id == input.thread_store.level_id()
        && action.turn_id == input.turn_id
        && action.call_id == input.call_id
        && action.tool_name == input.tool_name.to_string()
        && action.source == tool_action_source(&input.source)
}

pub(crate) fn core_decision(
    mode: GovernanceMode,
    decision: &GovernanceDecision,
) -> Result<ToolPolicyDecision, ToolPolicyError> {
    match (mode, decision) {
        (_, GovernanceDecision::NotEvaluated | GovernanceDecision::Allow)
        | (GovernanceMode::Shadow, GovernanceDecision::Block { .. }) => {
            Ok(ToolPolicyDecision::Allow)
        }
        (GovernanceMode::Enforce, GovernanceDecision::Block { reason_code }) => {
            Ok(ToolPolicyDecision::Block {
                reason_code: reason_code.clone(),
                message: format!("Hepta governance blocked this tool call ({reason_code})"),
            })
        }
    }
}

pub(crate) fn handler_outcome(
    outcome: ToolCallOutcome,
    authorization_exists: bool,
) -> HandlerOutcome {
    match outcome {
        ToolCallOutcome::Completed { success } => HandlerOutcome::HandlerCompleted {
            reported_success: success,
        },
        ToolCallOutcome::Blocked => HandlerOutcome::Blocked,
        ToolCallOutcome::Failed { handler_executed } => {
            HandlerOutcome::HandlerFailed { handler_executed }
        }
        ToolCallOutcome::Aborted if authorization_exists => HandlerOutcome::Indeterminate {
            reason_code: "cancelled_after_authorization".to_string(),
        },
        ToolCallOutcome::Aborted => HandlerOutcome::Aborted,
        ToolCallOutcome::Indeterminate { reason_code } => HandlerOutcome::Indeterminate {
            reason_code: reason_code.to_string(),
        },
    }
}
