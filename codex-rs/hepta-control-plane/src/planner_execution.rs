//! Durable dispatch admission around the authority-separated execution core.
//!
//! `planner_execution_core.rs` retains grant validation, final authority
//! revalidation, effect observation and terminal receipt construction. This
//! wrapper persists an exact operation/request/grant claim before that core can
//! call the executor. A retry that sees an existing claim fails closed into
//! reconciliation instead of replaying the side effect.

#[path = "planner_execution_core.rs"]
mod core;

pub use core::PlannerAuthorizationDecisionV1;
pub use core::PlannerAuthorityConsumerV1;
pub use core::PlannerAuthorityRevalidationV1;
pub use core::PlannerEffectDispositionV1;
pub use core::PlannerEffectExecutorV1;
pub use core::PlannerEffectObservationV1;
pub use core::PlannerExecutionError;
pub use core::PlannerExecutionGrantV1;
pub use core::PlannerTerminalReceiptSinkV1;
pub use core::PlannerTerminalReceiptV1;
pub use core::reconcile_planner_request_v1;

use codex_hepta_types::Digest32;

use crate::GrantRequestV1;
use crate::PlannerDispatchClaimSinkV1;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreV1;

/// Authorize once, persist the exact dispatch claim, then revalidate through
/// the canonical core immediately before executor invocation.
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
    validate_request(request, now_micros)?;
    let grant = match authority.authorize(request, now_micros)? {
        PlannerAuthorizationDecisionV1::Granted(grant) => grant,
        PlannerAuthorizationDecisionV1::Denied { reason_digest } => {
            require_digest(reason_digest, "authorization denial")?;
            return Err(PlannerExecutionError::AuthorizationDenied(reason_digest));
        }
        PlannerAuthorizationDecisionV1::Indeterminate { reason_digest } => {
            require_digest(reason_digest, "authorization indeterminate")?;
            return Err(PlannerExecutionError::AuthorizationIndeterminate(reason_digest));
        }
    };
    validate_grant(request, &grant, now_micros)?;

    let operation_identity_digest = operation_identity_digest(request);
    let request_digest = request_digest(request);
    if !sink.claim_dispatch(
        operation_identity_digest,
        request_digest,
        grant.grant_digest,
        request.final_payload_digest,
        now_micros,
    )? {
        return Err(PlannerExecutionError::Store(
            "dispatch already claimed; reconcile without replay".to_string(),
        ));
    }

    let mut preauthorized = PreauthorizedAuthority {
        inner: authority,
        grant,
    };
    core::execute_planner_request_v1(
        request,
        now_micros,
        &mut preauthorized,
        executor,
        sink,
    )
}

struct PreauthorizedAuthority<'a, A: ?Sized> {
    inner: &'a mut A,
    grant: PlannerExecutionGrantV1,
}

