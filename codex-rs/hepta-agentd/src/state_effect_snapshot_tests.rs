use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;

use crate::AgentdError;
use crate::AutomationEffectObservation;
use crate::AutomationEffectSnapshot;
use crate::automation_effect_host::AgentdAutomationEffectReconcileOutcome;

fn receipt(observation: Option<TaskFlowStepObservation>) -> TaskFlowStepReceipt {
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000179").unwrap();
    TaskFlowStepReceipt {
        owner_agent_id: owner.clone(),
        run_id: "run.receipt".to_string(),
        step_id: "step.receipt".to_string(),
        attempt: 3,
        state: TaskFlowStepState::Recorded,
        intent_digest: Sha256Digest::for_bytes(b"intent"),
        payload_digest: Sha256Digest::for_bytes(b"payload"),
        fence: TaskFlowFence::new(
            owner,
            "owner.fixture",
            /*owner_epoch*/ 2,
            /*generation*/ 4,
            "fence.fixture",
        )
        .unwrap(),
        event_seq: 7,
        last_command_id: "observe.fixture".to_string(),
        receipt_digest: Some(Sha256Digest::for_bytes(b"receipt")),
        observation,
        final_outcome: None,
    }
}

#[test]
fn boxed_observation_preserves_the_complete_wire_snapshot() {
    for (observation, expected_observation) in [
        (
            TaskFlowStepObservation::Succeeded,
            AutomationEffectObservation::Succeeded,
        ),
        (
            TaskFlowStepObservation::Failed,
            AutomationEffectObservation::Failed,
        ),
        (
            TaskFlowStepObservation::Indeterminate,
            AutomationEffectObservation::Indeterminate,
        ),
    ] {
        let original = receipt(Some(observation));
        let expected = AutomationEffectSnapshot {
            run_id: original.run_id.clone(),
            step_id: original.step_id.clone(),
            attempt: original.attempt,
            event_seq: original.event_seq,
            receipt_digest: original.receipt_digest.clone(),
            observation: expected_observation,
        };
        let outcome = AgentdAutomationEffectReconcileOutcome::Observed(Box::new(original));
        let AgentdAutomationEffectReconcileOutcome::Observed(owned) = outcome else {
            panic!("observed receipt changed variant");
        };
        let snapshot = super::effect_snapshot(*owned).unwrap();
        assert_eq!(snapshot, expected);
        assert_eq!(
            serde_json::to_vec(&snapshot).unwrap(),
            serde_json::to_vec(&expected).unwrap()
        );
    }
}

#[test]
fn boxing_does_not_create_a_missing_provider_observation() {
    let outcome = AgentdAutomationEffectReconcileOutcome::Observed(Box::new(receipt(
        /*observation*/ None,
    )));
    let AgentdAutomationEffectReconcileOutcome::Observed(owned) = outcome else {
        panic!("observed receipt changed variant");
    };
    assert!(
        matches!(super::effect_snapshot(*owned), Err(AgentdError::Protocol(message)) if message == "automation effect receipt has no provider observation")
    );
}
