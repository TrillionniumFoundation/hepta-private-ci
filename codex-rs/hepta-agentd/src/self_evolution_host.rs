//! Agentd composition for independently selected next-generation artifacts.
//!
//! Agentd does not generate, evaluate, sign or select candidates here. It
//! consumes an independently authenticated selection witness derived from the
//! causal learning ledger and delegates exact-generation adoption/rollback to
//! control.runtime. No merge, release or effect authority is created.

use codex_hepta_control_plane::{
    SelfEvolutionAdoptionReceiptV1, SelfEvolutionRollbackReceiptV1,
    SelfEvolutionRuntimeError, SelfEvolutionRuntimeV1,
};
use codex_hepta_intelligence_eval::{
    IndependentEvaluationBundleV1, LongitudinalTimeEvidenceV1, MetricRoleContractV2,
    SelfEvolutionSelectionError, SelfEvolutionSelectionPolicyV1,
    SelfEvolutionSelectionRequestV1, SignedEvaluationEvidenceV1,
    select_self_evolution_v1,
};
use codex_hepta_learning_ledger::{
    DatasetSnapshotReceiptV3, LearningEvidenceRoleV1, LearningEvidenceVerifierV1, LedgerSnapshot,
    SignedLearningEvidenceV1, VerifiedLearningEvidenceV1,
};
use codex_hepta_types::{Digest32, SelfEvolutionSelectionWitnessV1};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdSelfEvolutionAdoptionV1 {
    pub selection: SelfEvolutionSelectionWitnessV1,
    pub adoption: SelfEvolutionAdoptionReceiptV1,
}

#[derive(Debug)]
pub enum AgentdSelfEvolutionError {
    Selection(SelfEvolutionSelectionError),
    Runtime(SelfEvolutionRuntimeError),
    EvidenceRole,
    EvidenceBinding,
    EvidenceIndependence,
}

impl std::fmt::Display for AgentdSelfEvolutionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AgentdSelfEvolutionError {}

impl From<SelfEvolutionSelectionError> for AgentdSelfEvolutionError {
    fn from(value: SelfEvolutionSelectionError) -> Self {
        Self::Selection(value)
    }
}

impl From<SelfEvolutionRuntimeError> for AgentdSelfEvolutionError {
    fn from(value: SelfEvolutionRuntimeError) -> Self {
        Self::Runtime(value)
    }
}

/// Runtime-local host state. The selected generation remains authority-free;
/// a separate activation/release owner must still decide whether a qualified
/// artifact becomes part of a deployable signed topology.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdSelfEvolutionHostV1 {
    runtime: SelfEvolutionRuntimeV1,
}

impl AgentdSelfEvolutionHostV1 {
    pub fn new(runtime: SelfEvolutionRuntimeV1) -> Self {
        Self { runtime }
    }

    pub fn runtime(&self) -> &SelfEvolutionRuntimeV1 {
        &self.runtime
    }

