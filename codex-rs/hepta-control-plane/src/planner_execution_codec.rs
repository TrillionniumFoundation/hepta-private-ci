//! Canonical dispatch-claim and terminal-receipt codecs.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::PlannerEffectDispositionV1;
use super::PlannerExecutionError;
use super::PlannerExecutionGrantV1;
use super::PlannerTerminalReceiptV1;
use crate::GrantRequestV1;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreRecordV1;

const DISPATCH_CLAIM_IDENTITY_DOMAIN: &[u8] =
    b"hepta.control.execution-dispatch-claim-identity.v1";
const DISPATCH_CLAIM_BINDING_DOMAIN_V1: &[u8] =
    b"hepta.control.execution-dispatch-claim.v1";
const DISPATCH_CLAIM_BINDING_DOMAIN_V2: &[u8] =
    b"hepta.control.execution-dispatch-claim.v2";
pub(super) const DISPATCH_CLAIM_ENVELOPE_DOMAIN_V1: &[u8] =
    b"hepta.control.execution-dispatch-claim-envelope.v1";
const DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2: &[u8] =
    b"hepta.control.execution-dispatch-claim-envelope.v2";
const TERMINAL_ENVELOPE_DOMAIN_V1: &[u8] =
    b"hepta.control.execution-terminal-envelope.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct DecodedDispatchClaimV1 {
    pub(super) operation_identity_digest: Digest32,
    pub(super) request_digest: Digest32,
    pub(super) grant_digest: Digest32,
    pub(super) final_payload_digest: Digest32,
}

pub(super) fn decode_dispatch_claim(
    record: &PlannerStoreRecordV1,
) -> Result<DecodedDispatchClaimV1, PlannerExecutionError> {
    let (domain, version) = if record
        .envelope
        .starts_with(DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2)
    {
        (DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2, 2_u8)
    } else if record
        .envelope
        .starts_with(DISPATCH_CLAIM_ENVELOPE_DOMAIN_V1)
    {
        (DISPATCH_CLAIM_ENVELOPE_DOMAIN_V1, 1_u8)
    } else {
        return Err(store_error("unknown dispatch claim envelope"));
    };
    let expected_length = domain
        .len()
        .checked_add(32 * 5 + 8)
        .ok_or_else(|| store_error("dispatch claim envelope length overflow"))?;
    if record.envelope.len() != expected_length {
        return Err(store_error("truncated dispatch claim envelope"));
    }

    let mut offset = domain.len();
    let operation_identity_digest = read_digest(&record.envelope, &mut offset)?;
    let request_digest = read_digest(&record.envelope, &mut offset)?;
    let grant_digest = read_digest(&record.envelope, &mut offset)?;
    let final_payload_digest = read_digest(&record.envelope, &mut offset)?;
    let claimed_at_micros = read_u64(&record.envelope, &mut offset)?;
    let encoded_claim_digest = read_digest(&record.envelope, &mut offset)?;
    let expected_claim_digest = if version == 1 {
        dispatch_claim_digest_v1(
            operation_identity_digest,
            request_digest,
            grant_digest,
            final_payload_digest,
            claimed_at_micros,
        )
    } else {
        dispatch_claim_digest_v2(
            operation_identity_digest,
            request_digest,
            grant_digest,
            final_payload_digest,
        )
    };
    if encoded_claim_digest != expected_claim_digest
        || record.payload_digest != expected_claim_digest
        || record.operation_identity_digest
            != dispatch_claim_identity(operation_identity_digest)
    {
        return Err(store_error("dispatch claim envelope digest mismatch"));
    }
    require_digest(operation_identity_digest, "stored dispatch operation")?;
    require_digest(request_digest, "stored dispatch request")?;
    require_digest(grant_digest, "stored dispatch grant")?;
    require_digest(final_payload_digest, "stored dispatch payload")?;
    Ok(DecodedDispatchClaimV1 {
        operation_identity_digest,
        request_digest,
        grant_digest,
        final_payload_digest,
    })
}

