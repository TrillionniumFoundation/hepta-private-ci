use super::*;
use crate::{Currentness, ExecutionBinding, FinalUse, EXECUTION_SCHEMA_VERSION};

fn h(i: u8) -> String { format!("{i:064x}") }
fn base() -> AgentStepRequestV1 {
    AgentStepRequestV1 {
        binding: ExecutionBinding {
            schema_version: EXECUTION_SCHEMA_VERSION,
            run_id: "run-1".into(), turn_id: "turn-1".into(),
            cell_id: Some("cell-1".into()), organ_id: None,
            operation_id: "op-1".into(), principal: "agent-1".into(),
            objective_digest: h(1), policy_digest: h(2), candidate_digest: h(3),
            host: "local".into(), generation: 1, idempotency_key: "idem-1".into(),
            predecessor: None, currentness: Currentness::Current,
            final_use: FinalUse::NotGranted, rollback_reference: None,
        },
        step: 0, max_steps: 3, state_digest: h(4), deadline_unix_ms: 100,
    }
}
struct Reject;
impl ShadowStepCommitVerifier for Reject {
    fn verify_step_commit(&self, _: &AgentStepRequestV1, _: &AgentStepObservationV1,
                          _: &ShadowStepCommitV1) -> Result<(), PortError> {
        Err(PortError::Denied)
    }
}
struct Accept;
impl ShadowStepCommitVerifier for Accept {
    fn verify_step_commit(&self, _: &AgentStepRequestV1, _: &AgentStepObservationV1,
                          _: &ShadowStepCommitV1) -> Result<(), PortError> {
        Ok(())
    }
}
fn response(req: &AgentStepRequestV1, disposition: AgentStepDisposition) -> AgentStepObservationV1 {
    let action = matches!(disposition, AgentStepDisposition::InvokeModel | AgentStepDisposition::ProposeTool);
    let continues = action || disposition == AgentStepDisposition::Waiting;
    AgentStepObservationV1 {
        request_digest: req.digest().unwrap(), disposition,
        next_state_digest: continues.then(|| h(5)),
        action_digest: action.then(|| h(6)), observation_digest: h(7),
    }
}
fn commit(req: &AgentStepRequestV1, proposal: &AgentStepObservationV1) -> ShadowStepCommitV1 {
    let action = proposal.action_digest.is_some();
    ShadowStepCommitV1 {
        request_digest: req.digest().unwrap(),
        observation_digest: proposal.observation_digest.clone(),
        action_digest: proposal.action_digest.clone(),
        observed_terminal: action.then_some(PortTerminal::Succeeded),
        outcome_digest: action.then(|| h(8)),
        committed_state_digest: proposal.next_state_digest.clone(),
        owner_receipt_digest: h(9),
    }
}
#[test]
fn action_waits_for_independent_commit_and_never_executes_by_staging() {
    let mut s = ShadowAgentLoopV1::new(base()).unwrap();
    let proposed = response(s.next_request().unwrap(), AgentStepDisposition::InvokeModel);
    let witness = commit(s.next_request().unwrap(), &proposed);
    s.stage(proposed).unwrap();
    assert_eq!(s.phase(), ShadowLoopPhaseV1::AwaitingCommit);
    assert!(s.next_request().is_err());
    assert!(matches!(s.commit(witness.clone(), &Reject), Err(PortError::Denied)));
    assert_eq!(s.phase(), ShadowLoopPhaseV1::AwaitingCommit);
    let mut mismatched = witness.clone();
    mismatched.request_digest = h(30);
    assert!(s.commit(mismatched, &Accept).is_err());
    s.commit(witness, &Accept).unwrap();
    assert_eq!(s.next_request().unwrap().step, 1);
    let finished = response(s.next_request().unwrap(), AgentStepDisposition::Completed);
    let receipt = commit(s.next_request().unwrap(), &finished);
    s.stage(finished).unwrap();
    s.commit(receipt, &Accept).unwrap();
    assert_eq!(s.phase(), ShadowLoopPhaseV1::Completed);
    assert!(s.next_request().is_err());
}
#[test]
fn ambiguous_tool_outcome_is_sticky_no_replay() {
    let mut s = ShadowAgentLoopV1::new(base()).unwrap();
    let proposed = response(s.next_request().unwrap(), AgentStepDisposition::ProposeTool);
    let mut witness = commit(s.next_request().unwrap(), &proposed);
    witness.observed_terminal = Some(PortTerminal::Indeterminate);
    s.stage(proposed).unwrap();
    s.commit(witness, &Accept).unwrap();
    assert_eq!(s.phase(), ShadowLoopPhaseV1::Indeterminate);
    assert!(s.next_request().is_err());
}
#[test]
fn waiting_needs_authorized_wake() {
    let mut s = ShadowAgentLoopV1::new(base()).unwrap();
    let proposed = response(s.next_request().unwrap(), AgentStepDisposition::Waiting);
    let witness = commit(s.next_request().unwrap(), &proposed);
    s.stage(proposed).unwrap();
    s.commit(witness, &Accept).unwrap();
    assert_eq!(s.phase(), ShadowLoopPhaseV1::Waiting);
    assert!(s.resume_verified_wait(&h(5), &|_, _| Err(PortError::Denied)).is_err());
    assert!(s.next_request().is_err());
    s.resume_verified_wait(&h(5), &|_, _| Ok(())).unwrap();
    assert_eq!(s.next_request().unwrap().step, 1);
}
#[test]
fn no_false_effect_witness_or_missing_action_outcome() {
    let mut s = ShadowAgentLoopV1::new(base()).unwrap();
    let proposed = response(s.next_request().unwrap(), AgentStepDisposition::ProposeTool);
    let mut witness = commit(s.next_request().unwrap(), &proposed);
    witness.outcome_digest = None;
    s.stage(proposed).unwrap();
    assert!(s.commit(witness, &Accept).is_err());
    assert_eq!(s.phase(), ShadowLoopPhaseV1::AwaitingCommit);
}
