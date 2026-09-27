//! Host-owned construction of the canonical learning Decision.
//!
//! The provider supplies policy identity, candidate-completeness evidence and a
//! signer capability.  Run, snapshot, selected candidate and dispatch identities
//! are derived only from the prepared canonical envelope.

use std::sync::Arc;

use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IntelligenceLearningBindingV1;
use crate::IntelligenceLearningErrorV1;
use crate::PreparedAgentdIntelligenceRunV1;

pub trait AgentdIntelligenceDecisionEvidenceProviderV1: Send + Sync {
    fn sign(
        &self,
        decision: &ProductionDecisionV2,
        now: u64,
    ) -> Result<SignedLearningEvidenceV1, IntelligenceLearningErrorV1>;
}

pub struct AgentdIntelligenceDecisionPlanV1 {
    expected_predecessor: Digest32,
    episode_id: StableId,
    policy_digest: Digest32,
    candidate_ids: Vec<StableId>,
    completeness: CandidateSetCompletenessReceiptV1,
    evidence_provider: Arc<dyn AgentdIntelligenceDecisionEvidenceProviderV1>,
}

impl AgentdIntelligenceDecisionPlanV1 {
    pub fn new(
        expected_predecessor: Digest32,
        episode_id: StableId,
        policy_digest: Digest32,
        mut candidate_ids: Vec<StableId>,
        completeness: CandidateSetCompletenessReceiptV1,
        evidence_provider: Arc<dyn AgentdIntelligenceDecisionEvidenceProviderV1>,
    ) -> Result<Self, IntelligenceLearningErrorV1> {
        candidate_ids.sort();
        if policy_digest.is_zero()
            || candidate_ids.is_empty()
            || candidate_ids.len() > 128
            || candidate_ids.windows(2).any(|pair| pair[0] == pair[1])
            || completeness.candidate_count as usize != candidate_ids.len()
            || completeness.candidates_digest.is_zero()
            || completeness.canonical_order_digest.is_zero()
            || !completeness.complete_for_generator
        {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "canonical Decision plan",
            ));
        }
        Ok(Self {
            expected_predecessor,
            episode_id,
            policy_digest,
            candidate_ids,
            completeness,
            evidence_provider,
        })
    }

    pub(crate) fn prepare(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        now: u64,
    ) -> Result<PreparedIntelligenceLearningDecisionV1, IntelligenceLearningErrorV1> {
        let AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } = &prepared.envelope.decision.decision
        else {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "learning Decision requires selected canonical outcome",
            ));
        };
        if now == 0
            || !self.candidate_ids.contains(candidate_id)
            || propensity.raw() == 0
            || self.completeness.candidates_digest
                != prepared.envelope.candidate_set_digest
        {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "prepared Decision binding",
            ));
        }
        let run_snapshot = prepared.run_snapshot();
        if run_snapshot.run_id != prepared.envelope.run_id.to_string()
            || run_snapshot.objective_digest != prepared.envelope.objective_digest.to_string()
            || run_snapshot.compilation_receipt_digest_is_invalid()
        {
            return Err(IntelligenceLearningErrorV1::Invalid(
                "prepared run snapshot identity",
            ));
        }
        let run_snapshot_digest = agent_run_snapshot_digest(&run_snapshot)?;
        let binding = IntelligenceLearningBindingV1::new(
            prepared.envelope.run_id.clone(),
            run_snapshot_digest,
            prepared.envelope.objective_digest,
            prepared.envelope.envelope_digest,
            prepared.envelope.candidate_set_digest,
            prepared.dispatch_proposal_digest,
            prepared.envelope.run_id.clone(),
            self.episode_id.clone(),
            candidate_id.clone(),
        )?;
        let decision = ProductionDecisionV2 {
            record_id: prepared.envelope.run_id.clone(),
            episode_id: self.episode_id.clone(),
            run_snapshot_digest,
            objective_digest: prepared.envelope.objective_digest,
            policy_digest: self.policy_digest,
            candidate_ids: self.candidate_ids.clone(),
            selected_candidate_id: candidate_id.clone(),
            selected_propensity: *propensity,
            completeness: self.completeness.clone(),
            support_digest: prepared.dispatch_proposal_digest,
        };
        let evidence = self.evidence_provider.sign(&decision, now)?;
        Ok(PreparedIntelligenceLearningDecisionV1 {
            binding,
            expected_predecessor: self.expected_predecessor,
            decision,
            evidence,
        })
    }
}

pub(crate) struct PreparedIntelligenceLearningDecisionV1 {
    pub binding: IntelligenceLearningBindingV1,
    pub expected_predecessor: Digest32,
    pub decision: ProductionDecisionV2,
    pub evidence: SignedLearningEvidenceV1,
}

fn agent_run_snapshot_digest(
    snapshot: &crate::AgentRunSnapshot,
) -> Result<Digest32, IntelligenceLearningErrorV1> {
    let mut bytes = b"hepta.agentd.intelligence-run-snapshot.v1\0".to_vec();
    for value in [
        snapshot.run_id.as_str(),
        snapshot.request_digest.as_str(),
        snapshot.objective_digest.as_str(),
        snapshot.body_digest.as_str(),
        snapshot.artifact_set_digest.as_str(),
        snapshot.fence_digest.as_str(),
    ] {
        push_string(&mut bytes, value)?;
    }
    bytes.extend_from_slice(&snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&snapshot.generation.to_be_bytes());
    bytes.extend_from_slice(&snapshot.deadline_ms.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_string(
    bytes: &mut Vec<u8>,
    value: &str,
) -> Result<(), IntelligenceLearningErrorV1> {
    let length = u32::try_from(value.len())
        .map_err(|_| IntelligenceLearningErrorV1::Invalid("snapshot field length"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

trait AgentRunSnapshotSanityV1 {
    fn compilation_receipt_digest_is_invalid(&self) -> bool;
}

impl AgentRunSnapshotSanityV1 for crate::AgentRunSnapshot {
    fn compilation_receipt_digest_is_invalid(&self) -> bool {
        self.request_digest.len() != 64
            || self.body_digest.len() != 64
            || self.artifact_set_digest.len() != 64
            || self.fence_digest.len() != 64
    }
}
