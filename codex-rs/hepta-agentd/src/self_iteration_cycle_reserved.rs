//! Installed preparation reuses an actual sole-owner reservation, never a second debit.
use super::*;

impl<M, A, O> AgentdSelfIterationModelCycleV1<M, A, O>
where
    M: SelfIterationModelPortV1 + 'static,
    A: AgentdSelfIterationCandidateAssemblerV1 + 'static,
    O: AgentdSelfIterationIndependentOwnersV1,
{
    /// Return this same adapter only after the sole owner has settled the exact
    /// round and every original model task. No new model client is constructed.
    pub async fn take_model_after_terminal_round(&mut self) -> Result<M, AgentdError> {
        let current = self.runtime.inspect_current_round().await?
            .ok_or_else(|| invalid("original terminal reservation absent"))?;
        if self.round.as_ref() != Some(&current.status.round)
            || !current.can_admit_next_round()
            || self.pending_model.is_some() || self.pending_candidate.is_some()
        {
            return Err(invalid("original cycle still owns unresolved effects"));
        }
        self.model.take().ok_or_else(|| invalid("original model adapter unavailable"))
    }

    pub async fn run_reserved_round(
        &mut self,
        round: AgentdSelfIterationRoundV1,
        canonical: crate::CanonicalIterationEnvelopeV1,
        envelope: IterationEnvelopeV1,
        objective_prompt: String,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        payload::validate_canonical_execution(&canonical, &envelope)?;
        let current = self
            .runtime
            .inspect_current_round()
            .await?
            .ok_or_else(|| invalid("installed cycle lacks an original reserved round"))?;
        if current.status.round != round
            || round.canonical_policy_digest() != canonical.digest()
            || round.execution_envelope_digest() != envelope_digest(&envelope)
            || current.status.terminal
        {
            return Err(invalid(
                "installed cycle changed original reserved Goal, round or policy",
            ));
        }
        let now = now_ms()?;
        if now >= round.deadline_ms()
            || now < round.admitted_at_ms()
            || now < current.status.observed_clock_ms
        {
            return Err(invalid("original reserved round deadline or clock expired"));
        }
        if objective_prompt.is_empty() || objective_prompt.len() > 2 * 1024 {
            return Err(invalid("self-iteration objective prompt budget"));
        }
        if self.round.as_ref() != Some(&round) {
            if self.pending_candidate.is_some() {
                return Err(invalid("original candidate task still owned"));
            }
            self.constructed_candidate = None;
            self.actual_description = None;
        }
        if let Some(assembler) = &mut self.assembler {
            assembler.bind_round(round.clone(), canonical.clone())?;
        }
        self.round = Some(round);
        self.canonical = Some(canonical);
        self.run_inner(envelope, objective_prompt).await
    }
}
