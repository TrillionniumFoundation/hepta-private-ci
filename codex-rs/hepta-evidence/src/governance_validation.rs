use codex_hepta_contracts::GOVERNANCE_SCHEMA_VERSION;
use codex_hepta_contracts::GovernanceDecisionRecord;
use codex_hepta_contracts::GovernanceReceipt;
use codex_hepta_contracts::HandlerOutcome;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_contracts::ReceiptId;
use codex_hepta_contracts::ToolAction;

use crate::EvidenceError;

pub(crate) fn validate_decision(record: &GovernanceDecisionRecord) -> Result<(), EvidenceError> {
    if record.action.schema_version != GOVERNANCE_SCHEMA_VERSION {
        return invalid("unsupported action schema version");
    }
    let expected_action = codex_hepta_contracts::ActionId::for_tool_call(
        &record.action.thread_id,
        &record.action.turn_id,
        &record.action.call_id,
    );
    if record.action.action_id != expected_action {
        return invalid("action id does not bind thread, turn, and call ids");
    }
    let expected_decision = codex_hepta_contracts::DecisionId::for_action(
        &record.action.action_id,
        record.phase.as_str(),
    );
    if record.decision_id != expected_decision {
        return invalid("decision id does not bind action and policy phase");
    }
    for (label, digest) in [
        ("payload", &record.action.payload_sha256),
        ("policy", &record.policy.content_sha256),
    ] {
        if !is_canonical_sha256(digest.as_str()) {
            return invalid(format!("{label} digest is not canonical lowercase SHA-256"));
        }
    }
    if record.policy.policy_id.trim().is_empty() || record.policy.revision == 0 {
        return invalid("policy stamp requires a non-empty id and positive revision");
    }
    Ok(())
}

pub(crate) fn validate_receipt_binding(receipt: &GovernanceReceipt) -> Result<(), EvidenceError> {
    validate_decision(&receipt.admission)?;
    if receipt.admission.phase != PolicyPhase::Admission {
        return invalid("receipt admission record has the wrong policy phase");
    }
    if receipt.action_id != receipt.admission.action.action_id {
        return invalid("receipt action id does not match admission");
    }
    if receipt.receipt_id != ReceiptId::for_action(&receipt.action_id) {
        return invalid("receipt id does not bind its action id");
    }
    if let Some(authorization) = receipt.authorization.as_ref() {
        validate_decision(authorization)?;
        if authorization.phase != PolicyPhase::Authorization {
            return invalid("receipt authorization record has the wrong policy phase");
        }
        if !same_action_binding(&receipt.admission.action, &authorization.action) {
            return invalid("authorization does not bind the admitted action identity");
        }
    }
    if matches!(
        receipt.outcome,
        HandlerOutcome::HandlerCompleted { .. }
            | HandlerOutcome::HandlerFailed {
                handler_executed: true
            }
    ) && (!receipt.host_accepted || receipt.authorization.is_none())
    {
        return invalid("handler outcome requires accepted and authorized execution");
    }
    if matches!(
        receipt.admission.decision,
        codex_hepta_contracts::GovernanceDecision::Block { .. }
    ) && (receipt.host_accepted || receipt.authorization.is_some())
    {
        return invalid("blocked admission cannot be host-accepted or authorized");
    }
    if receipt.authorization.as_ref().is_some_and(|authorization| {
        matches!(
            authorization.decision,
            codex_hepta_contracts::GovernanceDecision::Block { .. }
        ) && !matches!(receipt.outcome, HandlerOutcome::Blocked)
    }) {
        return invalid("blocked authorization requires a blocked terminal outcome");
    }
    Ok(())
}

fn same_action_binding(left: &ToolAction, right: &ToolAction) -> bool {
    left.schema_version == right.schema_version
        && left.action_id == right.action_id
        && left.thread_id == right.thread_id
        && left.turn_id == right.turn_id
        && left.call_id == right.call_id
        && left.tool_name == right.tool_name
        && left.source == right.source
}

fn is_canonical_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn invalid<T>(detail: impl Into<String>) -> Result<T, EvidenceError> {
    Err(EvidenceError::InvalidRecord(detail.into()))
}
