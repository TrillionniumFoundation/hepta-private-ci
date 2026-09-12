//! Evidence-bound settlement of owner-local indeterminate runs.

use super::AgentRunCoordinator;
use super::AgentRunError;
use super::RunPhase;
use super::RunReceipt;
use super::RunSnapshot;
use super::RuntimeComposition;
use super::advance_revision;
use super::receipt;
use super::require_revision;
use super::validate_digest;
use super::validate_identity;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReconciledRunOutcome {
    Cancelled,
    Succeeded,
    Failed,
    /// The canonical owner durably accepted the unresolved effect for quarantine.
    /// This releases local admission capacity, but is NOT observed effect success.
    Quarantined,
}

/// The full statement authenticated by the current-fence execution observer.
/// A digest, a timestamp, or a caller-supplied identity alone is not authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunReconciliation {
    pub composition: RuntimeComposition,
    pub snapshot: RunSnapshot,
    pub expected_revision: u64,
    pub current_authority_epoch: u64,
    pub observation_id: String,
    pub evidence_digest: String,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub outcome: ReconciledRunOutcome,
}

/// Trusted host port for independently authenticated, currently authorized
/// observations. Implementations must bind EVERY field of the statement to the
/// retained owner receipt, check the live authority epoch and revocation state,
/// and prove durable quarantine handoff for `Quarantined`. They must not derive
/// trust from the statement itself, dispatch effects, or silently retry them.
/// No permissive production implementation is supplied by this coordinator.
pub trait RunReconciliationVerifier {
    fn verify_current_observation(
        &mut self,
        now_ms: u64,
        observation: &RunReconciliation,
    ) -> Result<(), AgentRunError>;
}

impl AgentRunCoordinator {
    /// Settle uncertainty using a current observer without executing any work.
    /// Request deadlines may have elapsed: expiry stops new work, not recovery.
    /// Even an equal replay must pass current authorization before it is exposed.
    pub fn reconcile_run<V: RunReconciliationVerifier + ?Sized>(
        &mut self,
        now_ms: u64,
        observation: RunReconciliation,
        verifier: &mut V,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(&observation.observation_id, "observation")?;
        validate_digest(&observation.evidence_digest, "reconciliation evidence")?;
        if observation.observed_at_ms > now_ms || observation.valid_until_ms <= now_ms {
            return Err(AgentRunError::InvalidObservationWindow);
        }
        if observation.composition != self.composition {
            return Err(AgentRunError::StaleComposition);
        }
        let record = self
            .runs
            .get_mut(&observation.snapshot.run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if observation.snapshot != record.snapshot {
            return Err(AgentRunError::MixedSnapshot);
        }
        if observation.current_authority_epoch < record.snapshot.authority_epoch {
            return Err(AgentRunError::StaleAuthorityEpoch);
        }
        verifier.verify_current_observation(now_ms, &observation)?;
        if let Some(previous) = &record.reconciliation {
            return if previous == &observation {
                Ok(receipt(record, /*idempotent*/ true))
            } else {
                Err(AgentRunError::Conflict)
            };
        }
        require_revision(record, observation.expected_revision)?;
        if record.phase != RunPhase::Indeterminate {
            return Err(AgentRunError::InvalidTransition);
        }
        advance_revision(record)?;
        record.phase = match observation.outcome {
            ReconciledRunOutcome::Cancelled => RunPhase::Cancelled,
            ReconciledRunOutcome::Succeeded => RunPhase::Succeeded,
            ReconciledRunOutcome::Failed => RunPhase::Failed,
            ReconciledRunOutcome::Quarantined => RunPhase::Quarantined,
        };
        record.reconciliation = Some(observation);
        Ok(receipt(record, /*idempotent*/ false))
    }
}
