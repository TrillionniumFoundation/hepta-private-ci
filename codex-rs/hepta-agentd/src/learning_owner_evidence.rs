//! Bounded storage encoding for original evidence; never a signing wire API.

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::learning_owner_journal::LearningOriginalOwnerErrorV1 as Error;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedEvidence {
    schema: u8,
    payload: Vec<u8>,
    evidence_id: String,
    principal_id: String,
    role: u8,
    trust_digest: String,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    payload_digest: String,
    signature: Vec<u8>,
}

pub(crate) fn encode(payload: &[u8], evidence: &SignedLearningEvidenceV1) -> Result<Vec<u8>, Error> {
    if payload.len() > 16_384 || evidence.evidence_id.as_str().len() > 128 || evidence.principal_id.as_str().len() > 128 {
        return Err(Error::Binding("bounded original attestation"));
    }
    let saved = SavedEvidence {
        schema: 1,
        payload: payload.to_vec(),
        evidence_id: evidence.evidence_id.to_string(),
        principal_id: evidence.principal_id.to_string(),
        role: match evidence.role {
            LearningEvidenceRoleV1::Generator => 0,
            LearningEvidenceRoleV1::Observer => 1,
            LearningEvidenceRoleV1::Evaluator => 2,
            LearningEvidenceRoleV1::Selector => 3,
            _ => return Err(Error::Binding("original stage evidence role")),
        },
        trust_digest: evidence.trust_digest.to_string(),
        scope_digest: evidence.scope_digest.to_string(),
        objective_digest: evidence.objective_digest.to_string(),
        authority_epoch: evidence.authority_epoch,
        issued_at: evidence.issued_at,
        expires_at: evidence.expires_at,
        payload_digest: evidence.payload_digest.to_string(),
        signature: evidence.signature.to_vec(),
    };
    let bytes = serde_json::to_vec(&saved).map_err(|_| Error::Binding("attestation encoding"))?;
    if bytes.len() > 65_536 {
        return Err(Error::Binding("bounded encoded attestation"));
    }
    Ok(bytes)
}

pub(crate) fn decode(bytes: &[u8]) -> Result<(Vec<u8>, SignedLearningEvidenceV1), Error> {
    let invalid = || Error::Binding("original attestation encoding");
    if bytes.len() > 65_536 {
        return Err(invalid());
    }
    let saved: SavedEvidence = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if saved.schema != 1 {
        return Err(invalid());
    }
    let evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(saved.evidence_id).map_err(|_| invalid())?,
        principal_id: StableId::new(saved.principal_id).map_err(|_| invalid())?,
        role: match saved.role {
            0 => LearningEvidenceRoleV1::Generator,
            1 => LearningEvidenceRoleV1::Observer,
            2 => LearningEvidenceRoleV1::Evaluator,
            3 => LearningEvidenceRoleV1::Selector,
            _ => return Err(invalid()),
        },
        trust_digest: saved.trust_digest.parse().map_err(|_| invalid())?,
        scope_digest: saved.scope_digest.parse().map_err(|_| invalid())?,
        objective_digest: saved.objective_digest.parse().map_err(|_| invalid())?,
        authority_epoch: saved.authority_epoch,
        issued_at: saved.issued_at,
        expires_at: saved.expires_at,
        payload_digest: saved.payload_digest.parse().map_err(|_| invalid())?,
        signature: saved.signature.try_into().map_err(|_| invalid())?,
    };
    if encode(&saved.payload, &evidence)? != bytes {
        return Err(invalid());
    }
    Ok((saved.payload, evidence))
}
