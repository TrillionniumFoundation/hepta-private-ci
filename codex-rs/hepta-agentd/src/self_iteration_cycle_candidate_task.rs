//! A caller may leave, but the one actual original assembly task remains owned.
use super::*;
pub(super) struct PendingCandidate<A> {
    round: Option<AgentdSelfIterationRoundV1>,
    execution: Digest32,
    task: tokio::task::JoinHandle<(A, Result<AgentdSelfIterationCandidateV1, AgentdError>)>,
}
impl<M, A, O> AgentdSelfIterationModelCycleV1<M, A, O>
where
    M: SelfIterationModelPortV1 + 'static,
    A: AgentdSelfIterationCandidateAssemblerV1 + 'static,
    O: AgentdSelfIterationIndependentOwnersV1,
{
    pub(super) async fn construct_candidate(
        &mut self,
        envelope: IterationEnvelopeV1,
        proposal: SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSelfIterationCandidateV1, AgentdError> {
        if let Some(candidate) = &self.constructed_candidate {
            if candidate.envelope != envelope
                || self.round.is_some() && candidate.model_assessment.as_ref() != Some(&proposal)
                || candidate.round != self.round
            {
                return Err(invalid("retained candidate differs from original round"));
            }
            return Ok(candidate.clone());
        }
        if self.pending_candidate.is_none() {
            let mut completed_only = false;
            if let Some(round) = &self.round {
                let status = self
                    .runtime
                    .inspect_round(
                        StableId::new(round.goal_id())
                            .map_err(|error| invalid(error.to_string()))?,
                        round.canonical_policy_digest(),
                    )
                    .await?;
                completed_only = match status.candidate_effects {
                    AgentdSelfIterationCandidateEffectsV1::NotStarted => false,
                    AgentdSelfIterationCandidateEffectsV1::Started => true,
                    AgentdSelfIterationCandidateEffectsV1::LegacyUnknown => {
                        return Err(invalid("legacy candidate effects remain unknown"));
                    }
                };
            }
            let assembler = self
                .assembler
                .as_mut()
                .ok_or_else(|| invalid("original candidate assembler unavailable"))?;
            if !completed_only {
                if let AgentdSelfIterationCandidateEffectAdmissionV1::RejectedBeforeCandidateEffects(
                reason,
            ) = assembler
                .validate_before_candidate_effects(&envelope, &proposal)
                .await?
            {
                if let Some(round) = &self.round {
                    self.runtime
                        .reject_proposal_before_candidate_effects(round.clone(), proposal, reason)
                        .await?;
                }
                return Err(AgentdError::SelfIterationProposalRejected);
            }
                if let Some(round) = &self.round
                    && self
                        .runtime
                        .begin_candidate_effects(round.clone(), proposal.clone())
                        .await?
                        != AgentdSelfIterationCandidateConstructionAdmissionV1::Fresh
                {
                    return Err(invalid(
                        "original candidate effects already admitted; no reissue",
                    ));
                }
            }
            let mut assembler = self
                .assembler
                .take()
                .ok_or_else(|| invalid("original candidate assembler unavailable"))?;
            let execution = envelope_digest(&envelope);
            let assembly_envelope = envelope.clone();
            let task = tokio::spawn(async move {
                let result = if completed_only {
                    assembler.recover_completed(assembly_envelope,&proposal).await.and_then(|candidate|
                        candidate.ok_or_else(||invalid("original candidate effects have no completed recovery; no reissue")))
                } else {
                    assembler.assemble(assembly_envelope, &proposal).await
                };
                (assembler, result)
            });
            self.pending_candidate = Some(PendingCandidate {
                round: self.round.clone(),
                execution,
                task,
            });
        }
        let pending = self
            .pending_candidate
            .as_mut()
            .ok_or_else(|| invalid("actual candidate task missing"))?;
        if pending.round != self.round || pending.execution != envelope_digest(&envelope) {
            return Err(invalid("actual candidate task identity changed"));
        }
        let joined = (&mut pending.task).await;
        self.pending_candidate = None;
        let (assembler, result) =
            joined.map_err(|error| invalid(format!("actual candidate task: {error}")))?;
        self.assembler = Some(assembler);
        let candidate = result?;
        self.constructed_candidate = Some(candidate.clone());
        Ok(candidate)
    }
}

#[cfg(test)]
#[path = "self_iteration_cycle_candidate_task_tests.rs"]
mod tests;
