use super::*;
use crate::{Currentness, FinalUse, EXECUTION_SCHEMA_VERSION};

fn digest(value: u8) -> String {
    format!("{value:064x}")
}

fn binding() -> ExecutionBinding {
    ExecutionBinding {
        schema_version: EXECUTION_SCHEMA_VERSION,
        run_id: "run-native-1".into(),
        turn_id: "turn-native-1".into(),
        cell_id: Some("cell-1".into()),
        organ_id: None,
        operation_id: "operation-native-1".into(),
        principal: "agent-1".into(),
        objective_digest: digest(1),
        policy_digest: digest(2),
        candidate_digest: digest(3),
        host: "host-1".into(),
        generation: 1,
        idempotency_key: "idem-1".into(),
        predecessor: None,
        currentness: Currentness::Current,
        final_use: FinalUse::NotGranted,
        rollback_reference: Some("rollback-native-1".into()),
    }
}

struct Deny;

impl NativeLoopObserver for Deny {
    fn verify_external(
        &self,
        _: &NativeLoopCursorV1,
        _: &NativeExternalObservationV1,
    ) -> Result<(), PortError> {
        Err(PortError::Denied)
    }

    fn verify_completion(
        &self,
        _: &NativeLoopCursorV1,
        _: &str,
    ) -> Result<(), PortError> {
        Err(PortError::Denied)
    }
}

struct TrustedFixture;

impl NativeLoopObserver for TrustedFixture {
    fn verify_external(
        &self,
        _: &NativeLoopCursorV1,
        _: &NativeExternalObservationV1,
    ) -> Result<(), PortError> {
        Ok(())
    }

    fn verify_completion(
        &self,
        _: &NativeLoopCursorV1,
        _: &str,
    ) -> Result<(), PortError> {
        Ok(())
    }
}

fn start() -> NativeLoopCursorV1 {
    NativeLoopCursorV1::begin(binding(), digest(4), 3, 10_000).unwrap()
}

fn proposed(
    cursor: &NativeLoopCursorV1,
    disposition: AgentStepDisposition,
) -> AgentStepObservationV1 {
    AgentStepObservationV1 {
        request_digest: cursor.next_request(1).unwrap().digest().unwrap(),
        disposition,
        next_state_digest: Some(digest(5)),
        action_digest: Some(digest(6)),
        observation_digest: digest(7),
    }
}

fn external(kind: NativeExternalKindV1) -> NativeExternalObservationV1 {
    NativeExternalObservationV1 {
        operation_id: "operation-native-1".into(),
        generation: 1,
        kind,
        action_digest: Some(digest(6)),
        step_observation_digest: digest(7),
        status: PortTerminal::Succeeded,
        observation_digest: digest(8),
    }
}

#[test]
fn model_continuation_requires_independent_observation_and_no_replay() {
    let base = start();
    let before = base.checkpoint_digest().unwrap();
    let waiting = base
        .accept_step(&proposed(&base, AgentStepDisposition::InvokeModel), 1)
        .unwrap();
    assert!(matches!(waiting.phase(), NativeLoopPhaseV1::AwaitingExternal { .. }));
    assert!(waiting.next_request(2).is_err());
    let unchanged = waiting.checkpoint_digest().unwrap();
    assert!(matches!(
        waiting.accept_external(&external(NativeExternalKindV1::Model), &Deny, 3),
        Err(PortError::Denied)
    ));
    assert_eq!(waiting.checkpoint_digest().unwrap(), unchanged);
    let resumed = waiting
        .accept_external(&external(NativeExternalKindV1::Model), &TrustedFixture, 3)
        .unwrap();
    assert_eq!(resumed.next_step(), 1);
    assert_ne!(resumed.state_digest(), digest(5));
    assert_ne!(resumed.checkpoint_digest().unwrap(), before);
    assert!(resumed
        .accept_external(&external(NativeExternalKindV1::Model), &TrustedFixture, 4)
        .is_err());
    assert!(resumed.next_request(4).is_ok());
}

#[test]
fn model_cannot_relabel_tool_outcome_or_change_correlation() {
    let base = start();
    let waiting = base
        .accept_step(&proposed(&base, AgentStepDisposition::ProposeTool), 1)
        .unwrap();
    assert!(waiting
        .accept_external(&external(NativeExternalKindV1::Model), &TrustedFixture, 3)
        .is_err());
    let mut altered = external(NativeExternalKindV1::Tool);
    altered.generation = 2;
    assert!(waiting.accept_external(&altered, &TrustedFixture, 3).is_err());
    altered.generation = 1;
    altered.action_digest = Some(digest(9));
    assert!(waiting.accept_external(&altered, &TrustedFixture, 3).is_err());
}

#[test]
fn indeterminate_effect_and_cancel_remain_quarantined() {
    let base = start();
    let waiting = base
        .accept_step(&proposed(&base, AgentStepDisposition::ProposeTool), 1)
        .unwrap();
    let mut observation = external(NativeExternalKindV1::Tool);
    observation.status = PortTerminal::Indeterminate;
    let blocked = waiting
        .accept_external(&observation, &TrustedFixture, 2)
        .unwrap();
    assert!(matches!(blocked.phase(), NativeLoopPhaseV1::Quarantined { .. }));
    assert!(blocked.next_request(3).is_err());
    assert!(matches!(
        waiting.request_cancel().phase(),
        NativeLoopPhaseV1::Quarantined { .. }
    ));
    assert!(matches!(base.request_cancel().phase(), NativeLoopPhaseV1::Cancelled));
    assert!(waiting.accept_external(&observation, &TrustedFixture, 10_001).is_err());
}

#[test]
fn completion_is_a_candidate_until_verified_by_independent_observer() {
    let base = start();
    let mut candidate = proposed(&base, AgentStepDisposition::Completed);
    candidate.action_digest = None;
    candidate.next_state_digest = None;
    let candidate = base.accept_step(&candidate, 1).unwrap();
    assert!(matches!(
        candidate.phase(),
        NativeLoopPhaseV1::CompletionCandidate { .. }
    ));
    assert!(matches!(
        candidate.accept_completion(&digest(9), &Deny),
        Err(PortError::Denied)
    ));
    let done = candidate
        .accept_completion(&digest(9), &TrustedFixture)
        .unwrap();
    assert!(matches!(done.phase(), NativeLoopPhaseV1::Completed { .. }));
    assert!(done.next_request(2).is_err());
}

#[test]
fn deadline_and_step_budgets_reject_reopening() {
    let base = NativeLoopCursorV1::begin(binding(), digest(4), 1, 100).unwrap();
    assert!(matches!(base.next_request(100), Err(PortError::Cancelled)));
    assert!(base
        .accept_step(&proposed(&start(), AgentStepDisposition::InvokeModel), 1)
        .is_err());
    assert!(NativeLoopCursorV1::begin(binding(), digest(4), 0, 100).is_err());
    assert!(NativeLoopCursorV1::begin(binding(), digest(0), 3, 100).is_err());
}
