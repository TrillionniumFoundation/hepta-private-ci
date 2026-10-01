//! Bounded recovery driver for unresolved durable planner dispatches.
//!
//! The driver consumes only the `DENY_ALL` pending projection, requires a
//! separately owned resolver for the exact original request, verifies the
//! resolved identities before contacting the effect owner, and invokes only
//! observation-time reconciliation. It never authorizes or redispatches an
//! effect. Product scheduling, retry policy and the effect owner remain outside
//! this module.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::GrantRequestV1;
use crate::PlannerEffectExecutorV1;
use crate::PlannerExecutionError;
use crate::PlannerPendingDispatchV1;
use crate::PlannerStoreV1;
use crate::PlannerTerminalReceiptV1;
use crate::planner_operation_identity_digest_v1;
use crate::planner_request_digest_v1;
use crate::reconcile_planner_request_v1;

/// Product-owned resolution of the exact request that created a durable claim.
/// Missing or indeterminate resolution never reaches the effect owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerPendingRequestResolutionV1 {
    Resolved(GrantRequestV1),
    Unavailable { reason_digest: Digest32 },
    Indeterminate { reason_digest: Digest32 },
}

/// Resolves a durable pending claim back to its exact original request.
///
/// Implementations must read from an authoritative product-owned request
/// ledger. A caller-provided or reconstructed best-effort request is rejected
/// by the canonical identity checks before reconciliation.
pub trait PlannerPendingRequestResolverV1 {
    fn resolve_request(
        &mut self,
        pending: &PlannerPendingDispatchV1,
    ) -> Result<PlannerPendingRequestResolutionV1, PlannerExecutionError>;
}

/// Per-claim outcome from one bounded reconciliation pass.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerPendingReconciliationDispositionV1 {
    Reconciled {
        receipt: PlannerTerminalReceiptV1,
    },
    RequestUnavailable {
        reason_digest: Digest32,
    },
    RequestIndeterminate {
        reason_digest: Digest32,
    },
    ResolverFailed {
        error: PlannerExecutionError,
    },
    RequestBindingMismatch {
        observed_operation_identity_digest: Digest32,
        observed_request_digest: Digest32,
        observed_final_payload_digest: Digest32,
    },
    ReconciliationFailed {
        error: PlannerExecutionError,
    },
}

/// Auditable result for one pending claim. This evidence remains `DENY_ALL`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerPendingReconciliationResultV1 {
    pub claim_sequence: u64,
    pub claim_record_digest: Digest32,
    pub operation_identity_digest: Digest32,
    pub disposition: PlannerPendingReconciliationDispositionV1,
    pub authority: AuthorityPosture,
}

/// Bounded round-robin recovery result. The cursor can be supplied to the next
/// pass; it is not an authorization or a redispatch token.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerPendingReconciliationBatchV1 {
    pub items: Vec<PlannerPendingReconciliationResultV1>,
    pub next_after_sequence: Option<u64>,
    pub wrapped: bool,
    pub authority: AuthorityPosture,
}

/// Reconcile at most `limit` unresolved durable claims in claim-sequence order.
///
/// Item-level resolver and observation failures are returned as evidence so a
/// later fair pass can continue. Structural store/page failures fail the whole
/// call. The function never invokes `PlannerEffectExecutorV1::execute`.
pub fn reconcile_pending_dispatches_v1<R, E>(
    store: &mut PlannerStoreV1,
    after_sequence: Option<u64>,
    limit: usize,
    resolver: &mut R,
    executor: &mut E,
) -> Result<PlannerPendingReconciliationBatchV1, PlannerExecutionError>
where
    R: PlannerPendingRequestResolverV1 + ?Sized,
    E: PlannerEffectExecutorV1 + ?Sized,
{
    let page = store.pending_dispatches_page(after_sequence, limit)?;
    if page.authority.grants_any()
        || page
            .items
            .iter()
            .any(|pending| pending.authority.grants_any())
    {
        return Err(PlannerExecutionError::Store(
            "pending dispatch projection must remain deny-all".to_string(),
        ));
    }

    let mut items = Vec::with_capacity(page.items.len());
    for pending in page.items {
        let disposition = reconcile_one(&pending, resolver, executor, store)?;
        items.push(PlannerPendingReconciliationResultV1 {
            claim_sequence: pending.claim_sequence,
            claim_record_digest: pending.claim_record_digest,
            operation_identity_digest: pending.operation_identity_digest,
            disposition,
            authority: AuthorityPosture::DENY_ALL,
        });
    }

    Ok(PlannerPendingReconciliationBatchV1 {
        items,
        next_after_sequence: page.next_after_sequence,
        wrapped: page.wrapped,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn reconcile_one<R, E>(
    pending: &PlannerPendingDispatchV1,
    resolver: &mut R,
    executor: &mut E,
    store: &mut PlannerStoreV1,
) -> Result<PlannerPendingReconciliationDispositionV1, PlannerExecutionError>
where
    R: PlannerPendingRequestResolverV1 + ?Sized,
    E: PlannerEffectExecutorV1 + ?Sized,
{
    let resolution = match resolver.resolve_request(pending) {
        Ok(resolution) => resolution,
        Err(error) => {
            return Ok(PlannerPendingReconciliationDispositionV1::ResolverFailed { error });
        }
    };

    let request = match resolution {
        PlannerPendingRequestResolutionV1::Resolved(request) => request,
        PlannerPendingRequestResolutionV1::Unavailable { reason_digest } => {
            if reason_digest.is_zero() {
                return Ok(PlannerPendingReconciliationDispositionV1::ResolverFailed {
                    error: PlannerExecutionError::EmptyDigest("pending request unavailable reason"),
                });
            }
            return Ok(
                PlannerPendingReconciliationDispositionV1::RequestUnavailable { reason_digest },
            );
        }
        PlannerPendingRequestResolutionV1::Indeterminate { reason_digest } => {
            if reason_digest.is_zero() {
                return Ok(PlannerPendingReconciliationDispositionV1::ResolverFailed {
                    error: PlannerExecutionError::EmptyDigest(
                        "pending request indeterminate reason",
                    ),
                });
            }
            return Ok(
                PlannerPendingReconciliationDispositionV1::RequestIndeterminate { reason_digest },
            );
        }
    };

    let observed_operation_identity_digest = planner_operation_identity_digest_v1(&request);
    let observed_request_digest = planner_request_digest_v1(&request);
    if observed_operation_identity_digest != pending.operation_identity_digest
        || observed_request_digest != pending.request_digest
        || request.final_payload_digest != pending.final_payload_digest
    {
        return Ok(
            PlannerPendingReconciliationDispositionV1::RequestBindingMismatch {
                observed_operation_identity_digest,
                observed_request_digest,
                observed_final_payload_digest: request.final_payload_digest,
            },
        );
    }

    match reconcile_planner_request_v1(&request, pending.original_grant_digest, executor, store) {
        Ok(receipt) => Ok(PlannerPendingReconciliationDispositionV1::Reconciled { receipt }),
        Err(error @ PlannerExecutionError::Store(_)) => Err(error),
        Err(error) => Ok(PlannerPendingReconciliationDispositionV1::ReconciliationFailed { error }),
    }
}

#[cfg(test)]
#[path = "planner_reconciliation_controller_tests.rs"]
mod tests;
