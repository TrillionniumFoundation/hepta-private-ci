//! Actual model terminal facts use the same bounded channel and journal writer.
use super::*;

impl AgentdSelfIterationHandleV1 {
    pub async fn begin_model(
        &self,
        round: AgentdSelfIterationRoundV1,
        request: SelfIterationModelRequestV1,
    ) -> Result<AgentdSelfIterationModelAdmissionV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(Command::Begin(round, request, response), receive)
            .await
    }
    pub async fn complete_failed_model(
        &self,
        round: AgentdSelfIterationRoundV1,
        request: SelfIterationModelRequestV1,
        failure: SelfIterationModelFailureV1,
    ) -> Result<(), AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::CompleteFailure(round, request, failure, response),
            receive,
        )
        .await
    }
}

pub(super) fn complete(
    owner: &mut SelfIterationOwner,
    round: &AgentdSelfIterationRoundV1,
    request: &SelfIterationModelRequestV1,
    assessment: &SelfIterationModelAssessmentV1,
    now: u64,
) -> Result<(), AgentdError> {
    // Late facts do not restore expired result-use authority.
    let mut rounds = owner
        .journal
        .rounds
        .clone()
        .ok_or_else(|| invalid("round not reserved"))?;
    rounds.retain_terminal_clock(now);
    rounds.complete(round, request, assessment)?;
    owner.journal.persist_rounds(rounds)
}

pub(super) fn complete_failed(
    owner: &mut SelfIterationOwner,
    round: &AgentdSelfIterationRoundV1,
    request: &SelfIterationModelRequestV1,
    failure: &SelfIterationModelFailureV1,
    now: u64,
) -> Result<(), AgentdError> {
    let mut rounds = owner
        .journal
        .rounds
        .clone()
        .ok_or_else(|| invalid("round not reserved"))?;
    rounds.retain_terminal_clock(now);
    rounds.complete_failed(round, request, failure)?;
    owner.journal.persist_rounds(rounds)
}
