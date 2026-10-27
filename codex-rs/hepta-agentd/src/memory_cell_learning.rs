//! Memory training records in the existing signed, durable causal ledger.
//! A completed training candidate is not a deployment decision or an outcome.

use std::sync::Mutex;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::LedgerWitnessFrontier;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::MemoryCellTrainingCandidateV1;

pub struct MemoryCellTrainingDecisionContextV1 {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub objective_digest: Digest32,
    pub generator_id: StableId,
}

/// Prepared only from an actual training host candidate. The candidate set is
/// the output of one completed fit plus the ledger's required abstain option,
/// not a claim of complete architecture or deployment search. A Generator must
/// sign its existing V2 payload to append.
pub struct MemoryCellLearningDecisionV1 {
    decision: ProductionDecisionV2,
}

impl MemoryCellLearningDecisionV1 {
    pub fn from_training(candidate: &MemoryCellTrainingCandidateV1, context: MemoryCellTrainingDecisionContextV1) -> Result<Self, String> {
        let receipt = serde_json::to_vec(candidate.receipt()).map_err(|_| "training receipt encoding failed")?;
        prepare(context, candidate.snapshot().owner_cut_digest().digest(), candidate.training_code_digest(),
            Digest32::of_bytes(&receipt), candidate.bundle().digest().digest())
    }

    pub fn decision(&self) -> &ProductionDecisionV2 { &self.decision }

    pub fn signing_payload(&self) -> Result<Vec<u8>, String> {
        decision_signing_payload_v2(&self.decision).map_err(|error| error.to_string())
    }

    /// Bind independently acquired outcome evidence to this exact trained
    /// candidate. This digest does not authenticate an Observer or its result.
    pub fn outcome_support_digest(&self, independent_observation: Digest32) -> Result<Digest32, String> {
        if independent_observation.is_zero() { return Err("memory outcome lacks independent observation evidence".to_string()); }
        Ok(Digest32::of_parts(&[b"hepta.memory.training-outcome-support.v1",
            self.decision.support_digest.as_array(), independent_observation.as_array()]))
    }
}

/// Consumes the real product LedgerWriter. No alternate log or signing key is
/// created here; current trust and role independence remain ledger authority.
pub struct MemoryCellLearningSinkV1 { writer: Mutex<LedgerWriter> }

impl MemoryCellLearningSinkV1 {
    pub fn new(writer: LedgerWriter) -> Self { Self { writer: Mutex::new(writer) } }

    pub fn append_training(&self, expected_predecessor: Digest32, prepared: &MemoryCellLearningDecisionV1,
        generator_evidence: &SignedLearningEvidenceV1, now: u64) -> Result<AppendReceipt, String> {
        self.writer.lock().map_err(|_| "memory learning writer lock poisoned")?
            .append_decision(expected_predecessor, prepared.decision.clone(), generator_evidence, now)
            .map_err(|error| error.to_string())
    }

    pub fn append_outcome(&self, expected_predecessor: Digest32, prepared: &MemoryCellLearningDecisionV1,
        independent_observation: Digest32, outcome: AuthenticatedOutcomeV1,
        observer_evidence: &SignedLearningEvidenceV1, now: u64) -> Result<AppendReceipt, String> {
        if outcome.episode_id != prepared.decision.episode_id
            || outcome.support_digest != prepared.outcome_support_digest(independent_observation)? {
            return Err("memory outcome differs from its training episode or independent evidence".to_string());
        }
        let mut writer = self.writer.lock().map_err(|_| "memory learning writer lock poisoned")?;
        let expected = &prepared.decision;
        writer.verify_active_decision_binding(&expected.record_id, &expected.episode_id).map_err(|error| error.to_string())?;
        if !writer.records().map_err(|error| error.to_string())?.iter().any(|record| {
            matches!(&record.event, LedgerEvent::AuthenticatedDecisionV2(actual)
                if actual.record_id == expected.record_id && actual.episode_id == expected.episode_id
                    && actual.run_snapshot_digest == expected.run_snapshot_digest && actual.policy_digest == expected.policy_digest
                    && actual.objective_digest == expected.objective_digest && actual.selected_candidate_id == expected.selected_candidate_id
                    && actual.support_digest == expected.support_digest)
        }) {
            return Err("memory outcome is not bound to the recorded training candidate".to_string());
        }
        writer.append_outcome(expected_predecessor, outcome, observer_evidence, now).map_err(|error| error.to_string())
    }

    pub fn snapshot(&self) -> Result<LedgerSnapshot, String> {
        self.writer.lock().map_err(|_| "memory learning writer lock poisoned")?.snapshot().map_err(|error| error.to_string())
    }

    pub fn witness_frontier(&self) -> Result<LedgerWitnessFrontier, String> {
        self.writer.lock().map_err(|_| "memory learning writer lock poisoned")?.witness_frontier().map_err(|error| error.to_string())
    }
}

fn prepare(context: MemoryCellTrainingDecisionContextV1, cut: Digest32, code: Digest32, receipt: Digest32, bundle: Digest32) -> Result<MemoryCellLearningDecisionV1, String> {
    if [cut, code, receipt, bundle, context.objective_digest].iter().any(|digest| digest.is_zero()) {
        return Err("memory training evidence binding contains a zero digest".to_string());
    }
    let support = Digest32::of_parts(&[b"hepta.memory.training-candidate-support.v1", cut.as_array(), code.as_array(), receipt.as_array(), bundle.as_array()]);
    let candidate = StableId::new(format!("memory-bundle:{bundle}")).map_err(|error| error.to_string())?;
    let abstain = StableId::new("abstain").map_err(|error| error.to_string())?;
    let candidates = vec![abstain, candidate.clone()];
    let set_id = StableId::new(format!("memory-training-result:{support}")).map_err(|error| error.to_string())?;
    let decision = ProductionDecisionV2 {
        record_id: context.record_id, episode_id: context.episode_id, run_snapshot_digest: cut,
        objective_digest: context.objective_digest, policy_digest: code, candidate_ids: candidates.clone(),
        selected_candidate_id: candidate, selected_propensity: ProbabilityQ32::ONE, support_digest: support,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id, state_digest: cut, generator_id: context.generator_id, generator_code_digest: code,
            grammar_digest: Digest32::of_bytes(b"hepta.memory.training-completed-fit-or-abstain.v1"),
            hard_filter_digest: Digest32::of_bytes(b"hepta.memory.native-bundle-owner-binding.v1"),
            truncation_digest: Digest32::of_bytes(b"hepta.memory.no-training-output-omissions.v1"),
            candidates_digest: candidate_ids_digest_v2(&candidates), candidate_count: 2, omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates), complete_for_generator: true,
        },
    };
    decision_signing_payload_v2(&decision).map_err(|error| error.to_string())?;
    Ok(MemoryCellLearningDecisionV1 { decision })
}

#[cfg(test)]
#[path = "memory_cell_learning_test_support.rs"]
pub(crate) mod test_support;
#[cfg(test)]
#[path = "memory_cell_learning_tests.rs"]
mod tests;