    #[allow(clippy::too_many_arguments)]
    pub fn select_and_adopt(
        &mut self,
        policy: &SelfEvolutionSelectionPolicyV1,
        request: SelfEvolutionSelectionRequestV1,
        evaluation_bundle: IndependentEvaluationBundleV1,
        metric_roles: Vec<MetricRoleContractV2>,
        evaluation_evidence: &SignedEvaluationEvidenceV1,
        longitudinal_time: &LongitudinalTimeEvidenceV1,
        dataset_receipt: &DatasetSnapshotReceiptV3,
        ledger_snapshot: &LedgerSnapshot,
        selector_evidence: &SignedLearningEvidenceV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<AgentdSelfEvolutionAdoptionV1, AgentdSelfEvolutionError> {
        let selection = select_self_evolution_v1(
            policy,
            request,
            evaluation_bundle,
            metric_roles,
            evaluation_evidence,
            longitudinal_time,
            dataset_receipt,
            ledger_snapshot,
            selector_evidence,
            verifier,
            now,
        )?;
        let adoption = self.runtime.adopt_self_evolution(&selection)?;
        Ok(AgentdSelfEvolutionAdoptionV1 { selection, adoption })
    }

    /// Rollback requires an opaque evaluator-verified token over the exact
    /// selected candidate, generation and regression digest. The token type
    /// cannot be constructed by product callers; it is emitted only by the
    /// learning evidence verifier after signature/trust/expiry checks.
    pub fn rollback_selected(
        &mut self,
        selection: &SelfEvolutionSelectionWitnessV1,
        regression_evidence_digest: Digest32,
        evidence: &VerifiedLearningEvidenceV1,
    ) -> Result<SelfEvolutionRollbackReceiptV1, AgentdSelfEvolutionError> {
        self.require_independent_evaluator(
            selection,
            regression_evidence_digest,
            b"rollback",
            evidence,
        )?;
        Ok(self.runtime.rollback_self_evolution(selection, regression_evidence_digest)?)
    }

    /// Dropping the rollback checkpoint is itself evidence-gated. A candidate
    /// cannot make its own canary permanent merely by presenting the selection
    /// digest that was already required for adoption.
    pub fn confirm_selected(
        &mut self,
        selection: &SelfEvolutionSelectionWitnessV1,
        stability_evidence_digest: Digest32,
        evidence: &VerifiedLearningEvidenceV1,
    ) -> Result<(), AgentdSelfEvolutionError> {
        self.require_independent_evaluator(
            selection,
            stability_evidence_digest,
            b"confirm",
            evidence,
        )?;
        self.runtime.confirm_self_evolution(selection.selection_digest)?;
        Ok(())
    }

    fn require_independent_evaluator(
        &self,
        selection: &SelfEvolutionSelectionWitnessV1,
        evidence_digest: Digest32,
        disposition: &[u8],
        evidence: &VerifiedLearningEvidenceV1,
    ) -> Result<(), AgentdSelfEvolutionError> {
        if evidence_digest.is_zero()
            || self.runtime.active_candidate_id() != &selection.candidate_id
            || self.runtime.generation() != selection.candidate_generation
            || self.runtime.artifact_digest() != selection.candidate_artifact_digest
        {
            return Err(AgentdSelfEvolutionError::EvidenceBinding);
        }
        if evidence.role() != LearningEvidenceRoleV1::Evaluator {
            return Err(AgentdSelfEvolutionError::EvidenceRole);
        }
        if evidence.principal().principal_id == selection.selector_id {
            return Err(AgentdSelfEvolutionError::EvidenceIndependence);
        }
        let payload = self_evolution_runtime_evidence_payload(
            selection,
            evidence_digest,
            disposition,
        );
        if evidence.payload_digest() != Digest32::of_bytes(&payload) {
            return Err(AgentdSelfEvolutionError::EvidenceBinding);
        }
        Ok(())
    }
}

fn self_evolution_runtime_evidence_payload(
    selection: &SelfEvolutionSelectionWitnessV1,
    evidence_digest: Digest32,
    disposition: &[u8],
) -> Vec<u8> {
    let mut bytes = b"hepta.agentd.self-evolution-runtime-evidence.v1\0".to_vec();
    bytes.extend_from_slice(&(disposition.len() as u64).to_be_bytes());
    bytes.extend_from_slice(disposition);
    bytes.extend_from_slice(selection.selection_digest.as_array());
    bytes.extend_from_slice(selection.candidate_artifact_digest.as_array());
    bytes.extend_from_slice(&selection.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(evidence_digest.as_array());
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::{AuthorityPosture, Generation, StableId};

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).unwrap()
    }

    fn witness() -> SelfEvolutionSelectionWitnessV1 {
        SelfEvolutionSelectionWitnessV1 {
            selection_id: id("selection"),
            predecessor_id: id("baseline"),
            predecessor_generation: generation(10),
            candidate_id: id("candidate"),
            candidate_generation: generation(11),
            candidate_artifact_digest: Digest32::of_bytes(b"candidate"),
            rollback_digest: Digest32::of_bytes(b"rollback"),
            no_change_baseline_id: id("baseline"),
            dataset_digest: Digest32::of_bytes(b"dataset"),
            ledger_head_digest: Digest32::of_bytes(b"ledger"),
            evaluation_evidence_digest: Digest32::of_bytes(b"evaluation"),
            evaluation_authentication_digest: Digest32::of_bytes(b"authentication"),
            selector_id: id("independent-selector"),
            selector_evidence_digest: Digest32::of_bytes(b"selector-evidence"),
            selection_digest: Digest32::of_bytes(b"selection-digest"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn selected_candidate_is_consumed_and_regression_rolls_back_exactly() {
        let runtime = SelfEvolutionRuntimeV1::new(
            id("baseline"),
            generation(10),
            Digest32::of_bytes(b"baseline"),
        )
        .unwrap();
        let mut host = AgentdSelfEvolutionHostV1::new(runtime);
        let selected = witness();
        let adoption = host.runtime.adopt_self_evolution(&selected).unwrap();
        let adopted = AgentdSelfEvolutionAdoptionV1 { selection: selected.clone(), adoption };
        assert_eq!(host.runtime().generation(), generation(11));
        assert_eq!(adopted.selection.selector_id, id("independent-selector"));

        let rolled = host
            .runtime
            .rollback_self_evolution(&selected, Digest32::of_bytes(b"future-regression"))
            .unwrap();
        assert_eq!(rolled.restored_candidate_id, id("baseline"));
        assert_eq!(host.runtime().generation(), generation(12));
    }

    #[test]
    fn selection_with_authority_cannot_enter_runtime() {
        let runtime = SelfEvolutionRuntimeV1::new(
            id("baseline"),
            generation(10),
            Digest32::of_bytes(b"baseline"),
        )
        .unwrap();
        let mut host = AgentdSelfEvolutionHostV1::new(runtime);
        let mut selected = witness();
        selected.authority = AuthorityPosture {
            runtime: true,
            ..AuthorityPosture::DENY_ALL
        };
        assert_eq!(
            host.runtime.adopt_self_evolution(&selected),
            Err(SelfEvolutionRuntimeError::SelectionAuthority)
        );
    }
}
