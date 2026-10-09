//! Typed role-qualification evidence carried by the CellSplit durable owners.
//!
//! The TaskFlow and learning-ledger owners remain lifecycle owners.  This
//! payload is deliberately an evidence record, not an activation command: it
//! retains the complete role/evaluator receipts in the durable replay stream
//! while target-host signatures and production admission remain external.

use codex_hepta_cell_roles::RoleIndependentEvaluatorReceiptV1;
use codex_hepta_cell_roles::RoleQualificationReceiptV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

pub const CELL_ROLE_QUALIFICATION_REPLAY_SCHEMA_V1: &str =
    "hepta.cell-role.qualification-replay.v1";
pub const MAX_CELL_ROLE_QUALIFICATION_REPLAY_BYTES: usize = 16 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRoleQualificationReplayV1 {
    pub qualification: RoleQualificationReceiptV1,
    pub evaluator: RoleIndependentEvaluatorReceiptV1,
}

impl CellRoleQualificationReplayV1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        self.qualification
            .validate()
            .map_err(|_| "role qualification receipt")?;
        if self.evaluator.cell_id != self.qualification.cell_id
            || self.evaluator.generation != self.qualification.generation
            || self.evaluator.role != self.qualification.role
            || self.evaluator.content_digest() != self.qualification.evaluator_receipt_digest
            || self.evaluator.evaluator_id.as_str().is_empty()
            || self.evaluator.proposer_id.as_str().is_empty()
            || self.evaluator.evaluated_receipt_digest.is_zero()
            || self.evaluator.evidence_digest.is_zero()
            || self.evaluator.evaluator_id == self.evaluator.proposer_id
            || self.evaluator.authority != AuthorityPosture::DENY_ALL
        {
            return Err("role evaluator binding");
        }
        Ok(())
    }

    /// Canonical bytes are retained in durable TaskFlow/ledger events.  The
    /// bytes include the typed receipt fields, rather than only a digest, so a
    /// clean replay can reconstruct and independently validate the evidence.
    #[must_use]
    pub fn canonical_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(512);
        bytes.extend_from_slice(CELL_ROLE_QUALIFICATION_REPLAY_SCHEMA_V1.as_bytes());
        push_id(&mut bytes, self.qualification.cell_id.as_str());
        bytes.extend_from_slice(&self.qualification.generation.get().to_be_bytes());
        bytes.push(self.qualification.role.tag());
        for digest in [
            self.qualification.definition_digest,
            self.qualification.artifact_receipt_digest,
            self.qualification.step_receipt_digest,
            self.qualification.metric_receipt_digest,
            self.qualification.fault_receipt_digest,
            self.qualification.evaluator_receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(self.qualification.origin.tag_for_replay());
        push_id(&mut bytes, self.evaluator.evaluator_id.as_str());
        push_id(&mut bytes, self.evaluator.proposer_id.as_str());
        bytes.extend_from_slice(self.evaluator.evaluated_receipt_digest.as_array());
        bytes.push(self.evaluator.disposition.tag_for_replay());
        bytes.extend_from_slice(self.evaluator.evidence_digest.as_array());
        bytes
    }

    pub fn encode_bounded(&self) -> Result<Vec<u8>, &'static str> {
        self.validate()?;
        let bytes = self.canonical_bytes();
        if bytes.len() > MAX_CELL_ROLE_QUALIFICATION_REPLAY_BYTES {
            return Err("role qualification replay payload capacity");
        }
        Ok(bytes)
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    let value = value.as_bytes();
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
}

trait ReplayTag {
    fn tag_for_replay(self) -> u8;
}

impl ReplayTag for codex_hepta_cell_roles::RoleQualificationEvidenceOriginV1 {
    fn tag_for_replay(self) -> u8 {
        match self {
            Self::LocalSimulation => 0,
            Self::RepositoryQualification => 1,
            Self::TargetHostMeasurement => 2,
        }
    }
}

impl ReplayTag for codex_hepta_cell_roles::RoleIndependentEvaluatorDispositionV1 {
    fn tag_for_replay(self) -> u8 {
        match self {
            Self::Retain => 0,
            Self::Quarantine => 1,
            Self::Reject => 2,
            Self::InsufficientEvidence => 3,
        }
    }
}

#[allow(dead_code)]
fn _digest_is_nonzero(value: Digest32) -> bool {
    !value.is_zero()
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_cell_roles::RoleIndependentEvaluatorDispositionV1;
    use codex_hepta_cell_roles::RoleQualificationEvidenceOriginV1;
    use codex_hepta_types::CellRoleV1;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn typed_role_and_evaluator_receipts_have_replay_payload() {
        let evaluator = RoleIndependentEvaluatorReceiptV1 {
            cell_id: id("memory-read-cell"),
            generation: Generation::new(1).expect("generation"),
            role: CellRoleV1::MemoryRead,
            evaluator_id: id("independent-evaluator"),
            proposer_id: id("role-proposer"),
            evaluated_receipt_digest: digest("evidence-bundle"),
            disposition: RoleIndependentEvaluatorDispositionV1::InsufficientEvidence,
            evidence_digest: digest("evaluator-evidence"),
            authority: AuthorityPosture::DENY_ALL,
        };
        let qualification = RoleQualificationReceiptV1 {
            cell_id: id("memory-read-cell"),
            generation: Generation::new(1).expect("generation"),
            role: CellRoleV1::MemoryRead,
            definition_digest: digest("definition"),
            artifact_receipt_digest: digest("artifact"),
            step_receipt_digest: digest("step"),
            metric_receipt_digest: digest("metric"),
            fault_receipt_digest: digest("fault"),
            evaluator_receipt_digest: evaluator.content_digest(),
            origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
            authority: AuthorityPosture::DENY_ALL,
        };
        let replay = CellRoleQualificationReplayV1 {
            qualification,
            evaluator,
        };
        replay.validate().expect("typed binding");
        let payload = replay.encode_bounded().expect("bounded payload");
        assert!(payload.starts_with(CELL_ROLE_QUALIFICATION_REPLAY_SCHEMA_V1.as_bytes()));
        assert!(payload.len() > 32, "payload must retain typed fields");
    }
}