impl<A> PlannerAuthorityConsumerV1 for PreauthorizedAuthority<'_, A>
where
    A: PlannerAuthorityConsumerV1 + ?Sized,
{
    fn authorize(
        &mut self,
        _request: &GrantRequestV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorizationDecisionV1, PlannerExecutionError> {
        Ok(PlannerAuthorizationDecisionV1::Granted(self.grant.clone()))
    }

    fn revalidate(
        &mut self,
        request: &GrantRequestV1,
        grant: &PlannerExecutionGrantV1,
        now_micros: u64,
    ) -> Result<PlannerAuthorityRevalidationV1, PlannerExecutionError> {
        self.inner.revalidate(request, grant, now_micros)
    }
}

impl PlannerDispatchClaimSinkV1 for PlannerStoreV1 {
    fn claim_dispatch(
        &mut self,
        operation_identity_digest: Digest32,
        request_digest: Digest32,
        grant_digest: Digest32,
        final_payload_digest: Digest32,
        claimed_at_micros: u64,
    ) -> Result<bool, PlannerExecutionError> {
        require_digest(operation_identity_digest, "dispatch operation")?;
        require_digest(request_digest, "dispatch request")?;
        require_digest(grant_digest, "dispatch grant")?;
        require_digest(final_payload_digest, "dispatch payload")?;

        if self.records().iter().any(|record| {
            record.kind == PlannerStoreRecordKindV1::TerminalReceipt
                && record.operation_identity_digest == operation_identity_digest
        }) {
            return Ok(false);
        }

        let claim_identity_digest = dispatch_claim_identity(operation_identity_digest);
        let claim_digest = dispatch_claim_digest(
            operation_identity_digest,
            request_digest,
            grant_digest,
            final_payload_digest,
            claimed_at_micros,
        );
        if let Some(existing) = self
            .records()
            .iter()
            .find(|record| record.operation_identity_digest == claim_identity_digest)
        {
            if existing.kind == PlannerStoreRecordKindV1::Selection
                && existing.payload_digest == claim_digest
            {
                return Ok(false);
            }
            return Err(PlannerExecutionError::Store(
                "dispatch claim identity conflict".to_string(),
            ));
        }

        let envelope = encode_dispatch_claim(
            operation_identity_digest,
            request_digest,
            grant_digest,
            final_payload_digest,
            claimed_at_micros,
            claim_digest,
        );
        self.append(
            PlannerStoreRecordKindV1::Selection,
            claim_identity_digest,
            claim_digest,
            &envelope,
        )?;
        Ok(true)
    }
}

fn validate_request(
    request: &GrantRequestV1,
    now_micros: u64,
) -> Result<(), PlannerExecutionError> {
    require_digest(request.plan_digest, "request plan")?;
    require_digest(request.final_payload_digest, "request final payload")?;
    require_digest(request.objective_digest, "request objective")?;
    require_digest(request.snapshot_digest, "request snapshot")?;
    require_digest(request.revocation_frontier_digest, "request revocation frontier")?;
    if now_micros >= request.expires_at_micros {
        return Err(PlannerExecutionError::ExpiredRequest);
    }
    Ok(())
}

fn validate_grant(
    request: &GrantRequestV1,
    grant: &PlannerExecutionGrantV1,
    now_micros: u64,
) -> Result<(), PlannerExecutionError> {
    require_digest(grant.grant_digest, "grant")?;
    if grant.final_payload_digest != request.final_payload_digest
        || grant.revocation_frontier_digest != request.revocation_frontier_digest
    {
        return Err(PlannerExecutionError::GrantMismatch);
    }
    if now_micros >= grant.expires_at_micros
        || grant.expires_at_micros > request.expires_at_micros
    {
        return Err(PlannerExecutionError::GrantExpired);
    }
    Ok(())
}

fn operation_identity_digest(request: &GrantRequestV1) -> Digest32 {
    let mut bytes = b"hepta.control.execution-operation.v1".to_vec();
    push_id(&mut bytes, request.operation_id.as_str());
    push_id(&mut bytes, request.candidate_id.as_str());
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.final_payload_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn request_digest(request: &GrantRequestV1) -> Digest32 {
    let mut bytes = b"hepta.control.execution-request.v1".to_vec();
    push_id(&mut bytes, request.operation_id.as_str());
    push_id(&mut bytes, request.candidate_id.as_str());
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.final_payload_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    bytes.extend_from_slice(request.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn dispatch_claim_identity(operation_identity_digest: Digest32) -> Digest32 {
    let mut bytes = b"hepta.control.execution-dispatch-claim-identity.v1".to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn dispatch_claim_digest(
    operation_identity_digest: Digest32,
    request_digest: Digest32,
    grant_digest: Digest32,
    final_payload_digest: Digest32,
    claimed_at_micros: u64,
) -> Digest32 {
    let mut bytes = b"hepta.control.execution-dispatch-claim.v1".to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(grant_digest.as_array());
    bytes.extend_from_slice(final_payload_digest.as_array());
    bytes.extend_from_slice(&claimed_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn encode_dispatch_claim(
    operation_identity_digest: Digest32,
    request_digest: Digest32,
    grant_digest: Digest32,
    final_payload_digest: Digest32,
    claimed_at_micros: u64,
    claim_digest: Digest32,
) -> Vec<u8> {
    let mut bytes = b"hepta.control.execution-dispatch-claim-envelope.v1".to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(grant_digest.as_array());
    bytes.extend_from_slice(final_payload_digest.as_array());
    bytes.extend_from_slice(&claimed_at_micros.to_be_bytes());
    bytes.extend_from_slice(claim_digest.as_array());
    bytes
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u64::try_from(value.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), PlannerExecutionError> {
    if value.is_zero() {
        return Err(PlannerExecutionError::EmptyDigest(field));
    }
    Ok(())
}

#[cfg(test)]
#[path = "planner_execution_tests.rs"]
mod tests;
