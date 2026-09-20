//! Qualification-only governance receipts used by the H8/H9 shadow
//! supervisor.  These receipts intentionally live next to the generic
//! governance contracts but are a separate type: creating one never grants
//! an enforce, production, outbound, or promotion capability.

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::Sha256Digest;

/// Schema identity for the local qualification receipt surface.
pub const QUALIFICATION_RECEIPT_SCHEMA_VERSION: u32 = 1;
/// Explicit namespace fence; this value is not accepted by production
/// governance consumers.
pub const QUALIFICATION_RECEIPT_NAMESPACE: &str = "local_qualification_only";
// Every authority/effect switch on a qualification receipt is a compile-time
// false contract.  Keeping the names explicit makes a serialized snapshot
// auditable and prevents a future caller from treating an omitted field as an
// implicit grant.
pub const QUALIFICATION_RECEIPT_PRODUCTION_CALLER: bool = false;
pub const QUALIFICATION_RECEIPT_PRODUCTION_WRITER: bool = false;
pub const QUALIFICATION_RECEIPT_EFFECT_AUTHORITY: bool = false;
pub const QUALIFICATION_RECEIPT_OPERATOR_ACCEPTANCE: bool = false;
pub const QUALIFICATION_RECEIPT_PROMOTION: bool = false;
pub const QUALIFICATION_RECEIPT_G5_ALLOWED: bool = false;
pub const QUALIFICATION_RECEIPT_EXECUTE_ALLOWED: bool = false;
pub const QUALIFICATION_RECEIPT_GOVERNANCE_BYPASS: bool = false;

/// Terminal state recorded by a qualification operation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QualificationReceiptStatus {
    Prepared,
    Committed,
    Recovered,
    RecoveryRequired,
    Rejected,
}

impl QualificationReceiptStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Committed => "committed",
            Self::Recovered => "recovered",
            Self::RecoveryRequired => "recovery_required",
            Self::Rejected => "rejected",
        }
    }
}

/// A digest-bound, qualification-only governance receipt.
///
/// `expected_revision` and `authority_epoch` are CAS witnesses.  The
/// resulting state digest is included in the receipt so a verifier can reject
/// a callback that was produced by a different local state head.  The boolean
/// authority fields are deliberately redundant and are checked on every
/// validation to make accidental promotion impossible.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationGovernanceReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub agent_id: String,
    pub operation: String,
    pub operation_id: Sha256Digest,
    pub owner_id: String,
    pub expected_revision: u64,
    pub committed_revision: u64,
    pub authority_epoch: u64,
    pub predecessor_state_sha256: Option<Sha256Digest>,
    pub resulting_state_sha256: Sha256Digest,
    pub status: QualificationReceiptStatus,
    pub production_authority: bool,
    pub external_effects: bool,
    pub promotion_eligible: bool,
    pub production_caller: bool,
    pub production_writer: bool,
    pub effect_authority: bool,
    pub operator_acceptance: bool,
    pub promotion: bool,
    pub g5_allowed: bool,
    pub execute_allowed: bool,
    pub governance_bypass: bool,
    pub receipt_sha256: Sha256Digest,
}

#[derive(Serialize)]
struct ReceiptDigest<'a> {
    schema_version: u32,
    namespace: &'a str,
    agent_id: &'a str,
    operation: &'a str,
    operation_id: &'a Sha256Digest,
    owner_id: &'a str,
    expected_revision: u64,
    committed_revision: u64,
    authority_epoch: u64,
    predecessor_state_sha256: &'a Option<Sha256Digest>,
    resulting_state_sha256: &'a Sha256Digest,
    status: QualificationReceiptStatus,
    production_authority: bool,
    external_effects: bool,
    promotion_eligible: bool,
    production_caller: bool,
    production_writer: bool,
    effect_authority: bool,
    operator_acceptance: bool,
    promotion: bool,
    g5_allowed: bool,
    execute_allowed: bool,
    governance_bypass: bool,
}

