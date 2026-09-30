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

const DECISION_ENVELOPE_PREFIX: &[u8] = b"hepta.control.decision-envelope.v1\0";
const AUTHORITY_REQUEST_PREFIX: &[u8] = b"hepta.control.authority-request.v2\0";
const AUTHORIZATION_PREFIX: &[u8] = b"hepta.control.independent-authorization.v2\0";
const DISPATCH_PREFIX: &[u8] = b"hepta.control.effect-dispatch.v2\0";
const TERMINAL_PREFIX: &[u8] = b"hepta.control.effect-terminal.v2\0";
const MAX_ID_BYTES: usize = 1024;
const MAX_RECEIPT_BYTES: usize = 1024 * 1024;

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
    CorruptDurableRecord,
    UnsupportedDurableRecord,
    DurableLengthOverflow,
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
    requests: BTreeMap<Digest32, GrantRequestV1>,
    authorizations: BTreeMap<Digest32, IndependentAuthorizationV1>,
}

impl ControlRuntimeExecutionConsumerV1 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn recover_from_store(
        store: &PlannerStoreV1,
    ) -> Result<Self, ProductExecutionErrorV1> {
        let mut consumer = Self::new();
        for durable in store.records() {
            match durable.kind {
                PlannerStoreRecordKindV1::DecisionEnvelope => {
                    let identity = decode_decision_identity(&durable.payload)?;
                    if consumer.operations.contains_key(&identity) {
                        return Err(ProductExecutionErrorV1::DuplicateOperation);
                    }
                    consumer.operations.insert(
                        identity,
                        ProductExecutionRecordV1 {
                            operation_identity_digest: identity,
                            phase: ProductExecutionPhaseV1::DecisionDurable,
                            decision_envelope_digest: durable.payload_digest,
                            authority_request_digest: None,
                            signed_grant_digest: None,
                            terminal_receipt_digest: None,
                        },
                    );
                }
                PlannerStoreRecordKindV1::AuthorityRequest => {
                    let (identity, request) = decode_grant_request(&durable.payload)?;
                    let record = consumer.require_phase_mut(
                        identity,
                        ProductExecutionPhaseV1::DecisionDurable,
                    )?;
                    record.phase = ProductExecutionPhaseV1::AuthorityRequested;
                    record.authority_request_digest = Some(durable.payload_digest);
                    if consumer.requests.insert(identity, request).is_some() {
                        return Err(ProductExecutionErrorV1::CorruptDurableRecord);
                    }
                }
                PlannerStoreRecordKindV1::IndependentAuthorization => {
                    let (identity, grant) = decode_authorization(&durable.payload)?;
                    let request = consumer
                        .requests
                        .get(&identity)
                        .ok_or(ProductExecutionErrorV1::CorruptDurableRecord)?;
                    validate_authorization_binding(request, &grant)?;
                    let record = consumer.require_phase_mut(
                        identity,
                        ProductExecutionPhaseV1::AuthorityRequested,
                    )?;
                    record.phase = ProductExecutionPhaseV1::IndependentlyAuthorized;
                    record.signed_grant_digest = Some(grant.signed_grant_digest);
                    if consumer.authorizations.insert(identity, grant).is_some() {
                        return Err(ProductExecutionErrorV1::CorruptDurableRecord);
                    }
                }
                PlannerStoreRecordKindV1::Dispatch => {
                    let identity = decode_dispatch(&durable.payload)?;
                    let record = consumer.require_phase_mut(
                        identity,
                        ProductExecutionPhaseV1::IndependentlyAuthorized,
                    )?;
                    record.phase = ProductExecutionPhaseV1::Dispatched;
                }
                PlannerStoreRecordKindV1::TerminalReceipt => {
                    let receipt = decode_terminal(&durable.payload)?;
                    let record = consumer.require_phase_mut(
                        receipt.operation_identity_digest,
                        ProductExecutionPhaseV1::Dispatched,
                    )?;
                    record.phase = phase_for_terminal(receipt.disposition);
                    record.terminal_receipt_digest = Some(durable.payload_digest);
                }
                PlannerStoreRecordKindV1::Reconciliation => {
                    let receipt = decode_terminal(&durable.payload)?;
                    if receipt.disposition == EffectTerminalDispositionV1::Indeterminate {
                        return Err(ProductExecutionErrorV1::TerminalBindingMismatch);
                    }
                    let record = consumer.require_phase_mut(
                        receipt.operation_identity_digest,
                        ProductExecutionPhaseV1::Indeterminate,
                    )?;
                    record.phase = ProductExecutionPhaseV1::Reconciled;
                    record.terminal_receipt_digest = Some(durable.payload_digest);
                }
                PlannerStoreRecordKindV1::Checkpoint => {}
                PlannerStoreRecordKindV1::MigratedLegacyRecord => {
                    return Err(ProductExecutionErrorV1::UnsupportedDurableRecord);
                }
            }
        }
        Ok(consumer)
    }

    pub fn operation(
        &self,
        operation_identity_digest: Digest32,
    ) -> Option<&ProductExecutionRecordV1> {
        self.operations.get(&operation_identity_digest)
    }

    pub(crate) fn requests(&self) -> &BTreeMap<Digest32, GrantRequestV1> {
        &self.requests
    }

    pub(crate) fn authorizations(
        &self,
    ) -> &BTreeMap<Digest32, IndependentAuthorizationV1> {
        &self.authorizations
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
        self.require_phase(
            operation_identity_digest,
            ProductExecutionPhaseV1::DecisionDurable,
        )?;
        let payload = encode_grant_request(operation_identity_digest, request)?;
        let receipt = store.append(PlannerStoreRecordKindV1::AuthorityRequest, &payload)?;
        let output = {
            let record = self.require_phase_mut(
                operation_identity_digest,
                ProductExecutionPhaseV1::DecisionDurable,
            )?;
            record.phase = ProductExecutionPhaseV1::AuthorityRequested;
            record.authority_request_digest = Some(receipt.payload_digest);
            record.clone()
        };
        self.requests
            .insert(operation_identity_digest, request.clone());
        Ok(output)
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
        let persisted_request = self
            .requests
            .get(&operation_identity_digest)
            .ok_or(ProductExecutionErrorV1::UnknownOperation)?;
        if persisted_request != request {
            return Err(ProductExecutionErrorV1::AuthorizationBindingMismatch);
        }
        self.require_phase(
            operation_identity_digest,
            ProductExecutionPhaseV1::AuthorityRequested,
        )?;
        let payload = encode_authorization(operation_identity_digest, grant)?;
        let receipt = store.append(
            PlannerStoreRecordKindV1::IndependentAuthorization,
            &payload,
        )?;
        let output = {
            let record = self.require_phase_mut(
                operation_identity_digest,
                ProductExecutionPhaseV1::AuthorityRequested,
            )?;
            record.phase = ProductExecutionPhaseV1::IndependentlyAuthorized;
            record.signed_grant_digest = Some(grant.signed_grant_digest);
            record.clone()
        };
        debug_assert_eq!(receipt.kind, PlannerStoreRecordKindV1::IndependentAuthorization);
        self.authorizations
            .insert(operation_identity_digest, grant.clone());
        Ok(output)
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
        self.require_phase(
            operation_identity_digest,
            ProductExecutionPhaseV1::IndependentlyAuthorized,
        )?;
        let payload = encode_dispatch(operation_identity_digest, dispatch_receipt)?;
        store.append(PlannerStoreRecordKindV1::Dispatch, &payload)?;
        let record = self.require_phase_mut(
            operation_identity_digest,
            ProductExecutionPhaseV1::IndependentlyAuthorized,
        )?;
        record.phase = ProductExecutionPhaseV1::Dispatched;
        Ok(record.clone())
    }

    pub fn record_terminal(
        &mut self,
        store: &mut PlannerStoreV1,
        receipt: &EffectTerminalReceiptV1,
    ) -> Result<ProductExecutionRecordV1, ProductExecutionErrorV1> {
        validate_terminal(receipt)?;
        self.require_phase(
            receipt.operation_identity_digest,
            ProductExecutionPhaseV1::Dispatched,
        )?;
        let payload = encode_terminal(receipt);
        let append = store.append(PlannerStoreRecordKindV1::TerminalReceipt, &payload)?;
        let record = self.require_phase_mut(
            receipt.operation_identity_digest,
            ProductExecutionPhaseV1::Dispatched,
        )?;
        record.phase = phase_for_terminal(receipt.disposition);
        record.terminal_receipt_digest = Some(append.payload_digest);
        Ok(record.clone())
    }

    pub fn reconcile_indeterminate(
        &mut self,
        store: &mut PlannerStoreV1,
        receipt: &EffectTerminalReceiptV1,
    ) -> Result<ProductExecutionRecordV1, ProductExecutionErrorV1> {
        validate_terminal(receipt)?;
        if receipt.disposition == EffectTerminalDispositionV1::Indeterminate {
            return Err(ProductExecutionErrorV1::TerminalBindingMismatch);
        }
        self.require_phase(
            receipt.operation_identity_digest,
            ProductExecutionPhaseV1::Indeterminate,
        )?;
        let payload = encode_terminal(receipt);
        let append = store.append(PlannerStoreRecordKindV1::Reconciliation, &payload)?;
        let record = self.require_phase_mut(
            receipt.operation_identity_digest,
            ProductExecutionPhaseV1::Indeterminate,
        )?;
        record.phase = ProductExecutionPhaseV1::Reconciled;
        record.terminal_receipt_digest = Some(append.payload_digest);
        Ok(record.clone())
    }

    fn require_phase(
        &self,
        operation_identity_digest: Digest32,
        expected: ProductExecutionPhaseV1,
    ) -> Result<(), ProductExecutionErrorV1> {
        let record = self
            .operations
            .get(&operation_identity_digest)
            .ok_or(ProductExecutionErrorV1::UnknownOperation)?;
        if record.phase != expected {
            return Err(ProductExecutionErrorV1::InvalidPhase);
        }
        Ok(())
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
    validate_authorization_binding(request, grant)?;
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
    Ok(())
}

