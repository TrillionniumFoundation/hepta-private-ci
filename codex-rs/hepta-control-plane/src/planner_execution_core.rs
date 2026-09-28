//! Authority-separated execution and reconciliation for planner requests.
//!
//! The planner remains advisory. A named authority adapter must issue and then
//! revalidate a final-payload-bound grant immediately before dispatch. A named
//! executor reports an observed terminal or indeterminate outcome, and a
//! durable sink records the receipt. These traits are composition boundaries;
//! their existence does not activate a production authority or executor.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::GrantRequestV1;
use crate::PlannerDispatchClaimOutcomeV1;
use crate::PlannerDispatchClaimSinkV1;
use crate::PlannerStoreError;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerExecutionGrantV1 {
    pub grant_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub expires_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerAuthorizationDecisionV1 {
    Granted(PlannerExecutionGrantV1),
    Denied { reason_digest: Digest32 },
    Indeterminate { reason_digest: Digest32 },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerAuthorityRevalidationV1 {
    Current,
    Revoked,
    Indeterminate,
}

pub trait PlannerAuthorityConsumerV1 {
    fn authorize(
        &mut self,
        request: &GrantRequestV1,
        now_micros: u64,
    ) -> Result<PlannerAuthorizationDecisionV1, PlannerExecutionError>;

    fn revalidate(
        &mut self,
        request: &GrantRequestV1,
        grant: &PlannerExecutionGrantV1,
        now_micros: u64,
    ) -> Result<PlannerAuthorityRevalidationV1, PlannerExecutionError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerEffectDispositionV1 {
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerEffectObservationV1 {
    pub disposition: PlannerEffectDispositionV1,
    pub outcome_digest: Digest32,
    pub observed_at_micros: u64,
}

pub trait PlannerEffectExecutorV1 {
    fn execute(
        &mut self,
        request: &GrantRequestV1,
        grant: &PlannerExecutionGrantV1,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError>;

    fn reconcile(
        &mut self,
        operation_identity_digest: Digest32,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerTerminalReceiptV1 {
    pub operation_identity_digest: Digest32,
    pub request_digest: Digest32,
    pub grant_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub disposition: PlannerEffectDispositionV1,
    pub outcome_digest: Digest32,
    pub observed_at_micros: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// A first dispatch and a later reconciliation have different durable record
/// identities. This permits an indeterminate first observation to converge to
/// a later terminal observation without reusing or overwriting the dispatch
/// receipt identity.
pub trait PlannerTerminalReceiptSinkV1 {
    fn append_terminal_receipt(
        &mut self,
        receipt: &PlannerTerminalReceiptV1,
    ) -> Result<(), PlannerExecutionError>;

    fn append_reconciliation_receipt(
        &mut self,
        receipt: &PlannerTerminalReceiptV1,
    ) -> Result<(), PlannerExecutionError> {
        self.append_terminal_receipt(receipt)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerExecutionError {
    EmptyDigest(&'static str),
    ExpiredRequest,
    AuthorizationDenied(Digest32),
    AuthorizationIndeterminate(Digest32),
    GrantMismatch,
    GrantExpired,
    AuthorityRevoked,
    AuthorityIndeterminate,
    InvalidObservation,
    Store(String),
}

impl fmt::Display for PlannerExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerExecutionError {}

impl From<PlannerStoreError> for PlannerExecutionError {
    fn from(error: PlannerStoreError) -> Self {
        Self::Store(error.to_string())
    }
}

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
    S: PlannerTerminalReceiptSinkV1 + ?Sized,
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
            return Err(PlannerExecutionError::AuthorizationIndeterminate(
                reason_digest,
            ));
        }
    };
    validate_grant(request, &grant, now_micros)?;
    match authority.revalidate(request, &grant, now_micros)? {
        PlannerAuthorityRevalidationV1::Current => {}
        PlannerAuthorityRevalidationV1::Revoked => {
            return Err(PlannerExecutionError::AuthorityRevoked);
        }
        PlannerAuthorityRevalidationV1::Indeterminate => {
            return Err(PlannerExecutionError::AuthorityIndeterminate);
        }
    }
    let observation = executor.execute(request, &grant)?;
    let receipt = terminal_receipt(request, &grant, observation)?;
    sink.append_terminal_receipt(&receipt)?;
    Ok(receipt)
}

/// Reconcile a previously indeterminate operation without replaying dispatch.
/// The sink receives a reconciliation record, not a second initial terminal
/// record with the same operation identity.
pub fn reconcile_planner_request_v1<E, S>(
    request: &GrantRequestV1,
    grant_digest: Digest32,
    executor: &mut E,
    sink: &mut S,
) -> Result<PlannerTerminalReceiptV1, PlannerExecutionError>
where
    E: PlannerEffectExecutorV1 + ?Sized,
    S: PlannerTerminalReceiptSinkV1 + ?Sized,
{
    require_digest(grant_digest, "reconciliation grant")?;
    let operation_identity_digest = operation_identity_digest(request);
    let observation = executor.reconcile(operation_identity_digest)?;
    let grant = PlannerExecutionGrantV1 {
        grant_digest,
        final_payload_digest: request.final_payload_digest,
        revocation_frontier_digest: request.revocation_frontier_digest,
        expires_at_micros: request.expires_at_micros,
    };
    let receipt = terminal_receipt(request, &grant, observation)?;
    sink.append_reconciliation_receipt(&receipt)?;
    Ok(receipt)
}

impl PlannerTerminalReceiptSinkV1 for PlannerStoreV1 {
    fn append_terminal_receipt(
        &mut self,
        receipt: &PlannerTerminalReceiptV1,
    ) -> Result<(), PlannerExecutionError> {
        if admit_store_receipt(self, receipt)? {
            return Ok(());
        }
        append_store_receipt(
            self,
            PlannerStoreRecordKindV1::TerminalReceipt,
            receipt.operation_identity_digest,
            receipt,
        )
    }

    fn append_reconciliation_receipt(
        &mut self,
        receipt: &PlannerTerminalReceiptV1,
    ) -> Result<(), PlannerExecutionError> {
        if admit_store_receipt(self, receipt)? {
            return Ok(());
        }
        let mut bytes = b"hepta.control.reconciliation-identity.v1".to_vec();
        bytes.extend_from_slice(receipt.operation_identity_digest.as_array());
        bytes.extend_from_slice(receipt.receipt_digest.as_array());
        append_store_receipt(
            self,
            PlannerStoreRecordKindV1::Reconciliation,
            Digest32::of_bytes(&bytes),
            receipt,
        )
    }
}

/// Validate both receipt integrity and the durable operation state before the
/// generic envelope store is allowed to accept an execution observation.
///
/// Returning `true` means the exact conclusive receipt is already committed and
/// the retry is idempotently complete. A different receipt may advance only an
/// unresolved claim; it can never replace a conclusive terminal observation.
fn admit_store_receipt(
    store: &PlannerStoreV1,
    receipt: &PlannerTerminalReceiptV1,
) -> Result<bool, PlannerExecutionError> {
    validate_terminal_receipt_integrity(receipt)?;
    let state = <PlannerStoreV1 as PlannerDispatchClaimSinkV1>::inspect_dispatch(
        store,
        receipt.operation_identity_digest,
        receipt.request_digest,
        receipt.final_payload_digest,
    )?;
    match state {
        None => Err(PlannerExecutionError::Store(
            "terminal receipt requires a durable dispatch claim".to_string(),
        )),
        Some(PlannerDispatchClaimOutcomeV1::Acquired) => Err(PlannerExecutionError::Store(
            "invalid acquired state while appending terminal receipt".to_string(),
        )),
        Some(PlannerDispatchClaimOutcomeV1::ExistingClaim {
            original_grant_digest,
        }) => {
            if original_grant_digest != receipt.grant_digest {
                return Err(PlannerExecutionError::Store(
                    "terminal receipt grant does not match durable dispatch claim".to_string(),
                ));
            }
            Ok(false)
        }
        Some(PlannerDispatchClaimOutcomeV1::ExistingTerminal { receipt: existing }) => {
            if existing.as_ref() == receipt {
                Ok(true)
            } else {
                Err(PlannerExecutionError::Store(
                    "conclusive terminal receipt is immutable".to_string(),
                ))
            }
        }
    }
}

fn validate_terminal_receipt_integrity(
    receipt: &PlannerTerminalReceiptV1,
) -> Result<(), PlannerExecutionError> {
    require_digest(receipt.operation_identity_digest, "terminal operation")?;
    require_digest(receipt.request_digest, "terminal request")?;
    require_digest(receipt.grant_digest, "terminal grant")?;
    require_digest(receipt.final_payload_digest, "terminal final payload")?;
    require_digest(receipt.outcome_digest, "terminal outcome")?;
    require_digest(receipt.receipt_digest, "terminal receipt")?;
    if receipt.authority.grants_any() {
        return Err(PlannerExecutionError::InvalidObservation);
    }
    let expected = digest_terminal_receipt(
        receipt.operation_identity_digest,
        receipt.request_digest,
        receipt.grant_digest,
        receipt.final_payload_digest,
        receipt.disposition,
        receipt.outcome_digest,
        receipt.observed_at_micros,
    );
    if receipt.receipt_digest != expected {
        return Err(PlannerExecutionError::InvalidObservation);
    }
    Ok(())
}

fn append_store_receipt(
    store: &mut PlannerStoreV1,
    kind: PlannerStoreRecordKindV1,
    identity_digest: Digest32,
    receipt: &PlannerTerminalReceiptV1,
) -> Result<(), PlannerExecutionError> {
    let envelope = encode_terminal_receipt(receipt);
    store.append(kind, identity_digest, receipt.receipt_digest, &envelope)?;
    Ok(())
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

fn digest_terminal_receipt(
    operation_identity_digest: Digest32,
    request_digest: Digest32,
    grant_digest: Digest32,
    final_payload_digest: Digest32,
    disposition: PlannerEffectDispositionV1,
    outcome_digest: Digest32,
    observed_at_micros: u64,
) -> Digest32 {
    let mut bytes = b"hepta.control.execution-terminal.v1".to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(grant_digest.as_array());
    bytes.extend_from_slice(final_payload_digest.as_array());
    bytes.push(match disposition {
        PlannerEffectDispositionV1::Succeeded => 0,
        PlannerEffectDispositionV1::Failed => 1,
        PlannerEffectDispositionV1::Indeterminate => 2,
    });
    bytes.extend_from_slice(outcome_digest.as_array());
    bytes.extend_from_slice(&observed_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn encode_terminal_receipt(receipt: &PlannerTerminalReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.execution-terminal-envelope.v1".to_vec();
    bytes.extend_from_slice(receipt.operation_identity_digest.as_array());
    bytes.extend_from_slice(receipt.request_digest.as_array());
    bytes.extend_from_slice(receipt.grant_digest.as_array());
    bytes.extend_from_slice(receipt.final_payload_digest.as_array());
    bytes.push(match receipt.disposition {
        PlannerEffectDispositionV1::Succeeded => 0,
        PlannerEffectDispositionV1::Failed => 1,
        PlannerEffectDispositionV1::Indeterminate => 2,
    });
    bytes.extend_from_slice(receipt.outcome_digest.as_array());
    bytes.extend_from_slice(&receipt.observed_at_micros.to_be_bytes());
    bytes.extend_from_slice(receipt.receipt_digest.as_array());
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
