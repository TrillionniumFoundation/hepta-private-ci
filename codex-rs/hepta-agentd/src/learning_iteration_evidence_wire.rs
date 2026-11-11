//! Fixed readback-only wire format. No request carries bytes to be signed.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::Error;

pub(super) const OPERATION: &str = "runtime.learning.evidence.readback.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub snapshot_head: String,
    pub operation_id: String,
    pub actor_id: String,
    pub predecessor: String,
    pub receipt_digest: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub binding: String,
    pub snapshot_head: String,
    pub receipt_digest: String,
    pub evidence: Evidence,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Evidence {
    pub evidence_id: String,
    pub principal_id: String,
    pub role: String,
    pub trust_digest: String,
    pub scope_digest: String,
    pub objective_digest: String,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub payload_digest: String,
    pub signature: String,
}

impl Evidence {
    pub(super) fn from_original(signed: &SignedLearningEvidenceV1) -> Self {
        Self {
            evidence_id: signed.evidence_id.to_string(),
            principal_id: signed.principal_id.to_string(),
            role: match signed.role {
                LearningEvidenceRoleV1::Generator => "generator",
                LearningEvidenceRoleV1::Observer => "observer",
                LearningEvidenceRoleV1::Evaluator => "evaluator",
                LearningEvidenceRoleV1::Selector => "selector",
            }.into(),
            trust_digest: signed.trust_digest.to_string(),
            scope_digest: signed.scope_digest.to_string(),
            objective_digest: signed.objective_digest.to_string(),
            authority_epoch: signed.authority_epoch,
            issued_at: signed.issued_at,
            expires_at: signed.expires_at,
            payload_digest: signed.payload_digest.to_string(),
            signature: STANDARD_NO_PAD.encode(signed.signature),
        }
    }

    pub(super) fn decode(self) -> Result<SignedLearningEvidenceV1, Error> {
        let invalid = || Error::Evidence(SignedEvidenceError::ContextMismatch);
        let signature = STANDARD_NO_PAD
            .decode(&self.signature)
            .map_err(|_| invalid())?;
        if STANDARD_NO_PAD.encode(&signature) != self.signature {
            return Err(invalid());
        }
        Ok(SignedLearningEvidenceV1 {
            evidence_id: StableId::new(self.evidence_id).map_err(|_| invalid())?,
            principal_id: StableId::new(self.principal_id).map_err(|_| invalid())?,
            role: match self.role.as_str() {
                "generator" => LearningEvidenceRoleV1::Generator,
                "observer" => LearningEvidenceRoleV1::Observer,
                "evaluator" => LearningEvidenceRoleV1::Evaluator,
                "selector" => LearningEvidenceRoleV1::Selector,
                _ => return Err(Error::Evidence(SignedEvidenceError::RoleMismatch)),
            },
            trust_digest: self.trust_digest.parse().map_err(|_| invalid())?,
            scope_digest: self.scope_digest.parse().map_err(|_| invalid())?,
            objective_digest: self.objective_digest.parse().map_err(|_| invalid())?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            payload_digest: self.payload_digest.parse().map_err(|_| invalid())?,
            signature: signature.try_into().map_err(|_| invalid())?,
        })
    }
}
