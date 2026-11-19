//! Data-only control adapter for the original producer and fixed Observer.
//! All append, trust, independence and once-only checks stay in that producer.

use codex_hepta_agent_protocol::MAX_Q24_OUTCOME_PREIMAGE_BYTES;
use codex_hepta_agent_protocol::Q24OriginalObserverEvidenceV1;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeReceiptV1;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeRequestV1;

use super::*;
use crate::AgentdError;

impl OriginalCellQ24TaskLedgerProducerV1 {
    pub(crate) fn require_original_control_identity(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        if &self.identity != identity {
            return Err(invalid("original producer belongs to another daemon"));
        }
        Ok(())
    }

    pub(crate) fn submit_original_control_outcome(
        &self,
        request: &Q24OriginalTerminalOutcomeRequestV1,
    ) -> Result<Q24OriginalTerminalOutcomeReceiptV1, AgentdError> {
        let (outcome, signed) = decode(request)?;
        match self
            .submit_original_terminal_outcome(outcome, &signed)
            .map_err(invalid)?
        {
            OriginalCellQ24TaskLedgerStatusV1::Complete { decision, outcome } => {
                Ok(Q24OriginalTerminalOutcomeReceiptV1 {
                    decision_sequence: decision.sequence.get(),
                    decision_chain_digest: decision.chain_digest.to_string(),
                    outcome_sequence: outcome.sequence.get(),
                    outcome_chain_digest: outcome.chain_digest.to_string(),
                })
            }
            OriginalCellQ24TaskLedgerStatusV1::AwaitingOutcome { .. } => {
                Err(invalid("original terminal Outcome remains unavailable"))
            }
        }
    }
}

pub(crate) fn encode(
    outcome: &AuthenticatedOutcomeV1,
    signed: &SignedLearningEvidenceV1,
) -> Result<Q24OriginalTerminalOutcomeRequestV1, AgentdError> {
    let payload = outcome_signing_payload_v2(outcome);
    let request = Q24OriginalTerminalOutcomeRequestV1 {
        outcome_preimage_hex: hex(&payload),
        evidence: Q24OriginalObserverEvidenceV1 {
            evidence_id: signed.evidence_id.as_str().into(),
            principal_id: signed.principal_id.as_str().into(),
            role: "observer".into(),
            trust_digest: signed.trust_digest.to_string(),
            scope_digest: signed.scope_digest.to_string(),
            objective_digest: signed.objective_digest.to_string(),
            authority_epoch: signed.authority_epoch,
            issued_at: signed.issued_at,
            expires_at: signed.expires_at,
            payload_digest: signed.payload_digest.to_string(),
            signature_hex: hex(&signed.signature),
        },
    };
    if signed.role != LearningEvidenceRoleV1::Observer
        || decode(&request)? != (outcome.clone(), signed.clone())
    {
        return Err(invalid("unchanged canonical Observer attestation required"));
    }
    Ok(request)
}

fn decode(
    request: &Q24OriginalTerminalOutcomeRequestV1,
) -> Result<(AuthenticatedOutcomeV1, SignedLearningEvidenceV1), AgentdError> {
    let payload = unhex(
        &request.outcome_preimage_hex,
        MAX_Q24_OUTCOME_PREIMAGE_BYTES,
    )?;
    let outcome = outcome_codec::decode(&payload).map_err(invalid)?;
    let evidence = &request.evidence;
    if evidence.role != "observer" {
        return Err(invalid("original Observer role required"));
    }
    let signed = SignedLearningEvidenceV1 {
        evidence_id: id(&evidence.evidence_id)?,
        principal_id: id(&evidence.principal_id)?,
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: Digest32::from_array(fixed(&evidence.trust_digest)?),
        scope_digest: Digest32::from_array(fixed(&evidence.scope_digest)?),
        objective_digest: Digest32::from_array(fixed(&evidence.objective_digest)?),
        authority_epoch: evidence.authority_epoch,
        issued_at: evidence.issued_at,
        expires_at: evidence.expires_at,
        payload_digest: Digest32::from_array(fixed(&evidence.payload_digest)?),
        signature: fixed(&evidence.signature_hex)?,
    };
    if signed.payload_digest != Digest32::of_bytes(&payload) {
        return Err(invalid("signed original Outcome preimage differs"));
    }
    Ok((outcome, signed))
}

fn id(value: &str) -> Result<StableId, AgentdError> {
    if !(1..=128).contains(&value.len()) {
        return Err(invalid("bounded original Observer identity required"));
    }
    StableId::new(value).map_err(invalid)
}

fn fixed<const N: usize>(value: &str) -> Result<[u8; N], AgentdError> {
    unhex(value, N)?
        .try_into()
        .map_err(|_| invalid("original Observer digest/signature width"))
}

fn unhex(value: &str, maximum: usize) -> Result<Vec<u8>, AgentdError> {
    if value.is_empty() || !value.len().is_multiple_of(2) || value.len() > maximum * 2 {
        return Err(invalid("bounded original Observer hex required"));
    }
    let digit = |byte: u8| match byte {
        b'0'..=b'9' => Ok(byte - b'0'),
        b'a'..=b'f' => Ok(byte - b'a' + 10),
        _ => Err(invalid("canonical lowercase Observer hex required")),
    };
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| Ok(digit(pair[0])? * 16 + digit(pair[1])?))
        .collect()
}

pub(super) fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(DIGITS[(byte >> 4) as usize]));
        output.push(char::from(DIGITS[(byte & 15) as usize]));
    }
    output
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("original Q24 Observer outcome: {error}"))
}