pub(super) fn decode_terminal_receipt(
    record: &PlannerStoreRecordV1,
) -> Result<PlannerTerminalReceiptV1, PlannerExecutionError> {
    let expected_length = TERMINAL_ENVELOPE_DOMAIN_V1
        .len()
        .checked_add(32 * 6 + 1 + 8)
        .ok_or_else(|| store_error("terminal receipt envelope length overflow"))?;
    if record.envelope.len() != expected_length
        || !record.envelope.starts_with(TERMINAL_ENVELOPE_DOMAIN_V1)
    {
        return Err(store_error("invalid terminal receipt envelope"));
    }

    let mut offset = TERMINAL_ENVELOPE_DOMAIN_V1.len();
    let operation_identity_digest = read_digest(&record.envelope, &mut offset)?;
    let request_digest = read_digest(&record.envelope, &mut offset)?;
    let grant_digest = read_digest(&record.envelope, &mut offset)?;
    let final_payload_digest = read_digest(&record.envelope, &mut offset)?;
    let disposition = match read_u8(&record.envelope, &mut offset)? {
        0 => PlannerEffectDispositionV1::Succeeded,
        1 => PlannerEffectDispositionV1::Failed,
        2 => PlannerEffectDispositionV1::Indeterminate,
        _ => return Err(store_error("unknown terminal receipt disposition")),
    };
    let outcome_digest = read_digest(&record.envelope, &mut offset)?;
    let observed_at_micros = read_u64(&record.envelope, &mut offset)?;
    let receipt_digest = read_digest(&record.envelope, &mut offset)?;
    let expected_receipt_digest = digest_terminal_receipt(
        operation_identity_digest,
        request_digest,
        grant_digest,
        final_payload_digest,
        disposition,
        outcome_digest,
        observed_at_micros,
    );
    let expected_record_identity = match record.kind {
        PlannerStoreRecordKindV1::TerminalReceipt => operation_identity_digest,
        PlannerStoreRecordKindV1::Reconciliation => {
            reconciliation_identity(operation_identity_digest, receipt_digest)
        }
        _ => return Err(store_error("unexpected execution receipt record kind")),
    };
    if receipt_digest != expected_receipt_digest
        || record.payload_digest != expected_receipt_digest
        || record.operation_identity_digest != expected_record_identity
    {
        return Err(store_error("terminal receipt envelope digest mismatch"));
    }
    require_digest(operation_identity_digest, "stored terminal operation")?;
    require_digest(request_digest, "stored terminal request")?;
    require_digest(grant_digest, "stored terminal grant")?;
    require_digest(final_payload_digest, "stored terminal payload")?;
    require_digest(outcome_digest, "stored terminal outcome")?;
    Ok(PlannerTerminalReceiptV1 {
        operation_identity_digest,
        request_digest,
        grant_digest,
        final_payload_digest,
        disposition,
        outcome_digest,
        observed_at_micros,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub(super) fn validate_existing_operation(
    stored_operation_identity_digest: Digest32,
    stored_request_digest: Digest32,
    stored_final_payload_digest: Digest32,
    operation_identity_digest: Digest32,
    request_digest: Digest32,
    final_payload_digest: Digest32,
) -> Result<(), PlannerExecutionError> {
    if stored_operation_identity_digest != operation_identity_digest
        || stored_request_digest != request_digest
        || stored_final_payload_digest != final_payload_digest
    {
        return Err(store_error("dispatch operation identity conflict"));
    }
    Ok(())
}

pub(super) fn validate_request_identity(
    request: &GrantRequestV1,
) -> Result<(), PlannerExecutionError> {
    require_digest(request.plan_digest, "request plan")?;
    require_digest(request.final_payload_digest, "request final payload")?;
    require_digest(request.objective_digest, "request objective")?;
    require_digest(request.snapshot_digest, "request snapshot")?;
    require_digest(
        request.revocation_frontier_digest,
        "request revocation frontier",
    )?;
    Ok(())
}

pub(super) fn validate_request_expiry(
    request: &GrantRequestV1,
    now_micros: u64,
) -> Result<(), PlannerExecutionError> {
    if now_micros >= request.expires_at_micros {
        return Err(PlannerExecutionError::ExpiredRequest);
    }
    Ok(())
}

pub(super) fn validate_grant(
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

pub(super) fn operation_identity_digest(request: &GrantRequestV1) -> Digest32 {
    let mut bytes = b"hepta.control.execution-operation.v1".to_vec();
    push_id(&mut bytes, request.operation_id.as_str());
    push_id(&mut bytes, request.candidate_id.as_str());
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.final_payload_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn request_digest(request: &GrantRequestV1) -> Digest32 {
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

pub(super) fn dispatch_claim_identity(operation_identity_digest: Digest32) -> Digest32 {
    let mut bytes = DISPATCH_CLAIM_IDENTITY_DOMAIN.to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn dispatch_claim_digest_v1(
    operation_identity_digest: Digest32,
    request_digest: Digest32,
    grant_digest: Digest32,
    final_payload_digest: Digest32,
    claimed_at_micros: u64,
) -> Digest32 {
    let mut bytes = DISPATCH_CLAIM_BINDING_DOMAIN_V1.to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(grant_digest.as_array());
    bytes.extend_from_slice(final_payload_digest.as_array());
    bytes.extend_from_slice(&claimed_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub(super) fn dispatch_claim_digest_v2(
    operation_identity_digest: Digest32,
    request_digest: Digest32,
    grant_digest: Digest32,
    final_payload_digest: Digest32,
) -> Digest32 {
    let mut bytes = DISPATCH_CLAIM_BINDING_DOMAIN_V2.to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(grant_digest.as_array());
    bytes.extend_from_slice(final_payload_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn encode_dispatch_claim_v2(
    operation_identity_digest: Digest32,
    request_digest: Digest32,
    grant_digest: Digest32,
    final_payload_digest: Digest32,
    claimed_at_micros: u64,
    claim_digest: Digest32,
) -> Vec<u8> {
    let mut bytes = DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2.to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(grant_digest.as_array());
    bytes.extend_from_slice(final_payload_digest.as_array());
    bytes.extend_from_slice(&claimed_at_micros.to_be_bytes());
    bytes.extend_from_slice(claim_digest.as_array());
    bytes
}

fn reconciliation_identity(
    operation_identity_digest: Digest32,
    receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.control.reconciliation-identity.v1".to_vec();
    bytes.extend_from_slice(operation_identity_digest.as_array());
    bytes.extend_from_slice(receipt_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_terminal_receipt(
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

fn read_u8(bytes: &[u8], offset: &mut usize) -> Result<u8, PlannerExecutionError> {
    let value = bytes
        .get(*offset)
        .copied()
        .ok_or_else(|| store_error("truncated execution envelope"))?;
    *offset = (*offset)
        .checked_add(1)
        .ok_or_else(|| store_error("execution envelope offset overflow"))?;
    Ok(value)
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, PlannerExecutionError> {
    let end = (*offset)
        .checked_add(8)
        .ok_or_else(|| store_error("execution envelope offset overflow"))?;
    let value: [u8; 8] = bytes
        .get(*offset..end)
        .ok_or_else(|| store_error("truncated execution envelope"))?
        .try_into()
        .map_err(|_| store_error("truncated execution envelope"))?;
    *offset = end;
    Ok(u64::from_be_bytes(value))
}

fn read_digest(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<Digest32, PlannerExecutionError> {
    let end = (*offset)
        .checked_add(32)
        .ok_or_else(|| store_error("execution envelope offset overflow"))?;
    let value: [u8; 32] = bytes
        .get(*offset..end)
        .ok_or_else(|| store_error("truncated execution envelope"))?
        .try_into()
        .map_err(|_| store_error("truncated execution envelope"))?;
    *offset = end;
    Ok(Digest32::from_array(value))
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u64::try_from(value.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

pub(super) fn require_digest(
    value: Digest32,
    field: &'static str,
) -> Result<(), PlannerExecutionError> {
    if value.is_zero() {
        return Err(PlannerExecutionError::EmptyDigest(field));
    }
    Ok(())
}

pub(super) fn store_error(message: &str) -> PlannerExecutionError {
    PlannerExecutionError::Store(message.to_string())
}
