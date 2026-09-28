//! Durable dispatch state machine.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::PlannerAuthorizationDecisionV1;
use super::PlannerAuthorityConsumerV1;
use super::PlannerAuthorityRevalidationV1;
use super::PlannerEffectDispositionV1;
use super::PlannerEffectExecutorV1;
use super::PlannerEffectObservationV1;
use super::PlannerExecutionError;
use super::PlannerExecutionGrantV1;
use super::PlannerTerminalReceiptSinkV1;
use super::PlannerTerminalReceiptV1;
use super::codec::decode_dispatch_claim;
use super::codec::decode_terminal_receipt;
use super::codec::digest_terminal_receipt;
use super::codec::dispatch_claim_digest_v2;
use super::codec::dispatch_claim_identity;
use super::codec::encode_dispatch_claim_v2;
use super::codec::operation_identity_digest;
use super::codec::request_digest;
use super::codec::require_digest;
use super::codec::store_error;
use super::codec::validate_existing_operation;
use super::codec::validate_grant;
use super::codec::validate_request_expiry;
use super::codec::validate_request_identity;
use super::core;

use crate::GrantRequestV1;
use crate::PlannerDispatchClaimOutcomeV1;
use crate::PlannerDispatchClaimSinkV1;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreV1;

/// Consult durable operation state before authorizing or dispatching an effect.
///
/// A conclusive prior receipt is returned even after the original execution
/// request expires. An unresolved claim is queried through the effect owner's
/// observation-only `reconcile` port. Only an operation with no durable state
/// can acquire a fresh grant and reach the executor.
pub fn execute_planner_request_v1<A, E, S>(
    request: &GrantRequestV1,
    now_micros: u64,
    authority: &mut A,
    executor: &mut E,
    sink: &mut S,
) -> Result<PlannerTerminalReceiptV1, PlannerExecutionError>
where
    A: PlannerAuthorityConsumerV1 + ?Sized,
    E: PlannerEffectExecutorV1 + ?Sized,
    S: PlannerDispatchClaimSinkV1 + ?Sized,
{
    validate_request_identity(request)?;
    let operation_identity_digest = operation_identity_digest(request);
    let request_digest = request_digest(request);
    if let Some(existing) = sink.inspect_dispatch(
        operation_identity_digest,
        request_digest,
        request.final_payload_digest,
    )? {
        return resolve_existing_dispatch(request, executor, sink, existing);
    }

    validate_request_expiry(request, now_micros)?;
    let grant = authorize_and_validate(request, now_micros, authority)?;
    let state = sink.claim_dispatch(
        operation_identity_digest,
        request_digest,
        grant.grant_digest,
        request.final_payload_digest,
        now_micros,
    )?;
    match state {
        PlannerDispatchClaimOutcomeV1::Acquired => execute_claimed_dispatch(
            request, now_micros, authority, executor, sink, &grant,
        ),
        existing => resolve_existing_dispatch(request, executor, sink, existing),
    }
}

/// Reconcile only an operation that already owns a durable dispatch claim.
///
/// This public entry cannot create a claim, cannot redispatch, and cannot append
/// a later observation after a conclusive terminal result. The caller-supplied
/// grant digest must equal the exact grant recorded by the first attempt.
pub fn reconcile_planner_request_v1<E, S>(
    request: &GrantRequestV1,
    grant_digest: Digest32,
    executor: &mut E,
    sink: &mut S,
) -> Result<PlannerTerminalReceiptV1, PlannerExecutionError>
where
    E: PlannerEffectExecutorV1 + ?Sized,
    S: PlannerDispatchClaimSinkV1 + ?Sized,
{
    validate_request_identity(request)?;
    require_digest(grant_digest, "reconciliation grant")?;
    let state = sink.inspect_dispatch(
        operation_identity_digest(request),
        request_digest(request),
        request.final_payload_digest,
    )?;
    match state {
        Some(PlannerDispatchClaimOutcomeV1::ExistingTerminal { receipt }) => Ok(*receipt),
        Some(PlannerDispatchClaimOutcomeV1::ExistingClaim {
            original_grant_digest,
        }) => {
            if original_grant_digest != grant_digest {
                return Err(store_error(
                    "reconciliation grant does not match durable claim",
                ));
            }
            core::reconcile_planner_request_v1(request, original_grant_digest, executor, sink)
        }
        Some(PlannerDispatchClaimOutcomeV1::Acquired) => Err(store_error(
            "invalid acquired state during reconciliation",
        )),
        None => Err(store_error(
            "reconciliation requires a durable dispatch claim",
        )),
    }
}

