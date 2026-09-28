//! Durable Abort/Enter arbitration inside the existing run coordinator.
use std::path::Path;

use super::*;
use crate::CodexEffectBinding;
use crate::CodexEffectDecision;
use crate::CodexEffectReceipt;
use crate::codex_effect_journal::CodexEffectJournal;

impl AgentRunCoordinator {
    pub(crate) fn open_effect_frontier(&mut self, path: &Path) -> Result<(), AgentRunError> {
        if self.effects.is_some() {
            return Err(AgentRunError::Conflict);
        }
        self.effects = Some(CodexEffectJournal::open(path, &self.composition.agent_id)?);
        Ok(())
    }

    pub(crate) fn decide_codex_effect(
        &mut self,
        now_ms: u64,
        binding: CodexEffectBinding,
        decision: CodexEffectDecision,
        reason: Option<String>,
    ) -> Result<CodexEffectReceipt, AgentRunError> {
        binding
            .validate()
            .map_err(|_| AgentRunError::InvalidIdentity("Codex effect binding"))?;
        if binding.generation != self.composition.agentd_generation {
            return Err(AgentRunError::InvalidGeneration);
        }
        match (decision, reason.as_deref()) {
            (CodexEffectDecision::Entered, None) => {}
            (CodexEffectDecision::AbortedBeforeEffect, Some(reason)) => {
                validate_cancel_reason(reason)?
            }
            _ => return Err(AgentRunError::InvalidTransition),
        }
        let effects = self
            .effects
            .as_mut()
            .ok_or(AgentRunError::EffectFrontierUnavailable)?;
        if let Some(receipt) = effects.replay(&binding, decision, reason.as_deref())? {
            return Ok(receipt);
        }
        let current = self
            .runs
            .get(&binding.run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        require_revision(current, binding.expected_revision)?;
        if current.phase != RunPhase::ContextAttached
            || current.snapshot.generation != binding.generation
            || current.context_digest.as_ref() != Some(&binding.context_digest)
            || current.compilation_receipt_digest.as_ref()
                != Some(&binding.compilation_receipt_digest)
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        let mut next = current.clone();
        match decision {
            CodexEffectDecision::Entered => {
                if !self.accepting_runs {
                    return Err(AgentRunError::AdmissionClosed);
                }
                require_live_deadline(current, now_ms)?;
                next.phase = RunPhase::Dispatched;
            }
            CodexEffectDecision::AbortedBeforeEffect => {
                // No Enter has been durably issued and ContextAttached is
                // still current. This owner fact, NOT a client digest/boolean,
                // is the negative proof. Aborting remains possible after expiry.
                next.phase = RunPhase::Cancelled;
                next.pre_effect_aborted = true;
                next.cancel_reason = reason.clone();
                next.cancel_ack_deadline_ms = None;
            }
        }
        advance_revision(&mut next)?;
        let receipt = CodexEffectReceipt {
            binding,
            decision,
            reason,
            owner_revision: next.revision,
            idempotent: false,
        };
        effects.commit(&receipt, /*legacy*/ false)?;
        // No fallible operation between durable decision and owner publication.
        self.runs.insert(receipt.binding.run_id.clone(), next);
        Ok(receipt)
    }
}

#[cfg(test)]
#[path = "codex_effect_owner_tests.rs"]
mod tests;
