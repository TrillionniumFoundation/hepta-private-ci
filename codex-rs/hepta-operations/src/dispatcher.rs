use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArmedDispatch;
use crate::DispatchClaim;
use crate::DispatchObservation;
use crate::DurableOperationRecord;
use crate::DurableOperationState;
use crate::DurableOperationStore;
use crate::OperationError;
use crate::ReconciliationOutcome;

/// Product adapters implement this only at a boundary that can provide its
/// stated acknowledgement/terminal evidence. Queue acceptance must use
/// `Acknowledged`, never `Terminal::Applied`.
pub trait EffectAdapter {
    fn dispatch(&mut self, dispatch: &ArmedDispatch) -> DispatchObservation;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReconciliationObservation {
    Terminal {
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
    },
    Unknown {
        reason_digest: Digest32,
    },
}

/// An observer is authoritative for terminal state at the destination. It does
/// not receive effect authority and must not replay the operation while
/// observing it.
pub trait TerminalObserver {
    fn observe(&mut self, operation: &DurableOperationRecord) -> ReconciliationObservation;
}

impl DurableOperationStore {
    /// Consume the real non-serializable kernel.authority token immediately
    /// around adapter entry. The dispatch attempt is durably armed first; from
    /// that point any crash is reconciled rather than blindly retried.
    pub async fn dispatch_with_final_use<A: EffectAdapter>(
        &self,
        claim: DispatchClaim,
        authority: &FinalUseAuthority,
        signed_grant: &SignedFinalUseGrant,
        expected_binding: &FinalUseBinding,
        dispatch_digest: Digest32,
        adapter: &mut A,
    ) -> Result<DispatchObservation, OperationError> {
        validate_final_use_binding(&claim.operation, signed_grant, expected_binding)?;
        let token = match authority.claim(signed_grant, expected_binding) {
            Ok(token) => token,
            Err(error) => {
                // No external effect was entered, so releasing the pre-dispatch
                // lease is safe. Failure to release is recovered by lease expiry.
                let _ = self.retry_claim(&claim.lease, 0).await;
                return Err(map_authority_error(error));
            }
        };
        let armed = self.arm_dispatch(&claim.lease, dispatch_digest).await?;
        let observation = match authority.with_verified_use(token, expected_binding, || {
            adapter.dispatch(&armed)
        }) {
            Ok(observation) => observation.validate()?,
            Err(error) => {
                // with_verified_use checks live revocation/expiry before calling
                // the consumer. A failure therefore proves this armed attempt did
                // not enter the adapter and can settle as NotApplied.
                let digest = authority_error_digest(error);
                self.observe_terminal(
                    &armed.operation.intent.scope_id,
                    &armed.operation.intent.operation_id,
                    armed.writer_generation,
                    ReconciliationOutcome::NotApplied,
                    digest,
                    None,
                )
                .await?;
                return Err(map_authority_error(error));
            }
        };
        match observation {
            DispatchObservation::Acknowledged {
                acknowledgement_digest,
            } => {
                self.acknowledge_dispatch(&armed, acknowledgement_digest)
                    .await?;
            }
            DispatchObservation::Terminal {
                outcome,
                evidence_digest,
                acknowledgement_digest,
            } => {
                self.observe_terminal(
                    &armed.operation.intent.scope_id,
                    &armed.operation.intent.operation_id,
                    armed.writer_generation,
                    outcome,
                    evidence_digest,
                    acknowledgement_digest,
                )
                .await?;
            }
            DispatchObservation::Indeterminate { reason_digest } => {
                self.mark_dispatch_indeterminate(&armed, reason_digest)
                    .await?;
            }
        }
        Ok(observation)
    }

    /// Query a destination-owned observer for a previously dispatched operation.
    /// Unknown results never make the outbox retryable. An already acknowledged
    /// dispatch remains acknowledged; an explicitly indeterminate dispatch stays
    /// indeterminate until a terminal observation exists.
    pub async fn reconcile_with<O: TerminalObserver>(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        observer_generation: Generation,
        observer: &mut O,
    ) -> Result<ReconciliationObservation, OperationError> {
        let operation = self
            .operation(scope_id, operation_id)
            .await?
            .ok_or_else(|| OperationError::Missing(operation_id.clone()))?;
        if operation.state.is_terminal() {
            return Err(OperationError::Terminal);
        }
        if observer_generation < operation.intent.writer_generation {
            return Err(OperationError::StaleGeneration);
        }
        if !matches!(
            operation.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(OperationError::InvalidTransition {
                from: operation.state.as_str(),
                to: "reconciliation",
            });
        }
        let observation = observer.observe(&operation);
        match observation {
            ReconciliationObservation::Terminal {
                outcome,
                evidence_digest,
            } => {
                if evidence_digest.is_zero() {
                    return Err(OperationError::InvalidDigest("terminal outcome"));
                }
                self.observe_terminal(
                    scope_id,
                    operation_id,
                    observer_generation,
                    outcome,
                    evidence_digest,
                    None,
                )
                .await?;
            }
            ReconciliationObservation::Unknown { reason_digest } => {
                if reason_digest.is_zero() {
                    return Err(OperationError::InvalidDigest("indeterminate reason"));
                }
            }
        }
        Ok(observation)
    }
}

fn validate_final_use_binding(
    operation: &DurableOperationRecord,
    signed_grant: &SignedFinalUseGrant,
    expected: &FinalUseBinding,
) -> Result<(), OperationError> {
    let intent = &operation.intent;
    if signed_grant.grant.authority_epoch != intent.authority_epoch.get()
        || expected.destination_id != intent.destination_id.as_str()
        || expected.request_sha256 != *intent.request_digest.as_array()
        || expected.scope_sha256 != *intent.scope_digest.as_array()
        || expected.payload_sha256 != *intent.payload_digest.as_array()
    {
        return Err(OperationError::AuthorityRejected);
    }
    Ok(())
}

fn authority_error_digest(error: FinalUseError) -> Digest32 {
    Digest32::of_bytes(format!("hepta.kernel.operations.final-use-rejected.v1:{error:?}").as_bytes())
}

fn map_authority_error(error: FinalUseError) -> OperationError {
    match error {
        FinalUseError::Unavailable | FinalUseError::StateLocked => {
            OperationError::Unavailable(format!("kernel.authority: {error}"))
        }
        _ => OperationError::AuthorityRejected,
    }
}