impl QualificationGovernanceReceipt {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        agent_id: impl Into<String>,
        operation: impl Into<String>,
        operation_id: Sha256Digest,
        owner_id: impl Into<String>,
        expected_revision: u64,
        committed_revision: u64,
        authority_epoch: u64,
        predecessor_state_sha256: Option<Sha256Digest>,
        resulting_state_sha256: Sha256Digest,
        status: QualificationReceiptStatus,
    ) -> Result<Self, String> {
        let mut receipt = Self {
            schema_version: QUALIFICATION_RECEIPT_SCHEMA_VERSION,
            namespace: QUALIFICATION_RECEIPT_NAMESPACE.to_string(),
            agent_id: agent_id.into(),
            operation: operation.into(),
            operation_id,
            owner_id: owner_id.into(),
            expected_revision,
            committed_revision,
            authority_epoch,
            predecessor_state_sha256,
            resulting_state_sha256,
            status,
            production_authority: false,
            external_effects: false,
            promotion_eligible: false,
            production_caller: QUALIFICATION_RECEIPT_PRODUCTION_CALLER,
            production_writer: QUALIFICATION_RECEIPT_PRODUCTION_WRITER,
            effect_authority: QUALIFICATION_RECEIPT_EFFECT_AUTHORITY,
            operator_acceptance: QUALIFICATION_RECEIPT_OPERATOR_ACCEPTANCE,
            promotion: QUALIFICATION_RECEIPT_PROMOTION,
            g5_allowed: QUALIFICATION_RECEIPT_G5_ALLOWED,
            execute_allowed: QUALIFICATION_RECEIPT_EXECUTE_ALLOWED,
            governance_bypass: QUALIFICATION_RECEIPT_GOVERNANCE_BYPASS,
            receipt_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        receipt.receipt_sha256 = receipt.compute_digest()?;
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != QUALIFICATION_RECEIPT_SCHEMA_VERSION
            || self.namespace != QUALIFICATION_RECEIPT_NAMESPACE
        {
            return Err("qualification receipt schema or namespace mismatch".to_string());
        }
        for (label, value) in [
            ("agent id", self.agent_id.as_str()),
            ("operation", self.operation.as_str()),
            ("owner id", self.owner_id.as_str()),
        ] {
            if value.trim().is_empty() || value.len() > 256 || value.as_bytes().contains(&0) {
                return Err(format!("qualification receipt {label} is malformed"));
            }
        }
        // A rejected callback is an observation, not a state mutation, so it
        // may legitimately carry an equal expected/committed revision.  Every
        // accepted/prepared/recovered outcome must advance exactly past its
        // CAS witness; a rejected outcome may never claim to move state
        // backwards.
        if self.status == QualificationReceiptStatus::Rejected {
            if self.expected_revision > self.committed_revision {
                return Err("qualification receipt rejected revision regressed".to_string());
            }
        } else if self.expected_revision >= self.committed_revision {
            return Err("qualification receipt revision did not advance".to_string());
        }
        if self.authority_epoch == 0 {
            return Err("qualification receipt authority epoch must be non-zero".to_string());
        }
        if self.production_authority
            || self.external_effects
            || self.promotion_eligible
            || self.production_caller
            || self.production_writer
            || self.effect_authority
            || self.operator_acceptance
            || self.promotion
            || self.g5_allowed
            || self.execute_allowed
            || self.governance_bypass
        {
            return Err("qualification receipt crosses the authority boundary".to_string());
        }
        for (label, digest) in [
            ("operation", &self.operation_id),
            ("resulting state", &self.resulting_state_sha256),
        ] {
            Sha256Digest::parse(digest.as_str().to_string())
                .map_err(|_| format!("qualification receipt {label} digest is malformed"))?;
        }
        if let Some(digest) = &self.predecessor_state_sha256 {
            Sha256Digest::parse(digest.as_str().to_string())
                .map_err(|_| "qualification receipt predecessor digest is malformed".to_string())?;
        }
        if self.receipt_sha256 != self.compute_digest()? {
            return Err("qualification receipt digest mismatch".to_string());
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, String> {
        self.validate()?;
        Ok(self.receipt_sha256.clone())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, String> {
        let payload = serde_json::to_vec(&ReceiptDigest {
            schema_version: self.schema_version,
            namespace: &self.namespace,
            agent_id: &self.agent_id,
            operation: &self.operation,
            operation_id: &self.operation_id,
            owner_id: &self.owner_id,
            expected_revision: self.expected_revision,
            committed_revision: self.committed_revision,
            authority_epoch: self.authority_epoch,
            predecessor_state_sha256: &self.predecessor_state_sha256,
            resulting_state_sha256: &self.resulting_state_sha256,
            status: self.status,
            production_authority: self.production_authority,
            external_effects: self.external_effects,
            promotion_eligible: self.promotion_eligible,
            production_caller: self.production_caller,
            production_writer: self.production_writer,
            effect_authority: self.effect_authority,
            operator_acceptance: self.operator_acceptance,
            promotion: self.promotion,
            g5_allowed: self.g5_allowed,
            execute_allowed: self.execute_allowed,
            governance_bypass: self.governance_bypass,
        })
        .map_err(|error| error.to_string())?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(payload)))
    }
}

/// Name used by callers that describe this receipt as a supervisor rollback
/// receipt.  Keeping the alias avoids a second, subtly different contract.
pub type SupervisorRollbackReceipt = QualificationGovernanceReceipt;
/// Short alias for qualification gate integrations.
pub type GovernanceQualificationReceipt = QualificationGovernanceReceipt;

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(seed: u8) -> Sha256Digest {
        Sha256Digest::for_bytes(&[seed; 8])
    }

    #[test]
    fn qualification_receipt_is_digest_bound_and_fail_closed() {
        let receipt = QualificationGovernanceReceipt::new(
            "agent-a",
            "rollback_commit",
            digest(1),
            "owner-a",
            4,
            5,
            9,
            Some(digest(2)),
            digest(3),
            QualificationReceiptStatus::Committed,
        )
        .expect("receipt");
        receipt.validate().expect("valid receipt");
        let mut tampered = receipt.clone();
        tampered.external_effects = true;
        assert!(tampered.validate().is_err());
        let mut tampered = receipt;
        tampered.status = QualificationReceiptStatus::Rejected;
        assert!(tampered.validate().is_err());
    }

    #[test]
    fn rejected_receipt_can_witness_a_non_mutating_callback() {
        let receipt = QualificationGovernanceReceipt::new(
            "agent-a",
            "rollback_rejected",
            digest(4),
            "owner-a",
            7,
            7,
            9,
            Some(digest(5)),
            digest(6),
            QualificationReceiptStatus::Rejected,
        )
        .expect("rejected receipt");
        receipt.validate().expect("valid rejection");
    }
}