fn resolve_existing_dispatch<E, S>(
    request: &GrantRequestV1,
    executor: &mut E,
    sink: &mut S,
    state: PlannerDispatchClaimOutcomeV1,
) -> Result<PlannerTerminalReceiptV1, PlannerExecutionError>
where
    E: PlannerEffectExecutorV1 + ?Sized,
    S: PlannerTerminalReceiptSinkV1 + ?Sized,
{
    match state {
        PlannerDispatchClaimOutcomeV1::ExistingTerminal { receipt } => Ok(*receipt),
        PlannerDispatchClaimOutcomeV1::ExistingClaim {
            original_grant_digest,
        } => core::reconcile_planner_request_v1(
            request,
            original_grant_digest,
            executor,
            sink,
        ),
        PlannerDispatchClaimOutcomeV1::Acquired => Err(store_error(
            "invalid acquired state while resolving durable dispatch",
        )),
    }
}

fn execute_claimed_dispatch<A, E, S>(
    request: &GrantRequestV1,
    now_micros: u64,
    authority: &mut A,
    executor: &mut E,
    sink: &mut S,
    grant: &PlannerExecutionGrantV1,
) -> Result<PlannerTerminalReceiptV1, PlannerExecutionError>
where
    A: PlannerAuthorityConsumerV1 + ?Sized,
    E: PlannerEffectExecutorV1 + ?Sized,
    S: PlannerTerminalReceiptSinkV1 + ?Sized,
{
    match authority.revalidate(request, grant, now_micros)? {
        PlannerAuthorityRevalidationV1::Current => {
            let mut prevalidated = PrevalidatedAuthorityV1 {
                grant: grant.clone(),
            };
            core::execute_planner_request_v1(
                request,
                now_micros,
                &mut prevalidated,
                executor,
                sink,
            )
        }
        PlannerAuthorityRevalidationV1::Revoked => {
            persist_not_dispatched(
                request,
                grant,
                now_micros,
                b"hepta.control.dispatch-not-invoked.authority-revoked.v1",
                sink,
            )?;
            Err(PlannerExecutionError::AuthorityRevoked)
        }
        PlannerAuthorityRevalidationV1::Indeterminate => {
            persist_not_dispatched(
                request,
                grant,
                now_micros,
                b"hepta.control.dispatch-not-invoked.authority-indeterminate.v1",
                sink,
            )?;
            Err(PlannerExecutionError::AuthorityIndeterminate)
        }
    }
}

struct PrevalidatedAuthorityV1 {
    grant: PlannerExecutionGrantV1,
}

