use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::GrantRequestSetV1;
use crate::GrantRequestV1;
use crate::PlannerStoreError;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EffectTerminalStatusV1 {
    Succeeded,
    Failed,
    Indeterminate,
}

impl EffectTerminalStatusV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Succeeded => 0,
            Self::Failed => 1,
            Self::Indeterminate => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityGrantV1 {
    request_set_digest: Digest32,
    request_digest: Digest32,
    grant_digest: Digest32,
    authority_epoch: u64,
    revocation_frontier_digest: Digest32,
    final_payload_digest: Digest32,
    expires_at_micros: u64,
    opaque_capability: Vec<u8>,
}

impl AuthorityGrantV1 {
    pub fn admit_external(
        request_set_digest: Digest32,
        request_digest: Digest32,
        authority_epoch: u64,
        revocation_frontier_digest: Digest32,
        final_payload_digest: Digest32,
        expires_at_micros: u64,
        opaque_capability: Vec<u8>,
    ) -> Result<Self, PlannerExecutionError> {
        if request_set_digest.is_zero()
            || request_digest.is_zero()
            || authority_epoch == 0
            || revocation_frontier_digest.is_zero()
            || final_payload_digest.is_zero()
            || expires_at_micros == 0
            || opaque_capability.is_empty()
        {
            return Err(PlannerExecutionError::InvalidAuthorityGrant);
        }
        let mut bytes = b"hepta.control.external-authority-grant.v1\0".to_vec();
        bytes.extend_from_slice(request_set_digest.as_array());
        bytes.extend_from_slice(request_digest.as_array());
        bytes.extend_from_slice(&authority_epoch.to_be_bytes());
        bytes.extend_from_slice(revocation_frontier_digest.as_array());
        bytes.extend_from_slice(final_payload_digest.as_array());
        bytes.extend_from_slice(&expires_at_micros.to_be_bytes());
        bytes.extend_from_slice(&(opaque_capability.len() as u64).to_be_bytes());
        bytes.extend_from_slice(&opaque_capability);
        let grant_digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            request_set_digest,
            request_digest,
            grant_digest,
            authority_epoch,
            revocation_frontier_digest,
            final_payload_digest,
            expires_at_micros,
            opaque_capability,
        })
    }

    #[must_use]
    pub const fn request_set_digest(&self) -> Digest32 {
        self.request_set_digest
    }

    #[must_use]
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    #[must_use]
    pub const fn grant_digest(&self) -> Digest32 {
        self.grant_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub const fn revocation_frontier_digest(&self) -> Digest32 {
        self.revocation_frontier_digest
    }

    #[must_use]
    pub const fn final_payload_digest(&self) -> Digest32 {
        self.final_payload_digest
    }

    #[must_use]
    pub const fn expires_at_micros(&self) -> u64 {
        self.expires_at_micros
    }

    #[must_use]
    pub fn opaque_capability(&self) -> &[u8] {
        &self.opaque_capability
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectTerminalReceiptV1 {
    pub operation_identity_digest: Digest32,
    pub grant_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub status: EffectTerminalStatusV1,
    pub observed_outcome_digest: Digest32,
    pub terminal_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReconciliationReceiptV1 {
    pub operation_identity_digest: Digest32,
    pub terminal_receipt_digest: Digest32,
    pub reconciled_state_digest: Digest32,
    pub reconciled_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableExecutionReceiptV1 {
    pub decision_identity_digest: Digest32,
    pub request_set_digest: Digest32,
    pub terminal_receipt_digests: Vec<Digest32>,
    pub reconciliation_receipt_digests: Vec<Digest32>,
    pub batch_digest: Digest32,
}

pub trait IndependentAuthorityPortV1 {
    fn authorize(
        &mut self,
        request_set_digest: Digest32,
        request: &GrantRequestV1,
        request_digest: Digest32,
        now_micros: u64,
    ) -> Result<AuthorityGrantV1, PlannerExecutionError>;

    fn revalidate_immediately_before_dispatch(
        &mut self,
        grant: &AuthorityGrantV1,
        request: &GrantRequestV1,
        now_micros: u64,
    ) -> Result<(), PlannerExecutionError>;
}

pub trait EffectExecutorPortV1 {
    fn execute(
        &mut self,
        operation_identity_digest: Digest32,
        grant: &AuthorityGrantV1,
    ) -> Result<EffectTerminalReceiptV1, PlannerExecutionError>;
}

pub trait EffectReconcilerPortV1 {
    fn reconcile(
        &mut self,
        terminal: &EffectTerminalReceiptV1,
    ) -> Result<ReconciliationReceiptV1, PlannerExecutionError>;
}

#[derive(Debug)]
pub enum PlannerExecutionError {
    Store(PlannerStoreError),
    InvalidDecisionEnvelope,
    PlannerAttemptedToGrantAuthority,
    InvalidAuthorityGrant,
    AuthorityUnavailable,
    AuthorityRejected,
    AuthorityExpired,
    AuthorityBindingMismatch,
    EffectUnavailable,
    InvalidTerminalReceipt,
    ReconciliationUnavailable,
    InvalidReconciliationReceipt,
}

impl fmt::Display for PlannerExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerExecutionError {}

impl From<PlannerStoreError> for PlannerExecutionError {
    fn from(error: PlannerStoreError) -> Self {
        Self::Store(error)
    }
}

#[derive(Debug)]
pub struct DurablePlannerExecutionCoordinatorV1<'a> {
    store: &'a mut PlannerStoreV1,
}

impl<'a> DurablePlannerExecutionCoordinatorV1<'a> {
    pub fn new(store: &'a mut PlannerStoreV1) -> Self {
        Self { store }
    }

    pub fn execute<A, E, R>(
        &mut self,
        decision_identity_digest: Digest32,
        canonical_decision_envelope: &[u8],
        request_set: &GrantRequestSetV1,
        authority: &mut A,
        executor: &mut E,
        reconciler: &mut R,
        now_micros: u64,
    ) -> Result<DurableExecutionReceiptV1, PlannerExecutionError>
    where
        A: IndependentAuthorityPortV1,
        E: EffectExecutorPortV1,
        R: EffectReconcilerPortV1,
    {
        if decision_identity_digest.is_zero() || canonical_decision_envelope.is_empty() {
            return Err(PlannerExecutionError::InvalidDecisionEnvelope);
        }
        if request_set.authority().grants_any() {
            return Err(PlannerExecutionError::PlannerAttemptedToGrantAuthority);
        }
        self.store
            .append_decision_envelope(decision_identity_digest, canonical_decision_envelope)?;

        let mut terminal_receipt_digests = Vec::new();
        let mut reconciliation_receipt_digests = Vec::new();
        for request in request_set.requests() {
            let request_envelope = encode_grant_request(request_set.request_set_digest(), request);
            let request_digest = Digest32::of_bytes(&request_envelope);
            self.store.append(
                PlannerStoreRecordKindV1::GrantRequestEnvelope,
                request_digest,
                &request_envelope,
            )?;

            let grant = authority.authorize(
                request_set.request_set_digest(),
                request,
                request_digest,
                now_micros,
            )?;
            validate_grant(request_set.request_set_digest(), request, request_digest, &grant, now_micros)?;
            let grant_envelope = encode_authority_grant(&grant);
            self.store.append(
                PlannerStoreRecordKindV1::AuthorityDecisionEnvelope,
                grant.grant_digest(),
                &grant_envelope,
            )?;

            authority.revalidate_immediately_before_dispatch(&grant, request, now_micros)?;
            validate_grant(request_set.request_set_digest(), request, request_digest, &grant, now_micros)?;
            let operation_identity_digest = operation_identity(request_digest, grant.grant_digest());
            let terminal = executor.execute(operation_identity_digest, &grant)?;
            let terminal_envelope = encode_terminal_receipt(&terminal)?;
            let terminal_digest = Digest32::of_bytes(&terminal_envelope);
            validate_terminal(operation_identity_digest, &grant, &terminal, terminal_digest)?;
            self.store
                .append_effect_terminal_envelope(operation_identity_digest, &terminal_envelope)?;
            terminal_receipt_digests.push(terminal_digest);

            let reconciliation = reconciler.reconcile(&terminal)?;
            let reconciliation_envelope = encode_reconciliation_receipt(&reconciliation)?;
            let reconciliation_digest = Digest32::of_bytes(&reconciliation_envelope);
            if reconciliation.operation_identity_digest != operation_identity_digest
                || reconciliation.terminal_receipt_digest != terminal_digest
                || reconciliation.reconciled_state_digest.is_zero()
                || reconciliation.reconciled_at_micros < terminal.terminal_at_micros
            {
                return Err(PlannerExecutionError::InvalidReconciliationReceipt);
            }
            self.store.append_reconciliation_envelope(
                operation_identity_digest,
                &reconciliation_envelope,
            )?;
            reconciliation_receipt_digests.push(reconciliation_digest);
        }

        let batch_digest = digest_batch(
            decision_identity_digest,
            request_set.request_set_digest(),
            &terminal_receipt_digests,
            &reconciliation_receipt_digests,
        );
        Ok(DurableExecutionReceiptV1 {
            decision_identity_digest,
            request_set_digest: request_set.request_set_digest(),
            terminal_receipt_digests,
            reconciliation_receipt_digests,
            batch_digest,
        })
    }
}

fn validate_grant(
    request_set_digest: Digest32,
    request: &GrantRequestV1,
    request_digest: Digest32,
    grant: &AuthorityGrantV1,
    now_micros: u64,
) -> Result<(), PlannerExecutionError> {
    if grant.request_set_digest != request_set_digest
        || grant.request_digest != request_digest
        || grant.final_payload_digest != request.final_payload_digest
        || grant.revocation_frontier_digest != request.revocation_frontier_digest
        || grant.expires_at_micros > request.expires_at_micros
    {
        return Err(PlannerExecutionError::AuthorityBindingMismatch);
    }
    if now_micros >= grant.expires_at_micros {
        return Err(PlannerExecutionError::AuthorityExpired);
    }
    Ok(())
}

fn validate_terminal(
    operation_identity_digest: Digest32,
    grant: &AuthorityGrantV1,
    terminal: &EffectTerminalReceiptV1,
    terminal_digest: Digest32,
) -> Result<(), PlannerExecutionError> {
    if operation_identity_digest.is_zero()
        || terminal_digest.is_zero()
        || terminal.operation_identity_digest != operation_identity_digest
        || terminal.grant_digest != grant.grant_digest
        || terminal.final_payload_digest != grant.final_payload_digest
        || terminal.observed_outcome_digest.is_zero()
        || terminal.terminal_at_micros == 0
    {
        return Err(PlannerExecutionError::InvalidTerminalReceipt);
    }
    Ok(())
}

fn encode_grant_request(request_set_digest: Digest32, request: &GrantRequestV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.grant-request-envelope.v1\0".to_vec();
    bytes.extend_from_slice(request_set_digest.as_array());
    push_id(&mut bytes, request.operation_id.as_str());
    push_id(&mut bytes, request.candidate_id.as_str());
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.final_payload_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    bytes.extend_from_slice(request.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    bytes
}

fn encode_authority_grant(grant: &AuthorityGrantV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.authority-grant-envelope.v1\0".to_vec();
    bytes.extend_from_slice(grant.request_set_digest.as_array());
    bytes.extend_from_slice(grant.request_digest.as_array());
    bytes.extend_from_slice(grant.grant_digest.as_array());
    bytes.extend_from_slice(&grant.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(grant.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(grant.final_payload_digest.as_array());
    bytes.extend_from_slice(&grant.expires_at_micros.to_be_bytes());
    bytes.extend_from_slice(&(grant.opaque_capability.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&grant.opaque_capability);
    bytes
}

fn encode_terminal_receipt(
    receipt: &EffectTerminalReceiptV1,
) -> Result<Vec<u8>, PlannerExecutionError> {
    if receipt.operation_identity_digest.is_zero()
        || receipt.grant_digest.is_zero()
        || receipt.final_payload_digest.is_zero()
        || receipt.observed_outcome_digest.is_zero()
        || receipt.terminal_at_micros == 0
    {
        return Err(PlannerExecutionError::InvalidTerminalReceipt);
    }
    let mut bytes = b"hepta.control.effect-terminal-envelope.v1\0".to_vec();
    bytes.extend_from_slice(receipt.operation_identity_digest.as_array());
    bytes.extend_from_slice(receipt.grant_digest.as_array());
    bytes.extend_from_slice(receipt.final_payload_digest.as_array());
    bytes.push(receipt.status.tag());
    bytes.extend_from_slice(receipt.observed_outcome_digest.as_array());
    bytes.extend_from_slice(&receipt.terminal_at_micros.to_be_bytes());
    Ok(bytes)
}

fn encode_reconciliation_receipt(
    receipt: &ReconciliationReceiptV1,
) -> Result<Vec<u8>, PlannerExecutionError> {
    if receipt.operation_identity_digest.is_zero()
        || receipt.terminal_receipt_digest.is_zero()
        || receipt.reconciled_state_digest.is_zero()
        || receipt.reconciled_at_micros == 0
    {
        return Err(PlannerExecutionError::InvalidReconciliationReceipt);
    }
    let mut bytes = b"hepta.control.reconciliation-envelope.v1\0".to_vec();
    bytes.extend_from_slice(receipt.operation_identity_digest.as_array());
    bytes.extend_from_slice(receipt.terminal_receipt_digest.as_array());
    bytes.extend_from_slice(receipt.reconciled_state_digest.as_array());
    bytes.extend_from_slice(&receipt.reconciled_at_micros.to_be_bytes());
    Ok(bytes)
}

fn operation_identity(request_digest: Digest32, grant_digest: Digest32) -> Digest32 {
    let mut bytes = b"hepta.control.authorized-effect-operation.v1\0".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(grant_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_batch(
    decision_identity: Digest32,
    request_set_digest: Digest32,
    terminals: &[Digest32],
    reconciliations: &[Digest32],
) -> Digest32 {
    let mut bytes = b"hepta.control.durable-execution-batch.v1\0".to_vec();
    bytes.extend_from_slice(decision_identity.as_array());
    bytes.extend_from_slice(request_set_digest.as_array());
    bytes.extend_from_slice(&(terminals.len() as u64).to_be_bytes());
    for digest in terminals {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(reconciliations.len() as u64).to_be_bytes());
    for digest in reconciliations {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
#[path = "planner_execution_tests.rs"]
mod tests;
