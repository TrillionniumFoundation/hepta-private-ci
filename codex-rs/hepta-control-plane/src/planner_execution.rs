use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CanonicalDecisionEnvelopeV1;
use crate::GrantRequestV1;
use crate::PlannerStoreError;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductExecutionPhaseV1 {
    DecisionDurable,
    AuthorityRequested,
    IndependentlyAuthorized,
    Dispatched,
    Succeeded,
    Failed,
    Indeterminate,
    Reconciled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CurrentExecutionFenceV1 {
    pub snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub now_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndependentAuthorizationV1 {
    pub authority_principal: StableId,
    pub signed_grant_digest: Digest32,
    pub operation_id: StableId,
    pub candidate_id: StableId,
    pub plan_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub expires_at_micros: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EffectTerminalDispositionV1 {
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectTerminalReceiptV1 {
    pub operation_identity_digest: Digest32,
    pub observed_outcome_digest: Digest32,
    pub disposition: EffectTerminalDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductExecutionRecordV1 {
    pub operation_identity_digest: Digest32,
    pub phase: ProductExecutionPhaseV1,
    pub decision_envelope_digest: Digest32,
    pub authority_request_digest: Option<Digest32>,
    pub signed_grant_digest: Option<Digest32>,
    pub terminal_receipt_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductExecutionErrorV1 {
    Store(String),
    EmptyDigest(&'static str),
    DuplicateOperation,
    UnknownOperation,
    InvalidPhase,
    SnapshotDrift,
    RevocationDrift,
    FinalPayloadDrift,
    GrantExpired,
    AuthorizationBindingMismatch,
    TerminalBindingMismatch,
}

impl fmt::Display for ProductExecutionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductExecutionErrorV1 {}

impl From<PlannerStoreError> for ProductExecutionErrorV1 {
    fn from(error: PlannerStoreError) -> Self {
        Self::Store(error.to_string())
    }
}

#[derive(Debug, Default)]
pub struct ControlRuntimeExecutionConsumerV1 {
    operations: BTreeMap<Digest32, ProductExecutionRecordV1>,
}

impl ControlRuntimeExecutionConsumerV1 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn operation(
        &self,
        operation_identity_digest: Digest32,
    ) -> Option<&ProductExecutionRecordV1> {
        self.operations.get(&operation_identity_digest)
    }

    pub fn commit_decision(
        &mut self,
        store: &mut PlannerStoreV1,
        envelope: &CanonicalDecisionEnvelopeV1,
    ) -> Result<ProductExecutionRecordV1, ProductExecutionErrorV1> {
        let identity = envelope.operation_identity_digest;
        if self.operations.contains_key(&identity) {
            return Err(ProductExecutionErrorV1::DuplicateOperation);
        }
        let decision_envelope_digest = envelope.digest()?;
        store.append_decision(envelope)?;
        let record = ProductExecutionRecordV1 {
            operation_identity_digest: identity,
            phase: ProductExecutionPhaseV1::DecisionDurable,
            decision_envelope_digest,
            authority_request_digest: None,
            signed_grant_digest: None,
            terminal_receipt_digest: None,
        };
        self.operations.insert(identity, record.clone());
        Ok(record)
    }

    pub fn record_authority_request(
        &mut self,
        store: &mut PlannerStoreV1,
        operation_identity_digest: Digest32,
        request: &GrantRequestV1,
    ) -> Result<ProductExecutionRecordV1, ProductExecutionErrorV1> {
        let record = self.require_phase_mut(
            operation_identity_digest,
            ProductExecutionPhaseV1::DecisionDurable,
        )?;
        let payload = encode_grant_request(request);
        let receipt = store.append(PlannerStoreRecordKindV1::AuthorityRequest, &payload)?;
        record.phase = ProductExecutionPhaseV1::AuthorityRequested;
        record.authority_request_digest = Some(receipt.payload_digest);
        Ok(record.clone())
    }

    pub fn consume_independent_authorization(
        &mut self,
        store: &mut PlannerStoreV1,
        operation_identity_digest: Digest32,
        request: &GrantRequestV1,
        current: &CurrentExecutionFenceV1,
        grant: &IndependentAuthorizationV1,
    ) -> Result<ProductExecutionRecordV1, ProductExecutionErrorV1> {
        validate_current_authorization(request, current, grant)?;
        let record = self.require_phase_mut(
            operation_identity_digest,
            ProductExecutionPhaseV1::AuthorityRequested,
        )?;
        let mut payload = b"hepta.control.independent-authorization.v1\0".to_vec();
        payload.extend_from_slice(grant.signed_grant_digest.as_array());
        payload.extend_from_slice(grant.authority_principal.as_str().as_bytes());
        store.append(PlannerStoreRecordKindV1::AuthorityRequest, &payload)?;
        record.phase = ProductExecutionPhaseV1::IndependentlyAuthorized;
        record.signed_grant_digest = Some(grant.signed_grant_digest);
        Ok(record.clone())
    }

    pub fn mark_dispatched(
        &mut self,
        store: &mut PlannerStoreV1,
        operation_identity_digest: Digest32,
        dispatch_receipt: &[u8],
    ) -> Result<ProductExecutionRecordV1, ProductExecutionErrorV1> {
        if dispatch_receipt.is_empty() {
            return Err(ProductExecutionErrorV1::EmptyDigest("dispatch receipt"));
        }
        let record = self.require_phase_mut(
            operation_identity_digest,
            ProductExecutionPhaseV1::IndependentlyAuthorized,
        )?;
        store.append(PlannerStoreRecordKindV1::Dispatch, dispatch_receipt)?;
        record.phase = ProductExecutionPhaseV1::Dispatched;
        Ok(record.clone())
    }

    pub fn record_terminal(
        &mut self,
        store: &mut PlannerStoreV1,
        receipt: &EffectTerminalReceiptV1,
    ) -> Result<ProductExecutionRecordV1, ProductExecutionErrorV1> {
        if receipt.operation_identity_digest.is_zero() || receipt.observed_outcome_digest.is_zero()
        {
            return Err(ProductExecutionErrorV1::EmptyDigest("terminal receipt"));
        }
        let record = self.require_phase_mut(
            receipt.operation_identity_digest,
            ProductExecutionPhaseV1::Dispatched,
        )?;
        let payload = encode_terminal(receipt);
        let append = store.append(PlannerStoreRecordKindV1::TerminalReceipt, &payload)?;
        record.phase = match receipt.disposition {
            EffectTerminalDispositionV1::Succeeded => ProductExecutionPhaseV1::Succeeded,
            EffectTerminalDispositionV1::Failed => ProductExecutionPhaseV1::Failed,
            EffectTerminalDispositionV1::Indeterminate => ProductExecutionPhaseV1::Indeterminate,
        };
        record.terminal_receipt_digest = Some(append.payload_digest);
        Ok(record.clone())
    }

    pub fn reconcile_indeterminate(
        &mut self,
        store: &mut PlannerStoreV1,
        receipt: &EffectTerminalReceiptV1,
    ) -> Result<ProductExecutionRecordV1, ProductExecutionErrorV1> {
        if receipt.disposition == EffectTerminalDispositionV1::Indeterminate {
            return Err(ProductExecutionErrorV1::TerminalBindingMismatch);
        }
        let record = self.require_phase_mut(
            receipt.operation_identity_digest,
            ProductExecutionPhaseV1::Indeterminate,
        )?;
        let payload = encode_terminal(receipt);
        let append = store.append(PlannerStoreRecordKindV1::Reconciliation, &payload)?;
        record.phase = ProductExecutionPhaseV1::Reconciled;
        record.terminal_receipt_digest = Some(append.payload_digest);
        Ok(record.clone())
    }

    fn require_phase_mut(
        &mut self,
        operation_identity_digest: Digest32,
        expected: ProductExecutionPhaseV1,
    ) -> Result<&mut ProductExecutionRecordV1, ProductExecutionErrorV1> {
        let record = self
            .operations
            .get_mut(&operation_identity_digest)
            .ok_or(ProductExecutionErrorV1::UnknownOperation)?;
        if record.phase != expected {
            return Err(ProductExecutionErrorV1::InvalidPhase);
        }
        Ok(record)
    }
}

pub fn validate_current_authorization(
    request: &GrantRequestV1,
    current: &CurrentExecutionFenceV1,
    grant: &IndependentAuthorizationV1,
) -> Result<(), ProductExecutionErrorV1> {
    if grant.signed_grant_digest.is_zero() {
        return Err(ProductExecutionErrorV1::EmptyDigest("signed grant"));
    }
    if current.snapshot_digest != request.snapshot_digest {
        return Err(ProductExecutionErrorV1::SnapshotDrift);
    }
    if current.revocation_frontier_digest != request.revocation_frontier_digest {
        return Err(ProductExecutionErrorV1::RevocationDrift);
    }
    if current.final_payload_digest != request.final_payload_digest {
        return Err(ProductExecutionErrorV1::FinalPayloadDrift);
    }
    if current.now_micros >= request.expires_at_micros {
        return Err(ProductExecutionErrorV1::GrantExpired);
    }
    if grant.operation_id != request.operation_id
        || grant.candidate_id != request.candidate_id
        || grant.plan_digest != request.plan_digest
        || grant.final_payload_digest != request.final_payload_digest
        || grant.snapshot_digest != request.snapshot_digest
        || grant.revocation_frontier_digest != request.revocation_frontier_digest
        || grant.expires_at_micros != request.expires_at_micros
    {
        return Err(ProductExecutionErrorV1::AuthorizationBindingMismatch);
    }
    Ok(())
}

fn encode_grant_request(request: &GrantRequestV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.authority-request.v1\0".to_vec();
    bytes.extend_from_slice(request.operation_id.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(request.candidate_id.as_str().as_bytes());
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.final_payload_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    bytes.extend_from_slice(request.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    bytes
}

fn encode_terminal(receipt: &EffectTerminalReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.effect-terminal.v1\0".to_vec();
    bytes.extend_from_slice(receipt.operation_identity_digest.as_array());
    bytes.extend_from_slice(receipt.observed_outcome_digest.as_array());
    bytes.push(match receipt.disposition {
        EffectTerminalDispositionV1::Succeeded => 0,
        EffectTerminalDispositionV1::Failed => 1,
        EffectTerminalDispositionV1::Indeterminate => 2,
    });
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;

    fn envelope() -> CanonicalDecisionEnvelopeV1 {
        CanonicalDecisionEnvelopeV1 {
            operation_identity_digest: Digest32::of_bytes(b"operation-identity"),
            snapshot_bytes: b"snapshot".to_vec(),
            prepared_plan_bytes: b"prepared".to_vec(),
            ndu_evaluation_bytes: b"ndu".to_vec(),
            plan_receipt_bytes: b"receipt".to_vec(),
            grant_request_set_bytes: b"requests".to_vec(),
        }
    }

    fn request() -> GrantRequestV1 {
        GrantRequestV1 {
            operation_id: StableId::new("execute").expect("operation"),
            candidate_id: StableId::new("candidate").expect("candidate"),
            plan_digest: Digest32::of_bytes(b"plan"),
            final_payload_digest: Digest32::of_bytes(b"payload"),
            objective_digest: Digest32::of_bytes(b"objective"),
            snapshot_digest: Digest32::of_bytes(b"snapshot"),
            revocation_frontier_digest: Digest32::of_bytes(b"frontier"),
            expires_at_micros: 100,
        }
    }

    fn grant(request: &GrantRequestV1) -> IndependentAuthorizationV1 {
        IndependentAuthorizationV1 {
            authority_principal: StableId::new("kernel-authority").expect("principal"),
            signed_grant_digest: Digest32::of_bytes(b"signed-grant"),
            operation_id: request.operation_id.clone(),
            candidate_id: request.candidate_id.clone(),
            plan_digest: request.plan_digest,
            final_payload_digest: request.final_payload_digest,
            snapshot_digest: request.snapshot_digest,
            revocation_frontier_digest: request.revocation_frontier_digest,
            expires_at_micros: request.expires_at_micros,
        }
    }

    #[test]
    fn decision_authorization_dispatch_terminal_and_reconciliation_are_durable() {
        let directory = tempfile::tempdir().expect("tempdir");
        let mut store =
            PlannerStoreV1::open(directory.path().join("planner.store")).expect("store");
        let mut consumer = ControlRuntimeExecutionConsumerV1::new();
        let envelope = envelope();
        let identity = envelope.operation_identity_digest;
        consumer
            .commit_decision(&mut store, &envelope)
            .expect("decision");
        let request = request();
        consumer
            .record_authority_request(&mut store, identity, &request)
            .expect("request");
        let fence = CurrentExecutionFenceV1 {
            snapshot_digest: request.snapshot_digest,
            revocation_frontier_digest: request.revocation_frontier_digest,
            final_payload_digest: request.final_payload_digest,
            now_micros: 10,
        };
        consumer
            .consume_independent_authorization(
                &mut store,
                identity,
                &request,
                &fence,
                &grant(&request),
            )
            .expect("authorization");
        consumer
            .mark_dispatched(&mut store, identity, b"executor-dispatch-receipt")
            .expect("dispatch");
        consumer
            .record_terminal(
                &mut store,
                &EffectTerminalReceiptV1 {
                    operation_identity_digest: identity,
                    observed_outcome_digest: Digest32::of_bytes(b"unknown-outcome"),
                    disposition: EffectTerminalDispositionV1::Indeterminate,
                },
            )
            .expect("indeterminate");
        let final_record = consumer
            .reconcile_indeterminate(
                &mut store,
                &EffectTerminalReceiptV1 {
                    operation_identity_digest: identity,
                    observed_outcome_digest: Digest32::of_bytes(b"observed-success"),
                    disposition: EffectTerminalDispositionV1::Succeeded,
                },
            )
            .expect("reconcile");
        assert_eq!(final_record.phase, ProductExecutionPhaseV1::Reconciled);
        assert_eq!(store.records().len(), 6);
    }

    #[test]
    fn revocation_and_final_payload_drift_fail_before_authorization() {
        let request = request();
        let authorization = grant(&request);
        let mut fence = CurrentExecutionFenceV1 {
            snapshot_digest: request.snapshot_digest,
            revocation_frontier_digest: Digest32::of_bytes(b"changed-frontier"),
            final_payload_digest: request.final_payload_digest,
            now_micros: 10,
        };
        assert_eq!(
            validate_current_authorization(&request, &fence, &authorization),
            Err(ProductExecutionErrorV1::RevocationDrift)
        );
        fence.revocation_frontier_digest = request.revocation_frontier_digest;
        fence.final_payload_digest = Digest32::of_bytes(b"changed-payload");
        assert_eq!(
            validate_current_authorization(&request, &fence, &authorization),
            Err(ProductExecutionErrorV1::FinalPayloadDrift)
        );
    }
}