impl PlannerAuthorityConsumerV1 for PrevalidatedAuthorityV1 {
    fn authorize(
        &mut self,
        _request: &GrantRequestV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorizationDecisionV1, PlannerExecutionError> {
        Ok(PlannerAuthorizationDecisionV1::Granted(self.grant.clone()))
    }

    fn revalidate(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorityRevalidationV1, PlannerExecutionError> {
        Ok(PlannerAuthorityRevalidationV1::Current)
    }
}

fn persist_not_dispatched<S>(
    request: &GrantRequestV1,
    grant: &PlannerExecutionGrantV1,
    observed_at_micros: u64,
    domain: &[u8],
    sink: &mut S,
) -> Result<(), PlannerExecutionError>
where
    S: PlannerTerminalReceiptSinkV1 + ?Sized,
{
    let receipt = terminal_receipt(
        request,
        grant,
        PlannerEffectObservationV1 {
            disposition: PlannerEffectDispositionV1::Failed,
            outcome_digest: Digest32::of_bytes(domain),
            observed_at_micros,
        },
    )?;
    sink.append_terminal_receipt(&receipt)
}

fn terminal_receipt(
    request: &GrantRequestV1,
    grant: &PlannerExecutionGrantV1,
    observation: PlannerEffectObservationV1,
) -> Result<PlannerTerminalReceiptV1, PlannerExecutionError> {
    require_digest(observation.outcome_digest, "effect outcome")?;
    let operation_identity_digest = operation_identity_digest(request);
    let request_digest = request_digest(request);
    let receipt_digest = digest_terminal_receipt(
        operation_identity_digest,
        request_digest,
        grant.grant_digest,
        request.final_payload_digest,
        observation.disposition,
        observation.outcome_digest,
        observation.observed_at_micros,
    );
    Ok(PlannerTerminalReceiptV1 {
        operation_identity_digest,
        request_digest,
        grant_digest: grant.grant_digest,
        final_payload_digest: request.final_payload_digest,
        disposition: observation.disposition,
        outcome_digest: observation.outcome_digest,
        observed_at_micros: observation.observed_at_micros,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn authorize_and_validate<A>(
    request: &GrantRequestV1,
    now_micros: u64,
    authority: &mut A,
) -> Result<PlannerExecutionGrantV1, PlannerExecutionError>
where
    A: PlannerAuthorityConsumerV1 + ?Sized,
{
    let grant = match authority.authorize(request, now_micros)? {
        PlannerAuthorizationDecisionV1::Granted(grant) => grant,
        PlannerAuthorizationDecisionV1::Denied { reason_digest } => {
            require_digest(reason_digest, "authorization denial")?;
            return Err(PlannerExecutionError::AuthorizationDenied(reason_digest));
        }
        PlannerAuthorizationDecisionV1::Indeterminate { reason_digest } => {
            require_digest(reason_digest, "authorization indeterminate")?;
            return Err(PlannerExecutionError::AuthorizationIndeterminate(
                reason_digest,
            ));
        }
    };
    validate_grant(request, &grant, now_micros)?;
    Ok(grant)
}

impl PlannerDispatchClaimSinkV1 for PlannerStoreV1 {
    fn inspect_dispatch(
        &self,
        operation_identity_digest: Digest32,
        request_digest: Digest32,
        final_payload_digest: Digest32,
    ) -> Result<Option<PlannerDispatchClaimOutcomeV1>, PlannerExecutionError> {
        self.ensure_healthy()?;
        require_digest(operation_identity_digest, "dispatch operation")?;
        require_digest(request_digest, "dispatch request")?;
        require_digest(final_payload_digest, "dispatch payload")?;

        let mut latest_receipt = None;
        for record in self.records().iter().filter(|record| {
            matches!(
                record.kind,
                PlannerStoreRecordKindV1::TerminalReceipt
                    | PlannerStoreRecordKindV1::Reconciliation
            )
        }) {
            let receipt = decode_terminal_receipt(record)?;
            if receipt.operation_identity_digest != operation_identity_digest {
                continue;
            }
            validate_existing_operation(
                receipt.operation_identity_digest,
                receipt.request_digest,
                receipt.final_payload_digest,
                operation_identity_digest,
                request_digest,
                final_payload_digest,
            )?;
            latest_receipt = Some(receipt);
        }
        if let Some(receipt) = latest_receipt {
            return match receipt.disposition {
                PlannerEffectDispositionV1::Succeeded | PlannerEffectDispositionV1::Failed => {
                    Ok(Some(PlannerDispatchClaimOutcomeV1::ExistingTerminal {
                        receipt: Box::new(receipt),
                    }))
                }
                PlannerEffectDispositionV1::Indeterminate => {
                    Ok(Some(PlannerDispatchClaimOutcomeV1::ExistingClaim {
                        original_grant_digest: receipt.grant_digest,
                    }))
                }
            };
        }

        let claim_identity_digest = dispatch_claim_identity(operation_identity_digest);
        if let Some(existing) = self
            .records()
            .iter()
            .find(|record| record.operation_identity_digest == claim_identity_digest)
        {
            if existing.kind != PlannerStoreRecordKindV1::Selection {
                return Err(store_error("dispatch claim record kind conflict"));
            }
            let claim = decode_dispatch_claim(existing)?;
            validate_existing_operation(
                claim.operation_identity_digest,
                claim.request_digest,
                claim.final_payload_digest,
                operation_identity_digest,
                request_digest,
                final_payload_digest,
            )?;
            return Ok(Some(PlannerDispatchClaimOutcomeV1::ExistingClaim {
                original_grant_digest: claim.grant_digest,
            }));
        }
        Ok(None)
    }

    fn claim_dispatch(
        &mut self,
        operation_identity_digest: Digest32,
        request_digest: Digest32,
        grant_digest: Digest32,
        final_payload_digest: Digest32,
        claimed_at_micros: u64,
    ) -> Result<PlannerDispatchClaimOutcomeV1, PlannerExecutionError> {
        require_digest(grant_digest, "dispatch grant")?;
        if let Some(existing) = self.inspect_dispatch(
            operation_identity_digest,
            request_digest,
            final_payload_digest,
        )? {
            return Ok(existing);
        }

        let claim_identity_digest = dispatch_claim_identity(operation_identity_digest);
        let claim_digest = dispatch_claim_digest_v2(
            operation_identity_digest,
            request_digest,
            grant_digest,
            final_payload_digest,
        );
        let envelope = encode_dispatch_claim_v2(
            operation_identity_digest,
            request_digest,
            grant_digest,
            final_payload_digest,
            claimed_at_micros,
            claim_digest,
        );
        self.append_execution_record(
            PlannerStoreRecordKindV1::Selection,
            claim_identity_digest,
            claim_digest,
            &envelope,
        )?;
        Ok(PlannerDispatchClaimOutcomeV1::Acquired)
    }
}
