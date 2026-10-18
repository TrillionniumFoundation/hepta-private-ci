use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::*;
use crate::SupervisordMutation;

#[test]
fn an_effect_without_a_durable_outcome_blocks_recovery_until_committed() {
    let dir = tempfile::tempdir().expect("temporary directory");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("Agent id");
    let state_digest = "00".repeat(32);
    let prepared = crate::prepare_mutation(
        dir.path(),
        /*request_id*/ 7,
        &agent_id,
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13",
        SupervisordMutation::Start,
        &state_digest,
        /*intent_sequence*/ 1,
    )
    .expect("prepare mutation");
    crate::mark_mutation_effect_started(dir.path(), &prepared.idempotency_key)
        .expect("persist effect boundary");

    assert_eq!(
        diagnose_recovery(dir.path(), &RecoveryDiagnosticContext::default()),
        RecoveryDiagnostic {
            agent_id: Some(agent_id.to_string()),
            recovery_required: true,
            intent_status: None,
            release_transaction_phase: None,
            intent_sha256: None,
            release_transaction_sha256: None,
            unresolved_control_intent: false,
            blockers: vec![RecoveryBlockerDiagnostic {
                kind: RecoveryBlockerKind::ProcessAmbiguity,
                detail: "an ordinary lifecycle mutation has no durable committed outcome".into(),
                operator_action: RecoveryOperatorAction::FenceExactProcessAndObserveExit,
            }],
        },
    );

    crate::commit_mutation(
        dir.path(),
        &prepared.idempotency_key,
        /*applied_state_revision*/ 1,
        /*read_snapshot_epoch*/ 1,
        &state_digest,
    )
    .expect("persist outcome");
    assert_eq!(
        diagnose_recovery(dir.path(), &RecoveryDiagnosticContext::default()),
        RecoveryDiagnostic {
            agent_id: None,
            recovery_required: false,
            intent_status: None,
            release_transaction_phase: None,
            intent_sha256: None,
            release_transaction_sha256: None,
            unresolved_control_intent: false,
            blockers: Vec::new(),
        },
    );
}
