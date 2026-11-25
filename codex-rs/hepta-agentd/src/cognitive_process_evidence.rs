//! Bounded process input mapping. Raw fields are not verified capabilities.

use super::cognitive_process_wire::*;
use serde::Deserialize;
use serde::Serialize;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AuthenticatedPrincipalV1Raw {
    pub principal_id: Id,
    pub credential_chain_digest: Digest,
    pub signing_key_digest: Digest,
    pub scope_digest: Digest,
    pub authority_epoch: u64,
    pub authenticated_at: u64,
    pub expires_at: u64,
}

impl From<AuthenticatedPrincipalV1Raw> for codex_hepta_learning_ledger::AuthenticatedPrincipalV1 {
    fn from(raw: AuthenticatedPrincipalV1Raw) -> Self {
        Self {
            principal_id: raw.principal_id.into(),
            credential_chain_digest: raw.credential_chain_digest.into(),
            signing_key_digest: raw.signing_key_digest.into(),
            scope_digest: raw.scope_digest.into(),
            authority_epoch: raw.authority_epoch,
            authenticated_at: raw.authenticated_at,
            expires_at: raw.expires_at,
        }
    }
}

impl From<codex_hepta_learning_ledger::AuthenticatedPrincipalV1> for AuthenticatedPrincipalV1Raw {
    fn from(raw: codex_hepta_learning_ledger::AuthenticatedPrincipalV1) -> Self {
        Self {
            principal_id: raw.principal_id.into(),
            credential_chain_digest: raw.credential_chain_digest.into(),
            signing_key_digest: raw.signing_key_digest.into(),
            scope_digest: raw.scope_digest.into(),
            authority_epoch: raw.authority_epoch,
            authenticated_at: raw.authenticated_at,
            expires_at: raw.expires_at,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DatasetSnapshotV2Raw {
    pub snapshot_id: Id,
    pub ledger_head_digest: Digest,
    pub objective_digest: Digest,
    pub eligible_frontier: u64,
    pub outcome_watermark: u64,
    pub source_record_digests: Vec<Digest>,
    pub pending_outcomes: u32,
    pub censored_outcomes: u32,
    pub dataset_digest: Digest,
}

impl From<DatasetSnapshotV2Raw> for codex_hepta_learning_ledger::DatasetSnapshotV2 {
    fn from(raw: DatasetSnapshotV2Raw) -> Self {
        Self {
            snapshot_id: raw.snapshot_id.into(),
            ledger_head_digest: raw.ledger_head_digest.into(),
            objective_digest: raw.objective_digest.into(),
            eligible_frontier: raw.eligible_frontier,
            outcome_watermark: raw.outcome_watermark,
            source_record_digests: raw
                .source_record_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            pending_outcomes: raw.pending_outcomes,
            censored_outcomes: raw.censored_outcomes,
            dataset_digest: raw.dataset_digest.into(),
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        }
    }
}

impl From<codex_hepta_learning_ledger::DatasetSnapshotV2> for DatasetSnapshotV2Raw {
    fn from(raw: codex_hepta_learning_ledger::DatasetSnapshotV2) -> Self {
        Self {
            snapshot_id: raw.snapshot_id.into(),
            ledger_head_digest: raw.ledger_head_digest.into(),
            objective_digest: raw.objective_digest.into(),
            eligible_frontier: raw.eligible_frontier,
            outcome_watermark: raw.outcome_watermark,
            source_record_digests: raw
                .source_record_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            pending_outcomes: raw.pending_outcomes,
            censored_outcomes: raw.censored_outcomes,
            dataset_digest: raw.dataset_digest.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DatasetSnapshotReceiptV3Raw {
    pub snapshot: DatasetSnapshotV2Raw,
    pub producer: AuthenticatedPrincipalV1Raw,
    pub correction_cut_digest: Digest,
    pub revocation_cut_digest: Digest,
    pub inclusion_policy_digest: Digest,
}

impl From<DatasetSnapshotReceiptV3Raw> for codex_hepta_learning_ledger::DatasetSnapshotReceiptV3 {
    fn from(raw: DatasetSnapshotReceiptV3Raw) -> Self {
        Self {
            snapshot: raw.snapshot.into(),
            producer: raw.producer.into(),
            correction_cut_digest: raw.correction_cut_digest.into(),
            revocation_cut_digest: raw.revocation_cut_digest.into(),
            inclusion_policy_digest: raw.inclusion_policy_digest.into(),
        }
    }
}

impl From<codex_hepta_learning_ledger::DatasetSnapshotReceiptV3> for DatasetSnapshotReceiptV3Raw {
    fn from(raw: codex_hepta_learning_ledger::DatasetSnapshotReceiptV3) -> Self {
        Self {
            snapshot: raw.snapshot.into(),
            producer: raw.producer.into(),
            correction_cut_digest: raw.correction_cut_digest.into(),
            revocation_cut_digest: raw.revocation_cut_digest.into(),
            inclusion_policy_digest: raw.inclusion_policy_digest.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TrustedLearningSignerV1Raw {
    pub principal: AuthenticatedPrincipalV1Raw,
    pub controller_id: Id,
    pub verifying_key: Key,
    pub roles: Vec<LearningEvidenceRoleV1Raw>,
    pub revoked_at: Option<u64>,
}

impl From<TrustedLearningSignerV1Raw> for codex_hepta_learning_ledger::TrustedLearningSignerV1 {
    fn from(raw: TrustedLearningSignerV1Raw) -> Self {
        Self {
            principal: raw.principal.into(),
            controller_id: raw.controller_id.into(),
            verifying_key: raw.verifying_key.into(),
            roles: raw
                .roles
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            revoked_at: raw.revoked_at,
        }
    }
}

impl From<codex_hepta_learning_ledger::TrustedLearningSignerV1> for TrustedLearningSignerV1Raw {
    fn from(raw: codex_hepta_learning_ledger::TrustedLearningSignerV1) -> Self {
        Self {
            principal: raw.principal.into(),
            controller_id: raw.controller_id.into(),
            verifying_key: raw.verifying_key.into(),
            roles: raw
                .roles
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            revoked_at: raw.revoked_at,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LearningEvidenceTrustV1Raw {
    pub scope_digest: Digest,
    pub objective_digest: Digest,
    pub authority_epoch: u64,
    pub signers: Vec<TrustedLearningSignerV1Raw>,
}

impl From<LearningEvidenceTrustV1Raw> for codex_hepta_learning_ledger::LearningEvidenceTrustV1 {
    fn from(raw: LearningEvidenceTrustV1Raw) -> Self {
        Self {
            scope_digest: raw.scope_digest.into(),
            objective_digest: raw.objective_digest.into(),
            authority_epoch: raw.authority_epoch,
            signers: raw
                .signers
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
        }
    }
}

impl From<codex_hepta_learning_ledger::LearningEvidenceTrustV1> for LearningEvidenceTrustV1Raw {
    fn from(raw: codex_hepta_learning_ledger::LearningEvidenceTrustV1) -> Self {
        Self {
            scope_digest: raw.scope_digest.into(),
            objective_digest: raw.objective_digest.into(),
            authority_epoch: raw.authority_epoch,
            signers: raw
                .signers
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignedLearningEvidenceV1Raw {
    pub evidence_id: Id,
    pub principal_id: Id,
    pub role: LearningEvidenceRoleV1Raw,
    pub trust_digest: Digest,
    pub scope_digest: Digest,
    pub objective_digest: Digest,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub payload_digest: Digest,
    pub signature: Signature,
}

impl From<SignedLearningEvidenceV1Raw> for codex_hepta_learning_ledger::SignedLearningEvidenceV1 {
    fn from(raw: SignedLearningEvidenceV1Raw) -> Self {
        Self {
            evidence_id: raw.evidence_id.into(),
            principal_id: raw.principal_id.into(),
            role: raw.role.into(),
            trust_digest: raw.trust_digest.into(),
            scope_digest: raw.scope_digest.into(),
            objective_digest: raw.objective_digest.into(),
            authority_epoch: raw.authority_epoch,
            issued_at: raw.issued_at,
            expires_at: raw.expires_at,
            payload_digest: raw.payload_digest.into(),
            signature: raw.signature.into(),
        }
    }
}

impl From<codex_hepta_learning_ledger::SignedLearningEvidenceV1> for SignedLearningEvidenceV1Raw {
    fn from(raw: codex_hepta_learning_ledger::SignedLearningEvidenceV1) -> Self {
        Self {
            evidence_id: raw.evidence_id.into(),
            principal_id: raw.principal_id.into(),
            role: raw.role.into(),
            trust_digest: raw.trust_digest.into(),
            scope_digest: raw.scope_digest.into(),
            objective_digest: raw.objective_digest.into(),
            authority_epoch: raw.authority_epoch,
            issued_at: raw.issued_at,
            expires_at: raw.expires_at,
            payload_digest: raw.payload_digest.into(),
            signature: raw.signature.into(),
        }
    }
}