fn validate_authorization_binding(
    request: &GrantRequestV1,
    grant: &IndependentAuthorizationV1,
) -> Result<(), ProductExecutionErrorV1> {
    if grant.signed_grant_digest.is_zero() {
        return Err(ProductExecutionErrorV1::EmptyDigest("signed grant"));
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

fn validate_terminal(receipt: &EffectTerminalReceiptV1) -> Result<(), ProductExecutionErrorV1> {
    if receipt.operation_identity_digest.is_zero() || receipt.observed_outcome_digest.is_zero() {
        return Err(ProductExecutionErrorV1::EmptyDigest("terminal receipt"));
    }
    Ok(())
}

const fn phase_for_terminal(
    disposition: EffectTerminalDispositionV1,
) -> ProductExecutionPhaseV1 {
    match disposition {
        EffectTerminalDispositionV1::Succeeded => ProductExecutionPhaseV1::Succeeded,
        EffectTerminalDispositionV1::Failed => ProductExecutionPhaseV1::Failed,
        EffectTerminalDispositionV1::Indeterminate => ProductExecutionPhaseV1::Indeterminate,
    }
}

fn encode_grant_request(
    operation_identity_digest: Digest32,
    request: &GrantRequestV1,
) -> Result<Vec<u8>, ProductExecutionErrorV1> {
    if operation_identity_digest.is_zero() {
        return Err(ProductExecutionErrorV1::EmptyDigest("operation identity"));
    }
    let mut bytes = AUTHORITY_REQUEST_PREFIX.to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    push_id(&mut bytes, &request.operation_id)?;
    push_id(&mut bytes, &request.candidate_id)?;
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.final_payload_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    bytes.extend_from_slice(request.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    Ok(bytes)
}

fn encode_authorization(
    operation_identity_digest: Digest32,
    grant: &IndependentAuthorizationV1,
) -> Result<Vec<u8>, ProductExecutionErrorV1> {
    if operation_identity_digest.is_zero() || grant.signed_grant_digest.is_zero() {
        return Err(ProductExecutionErrorV1::EmptyDigest("authorization"));
    }
    let mut bytes = AUTHORIZATION_PREFIX.to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    push_id(&mut bytes, &grant.authority_principal)?;
    bytes.extend_from_slice(grant.signed_grant_digest.as_array());
    push_id(&mut bytes, &grant.operation_id)?;
    push_id(&mut bytes, &grant.candidate_id)?;
    bytes.extend_from_slice(grant.plan_digest.as_array());
    bytes.extend_from_slice(grant.final_payload_digest.as_array());
    bytes.extend_from_slice(grant.snapshot_digest.as_array());
    bytes.extend_from_slice(grant.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(&grant.expires_at_micros.to_be_bytes());
    Ok(bytes)
}

fn encode_dispatch(
    operation_identity_digest: Digest32,
    receipt: &[u8],
) -> Result<Vec<u8>, ProductExecutionErrorV1> {
    if operation_identity_digest.is_zero() || receipt.is_empty() {
        return Err(ProductExecutionErrorV1::EmptyDigest("dispatch receipt"));
    }
    if receipt.len() > MAX_RECEIPT_BYTES {
        return Err(ProductExecutionErrorV1::DurableLengthOverflow);
    }
    let mut bytes = DISPATCH_PREFIX.to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    push_bytes(&mut bytes, receipt)?;
    Ok(bytes)
}

fn encode_terminal(receipt: &EffectTerminalReceiptV1) -> Vec<u8> {
    let mut bytes = TERMINAL_PREFIX.to_vec();
    bytes.extend_from_slice(receipt.operation_identity_digest.as_array());
    bytes.extend_from_slice(receipt.observed_outcome_digest.as_array());
    bytes.push(match receipt.disposition {
        EffectTerminalDispositionV1::Succeeded => 0,
        EffectTerminalDispositionV1::Failed => 1,
        EffectTerminalDispositionV1::Indeterminate => 2,
    });
    bytes
}

fn decode_decision_identity(payload: &[u8]) -> Result<Digest32, ProductExecutionErrorV1> {
    let mut cursor = Cursor::new(payload, DECISION_ENVELOPE_PREFIX)?;
    let identity = cursor.read_digest()?;
    if identity.is_zero() {
        return Err(ProductExecutionErrorV1::CorruptDurableRecord);
    }
    for _ in 0..5 {
        let section = cursor.read_bytes()?;
        if section.is_empty() {
            return Err(ProductExecutionErrorV1::CorruptDurableRecord);
        }
    }
    cursor.finish()?;
    Ok(identity)
}

fn decode_grant_request(
    payload: &[u8],
) -> Result<(Digest32, GrantRequestV1), ProductExecutionErrorV1> {
    let mut cursor = Cursor::new(payload, AUTHORITY_REQUEST_PREFIX)?;
    let identity = cursor.read_digest()?;
    let request = GrantRequestV1 {
        operation_id: cursor.read_id()?,
        candidate_id: cursor.read_id()?,
        plan_digest: cursor.read_digest()?,
        final_payload_digest: cursor.read_digest()?,
        objective_digest: cursor.read_digest()?,
        snapshot_digest: cursor.read_digest()?,
        revocation_frontier_digest: cursor.read_digest()?,
        expires_at_micros: cursor.read_u64()?,
    };
    cursor.finish()?;
    if identity.is_zero()
        || request.plan_digest.is_zero()
        || request.final_payload_digest.is_zero()
        || request.objective_digest.is_zero()
        || request.snapshot_digest.is_zero()
        || request.revocation_frontier_digest.is_zero()
        || request.expires_at_micros == 0
    {
        return Err(ProductExecutionErrorV1::CorruptDurableRecord);
    }
    Ok((identity, request))
}

fn decode_authorization(
    payload: &[u8],
) -> Result<(Digest32, IndependentAuthorizationV1), ProductExecutionErrorV1> {
    let mut cursor = Cursor::new(payload, AUTHORIZATION_PREFIX)?;
    let identity = cursor.read_digest()?;
    let grant = IndependentAuthorizationV1 {
        authority_principal: cursor.read_id()?,
        signed_grant_digest: cursor.read_digest()?,
        operation_id: cursor.read_id()?,
        candidate_id: cursor.read_id()?,
        plan_digest: cursor.read_digest()?,
        final_payload_digest: cursor.read_digest()?,
        snapshot_digest: cursor.read_digest()?,
        revocation_frontier_digest: cursor.read_digest()?,
        expires_at_micros: cursor.read_u64()?,
    };
    cursor.finish()?;
    if identity.is_zero() || grant.signed_grant_digest.is_zero() || grant.expires_at_micros == 0 {
        return Err(ProductExecutionErrorV1::CorruptDurableRecord);
    }
    Ok((identity, grant))
}

fn decode_dispatch(payload: &[u8]) -> Result<Digest32, ProductExecutionErrorV1> {
    let mut cursor = Cursor::new(payload, DISPATCH_PREFIX)?;
    let identity = cursor.read_digest()?;
    let receipt = cursor.read_bytes()?;
    cursor.finish()?;
    if identity.is_zero() || receipt.is_empty() || receipt.len() > MAX_RECEIPT_BYTES {
        return Err(ProductExecutionErrorV1::CorruptDurableRecord);
    }
    Ok(identity)
}

fn decode_terminal(
    payload: &[u8],
) -> Result<EffectTerminalReceiptV1, ProductExecutionErrorV1> {
    let mut cursor = Cursor::new(payload, TERMINAL_PREFIX)?;
    let operation_identity_digest = cursor.read_digest()?;
    let observed_outcome_digest = cursor.read_digest()?;
    let disposition = match cursor.read_u8()? {
        0 => EffectTerminalDispositionV1::Succeeded,
        1 => EffectTerminalDispositionV1::Failed,
        2 => EffectTerminalDispositionV1::Indeterminate,
        _ => return Err(ProductExecutionErrorV1::CorruptDurableRecord),
    };
    cursor.finish()?;
    let receipt = EffectTerminalReceiptV1 {
        operation_identity_digest,
        observed_outcome_digest,
        disposition,
    };
    validate_terminal(&receipt)?;
    Ok(receipt)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ProductExecutionErrorV1> {
    let raw = value.as_str().as_bytes();
    if raw.is_empty() || raw.len() > MAX_ID_BYTES {
        return Err(ProductExecutionErrorV1::DurableLengthOverflow);
    }
    push_bytes(bytes, raw)
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), ProductExecutionErrorV1> {
    let length = u32::try_from(value.len())
        .map_err(|_| ProductExecutionErrorV1::DurableLengthOverflow)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Cursor<'a> {
    fn new(bytes: &'a [u8], prefix: &[u8]) -> Result<Self, ProductExecutionErrorV1> {
        if !bytes.starts_with(prefix) {
            return Err(ProductExecutionErrorV1::UnsupportedDurableRecord);
        }
        Ok(Self {
            bytes,
            offset: prefix.len(),
        })
    }

    fn read_u8(&mut self) -> Result<u8, ProductExecutionErrorV1> {
        let value = *self
            .bytes
            .get(self.offset)
            .ok_or(ProductExecutionErrorV1::CorruptDurableRecord)?;
        self.offset += 1;
        Ok(value)
    }

    fn read_u32(&mut self) -> Result<u32, ProductExecutionErrorV1> {
        let end = self
            .offset
            .checked_add(4)
            .ok_or(ProductExecutionErrorV1::DurableLengthOverflow)?;
        let value = u32::from_be_bytes(
            self.bytes
                .get(self.offset..end)
                .ok_or(ProductExecutionErrorV1::CorruptDurableRecord)?
                .try_into()
                .map_err(|_| ProductExecutionErrorV1::CorruptDurableRecord)?,
        );
        self.offset = end;
        Ok(value)
    }

    fn read_u64(&mut self) -> Result<u64, ProductExecutionErrorV1> {
        let end = self
            .offset
            .checked_add(8)
            .ok_or(ProductExecutionErrorV1::DurableLengthOverflow)?;
        let value = u64::from_be_bytes(
            self.bytes
                .get(self.offset..end)
                .ok_or(ProductExecutionErrorV1::CorruptDurableRecord)?
                .try_into()
                .map_err(|_| ProductExecutionErrorV1::CorruptDurableRecord)?,
        );
        self.offset = end;
        Ok(value)
    }

    fn read_digest(&mut self) -> Result<Digest32, ProductExecutionErrorV1> {
        let end = self
            .offset
            .checked_add(32)
            .ok_or(ProductExecutionErrorV1::DurableLengthOverflow)?;
        let value: [u8; 32] = self
            .bytes
            .get(self.offset..end)
            .ok_or(ProductExecutionErrorV1::CorruptDurableRecord)?
            .try_into()
            .map_err(|_| ProductExecutionErrorV1::CorruptDurableRecord)?;
        self.offset = end;
        Ok(Digest32::from_array(value))
    }

    fn read_bytes(&mut self) -> Result<&'a [u8], ProductExecutionErrorV1> {
        let length = usize::try_from(self.read_u32()?)
            .map_err(|_| ProductExecutionErrorV1::DurableLengthOverflow)?;
        let end = self
            .offset
            .checked_add(length)
            .ok_or(ProductExecutionErrorV1::DurableLengthOverflow)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(ProductExecutionErrorV1::CorruptDurableRecord)?;
        self.offset = end;
        Ok(value)
    }

    fn read_id(&mut self) -> Result<StableId, ProductExecutionErrorV1> {
        let raw = self.read_bytes()?;
        if raw.is_empty() || raw.len() > MAX_ID_BYTES {
            return Err(ProductExecutionErrorV1::CorruptDurableRecord);
        }
        let value = std::str::from_utf8(raw)
            .map_err(|_| ProductExecutionErrorV1::CorruptDurableRecord)?;
        StableId::new(value).map_err(|_| ProductExecutionErrorV1::CorruptDurableRecord)
    }

    fn finish(self) -> Result<(), ProductExecutionErrorV1> {
        if self.offset != self.bytes.len() {
            return Err(ProductExecutionErrorV1::CorruptDurableRecord);
        }
        Ok(())
    }
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
    fn decision_authorization_dispatch_terminal_and_reconciliation_survive_restart() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("planner.store");
        let identity = envelope().operation_identity_digest;
        {
            let mut store = PlannerStoreV1::open(&path).expect("store");
            let mut consumer = ControlRuntimeExecutionConsumerV1::new();
            let envelope = envelope();
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
            consumer
                .reconcile_indeterminate(
                    &mut store,
                    &EffectTerminalReceiptV1 {
                        operation_identity_digest: identity,
                        observed_outcome_digest: Digest32::of_bytes(b"observed-success"),
                        disposition: EffectTerminalDispositionV1::Succeeded,
                    },
                )
                .expect("reconcile");
            assert_eq!(store.records().len(), 6);
        }

        let store = PlannerStoreV1::open(&path).expect("reopen store");
        let recovered =
            ControlRuntimeExecutionConsumerV1::recover_from_store(&store).expect("recover");
        assert_eq!(
            recovered.operation(identity).expect("operation").phase,
            ProductExecutionPhaseV1::Reconciled
        );
        assert_eq!(recovered.requests().get(&identity), Some(&request()));
        assert_eq!(
            recovered.authorizations().get(&identity),
            Some(&grant(&request()))
        );
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

    #[test]
    fn recovery_rejects_a_semantically_out_of_order_store() {
        let directory = tempfile::tempdir().expect("tempdir");
        let mut store =
            PlannerStoreV1::open(directory.path().join("planner.store")).expect("store");
        let payload = encode_dispatch(Digest32::of_bytes(b"unknown"), b"dispatch")
            .expect("dispatch payload");
        store
            .append(PlannerStoreRecordKindV1::Dispatch, &payload)
            .expect("append malformed ordering");
        assert!(matches!(
            ControlRuntimeExecutionConsumerV1::recover_from_store(&store),
            Err(ProductExecutionErrorV1::UnknownOperation)
        ));
    }
}
