//! Bounded, effect-free native Agent Loop cursor for Agentd integration.
//!
//! This is a *shadow* state machine, not an executor or durable state owner.
//! A trusted run owner must persist each accepted transition, independently
//! verify actual model/tool outcomes, and enforce FinalUse at physical entry.

use crate::ports::{
    AgentStepDisposition, AgentStepObservationV1, AgentStepRequestV1, PortError, PortTerminal,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ShadowLoopPhaseV1 {
    Ready,
    AwaitingCommit,
    Waiting,
    Completed,
    Abstained,
    Cancelled,
    Indeterminate,
}

/// An untrusted serialized record until verified against an actual owner and
/// independently observed terminal output. Its digest alone grants nothing.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowStepCommitV1 {
    pub request_digest: String,
    pub observation_digest: String,
    pub action_digest: Option<String>,
    pub observed_terminal: Option<PortTerminal>,
    pub outcome_digest: Option<String>,
    pub committed_state_digest: Option<String>,
    pub owner_receipt_digest: String,
}

/// Only an independent, authoritative owner may attest state CAS, evidence,
/// effect terminality, generation and exact operation correlation.
pub trait ShadowStepCommitVerifier: Send + Sync {
    fn verify_step_commit(
        &self,
        request: &AgentStepRequestV1,
        proposal: &AgentStepObservationV1,
        commit: &ShadowStepCommitV1,
    ) -> Result<(), PortError>;
}

fn digest_is_valid(value: &str) -> bool {
    value.len() == 64
        && value.as_bytes().iter().any(|byte| *byte != b'0')
        && value
            .as_bytes()
            .iter()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
}

/// Single live cursor. Exactly one proposal may await one owner-verified
/// commit; process restart must recover from the run-owner's durable ledger,
/// never from this volatile struct or a replayed model proposal alone.
#[derive(Debug)]
pub struct ShadowAgentLoopV1 {
    request: AgentStepRequestV1,
    phase: ShadowLoopPhaseV1,
    proposal: Option<AgentStepObservationV1>,
}

impl ShadowAgentLoopV1 {
    pub fn new(request: AgentStepRequestV1) -> Result<Self, PortError> {
        request.digest()?;
        Ok(Self {
            request,
            phase: ShadowLoopPhaseV1::Ready,
            proposal: None,
        })
    }

    pub fn phase(&self) -> ShadowLoopPhaseV1 {
        self.phase
    }

    pub fn next_request(&self) -> Result<&AgentStepRequestV1, PortError> {
        if self.phase != ShadowLoopPhaseV1::Ready {
            return Err(PortError::Invalid("agent cursor not ready"));
        }
        Ok(&self.request)
    }

    /// Stage the model's proposal only. No tool, provider, or physical action
    /// can be dispatched by this method.
    pub fn stage(&mut self, response: AgentStepObservationV1) -> Result<(), PortError> {
        self.next_request()?;
        response.validate_against(&self.request)?;
        self.proposal = Some(response);
        self.phase = ShadowLoopPhaseV1::AwaitingCommit;
        Ok(())
    }

    /// Only a verified owner receipt can advance the run. The terminal state
    /// is sticky and an unknown effect can never turn into a fresh dispatch.
    pub fn commit(
        &mut self,
        receipt: ShadowStepCommitV1,
        verifier: &impl ShadowStepCommitVerifier,
    ) -> Result<(), PortError> {
        if self.phase != ShadowLoopPhaseV1::AwaitingCommit {
            return Err(PortError::Invalid("agent cursor has no pending proposal"));
        }
        let proposal = self.proposal.as_ref().ok_or(PortError::Indeterminate)?;
        if receipt.request_digest != self.request.digest()?
            || receipt.observation_digest != proposal.observation_digest
            || receipt.committed_state_digest != proposal.next_state_digest
            || receipt.action_digest != proposal.action_digest
            || !digest_is_valid(&receipt.owner_receipt_digest)
        {
            return Err(PortError::Invalid("agent step owner correlation"));
        }
        let requires_effect = matches!(
            proposal.disposition,
            AgentStepDisposition::InvokeModel | AgentStepDisposition::ProposeTool
        );
        if requires_effect {
            if receipt.observed_terminal.is_none()
                || !receipt
                    .outcome_digest
                    .as_ref()
                    .is_some_and(|d| digest_is_valid(d))
            {
                return Err(PortError::Invalid("missing independently observed action"));
            }
        } else if receipt.observed_terminal.is_some() || receipt.outcome_digest.is_some() {
            return Err(PortError::Invalid("unexpected external action witness"));
        }
        verifier.verify_step_commit(&self.request, proposal, &receipt)?;
        self.phase = match (proposal.disposition, receipt.observed_terminal) {
            (_, Some(PortTerminal::Indeterminate)) => ShadowLoopPhaseV1::Indeterminate,
            (_, Some(PortTerminal::Cancelled)) => ShadowLoopPhaseV1::Cancelled,
            (_, Some(PortTerminal::Failed | PortTerminal::Rejected)) => {
                ShadowLoopPhaseV1::Indeterminate
            }
            (AgentStepDisposition::InvokeModel | AgentStepDisposition::ProposeTool,
             Some(PortTerminal::Succeeded)) => ShadowLoopPhaseV1::Ready,
            (AgentStepDisposition::Waiting, None) => ShadowLoopPhaseV1::Waiting,
            (AgentStepDisposition::Completed, None) => ShadowLoopPhaseV1::Completed,
            (AgentStepDisposition::Abstained, None) => ShadowLoopPhaseV1::Abstained,
            (AgentStepDisposition::Cancelled, None) => ShadowLoopPhaseV1::Cancelled,
            (AgentStepDisposition::Indeterminate, None) => ShadowLoopPhaseV1::Indeterminate,
            _ => return Err(PortError::Invalid("disposition/outcome mismatch")),
        };
        if matches!(self.phase, ShadowLoopPhaseV1::Ready | ShadowLoopPhaseV1::Waiting) {
            self.request.step += 1;
            self.request.state_digest = receipt
                .committed_state_digest
                .ok_or(PortError::Invalid("missing next state"))?;
        }
        self.proposal = None;
        Ok(())
    }

    /// Waiting cannot resume without a separately authorized wake-up and a
    /// recorded state cut. The consumer passes only an explicitly verified
    /// next-state identity; this method itself grants no execution authority.
    pub fn resume_verified_wait(
        &mut self,
        next_state_digest: &str,
        verify_wake: &impl Fn(&AgentStepRequestV1, &str) -> Result<(), PortError>,
    ) -> Result<(), PortError> {
        if self.phase != ShadowLoopPhaseV1::Waiting
            || self.request.state_digest != next_state_digest
        {
            return Err(PortError::Invalid("wake cursor/state mismatch"));
        }
        verify_wake(&self.request, next_state_digest)?;
        self.phase = ShadowLoopPhaseV1::Ready;
        Ok(())
    }
}

#[cfg(test)]
#[path = "shadow_loop_tests.rs"]
mod tests;
