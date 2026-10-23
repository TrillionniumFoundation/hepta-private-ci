//! Typed DecisionCell split binding for the generic topology candidate lane.
//!
//! The adapter keeps the semantic cell contract visible until the runtime
//! candidate is built. It grants no selection, activation or migration
//! authority; those remain with the existing topology and runtime owners.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::CellSplitContractErrorV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::StableId;

use crate::TopologyChangeV2;
use crate::TopologyOperationV2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitTopologyCandidateV1 {
    pub proposal_digest: Digest32,
    pub candidate_id: StableId,
    pub module_id: StableId,
    pub predecessor_digest: Digest32,
    pub candidate_graph_digest: Digest32,
    pub split: CellSplitV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitTopologyCandidateErrorV1 {
    Contract(CellSplitContractErrorV1),
    RuntimeTopology,
}

impl fmt::Display for CellSplitTopologyCandidateErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitTopologyCandidateErrorV1 {}

impl From<CellSplitContractErrorV1> for CellSplitTopologyCandidateErrorV1 {
    fn from(value: CellSplitContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

impl CellSplitTopologyCandidateV1 {
    /// Project the typed contract into the existing proposal-only topology
    /// change. The semantic contract digest is retained as evidence; callers
    /// must persist the typed contract alongside the proposal if they need to
    /// replay the full cell-level payload.
    #[allow(clippy::too_many_arguments)]
    pub fn topology_change(
        &self,
        capability_typing_digest: Digest32,
        compatibility_plan_digest: Digest32,
        lesion_ablation_digest: Digest32,
        resource_review_digest: Digest32,
        security_review_digest: Digest32,
        migration_digest: Digest32,
        rollback_digest: Digest32,
        writer_handoff_digest: Digest32,
    ) -> Result<TopologyChangeV2, CellSplitTopologyCandidateErrorV1> {
        let evidence_digest = self.split.evaluation_subject_digest()?;
        if [
            self.predecessor_digest,
            self.candidate_graph_digest,
            capability_typing_digest,
            compatibility_plan_digest,
            lesion_ablation_digest,
            resource_review_digest,
            security_review_digest,
            migration_digest,
            rollback_digest,
            writer_handoff_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
        {
            return Err(CellSplitTopologyCandidateErrorV1::RuntimeTopology);
        }
        Ok(TopologyChangeV2 {
            module_id: self.module_id.clone(),
            operation: TopologyOperationV2::Split,
            predecessor_digest: Some(self.predecessor_digest),
            candidate_digest: Some(self.candidate_graph_digest),
            capability_typing_digest,
            compatibility_plan_digest,
            lesion_ablation_digest,
            resource_review_digest,
            security_review_digest,
            migration_digest,
            rollback_digest,
            writer_handoff_digest,
            evidence_digest,
        })
    }

    /// Build the existing runtime candidate with a root `Split` plus explicit
    /// child `Add` deltas. The returned candidate remains deny-all data until
    /// the existing independent selection and FinalUse gates admit it.
    pub fn build_runtime_candidate(
        &self,
    ) -> Result<RuntimeTopologyCandidateV1, CellSplitTopologyCandidateErrorV1> {
        self.split
            .runtime_topology_candidate(
                self.proposal_digest,
                self.candidate_id.clone(),
                self.module_id.clone(),
                self.predecessor_digest,
                self.candidate_graph_digest,
            )
            .map_err(CellSplitTopologyCandidateErrorV1::from)
            .and_then(|candidate| {
                candidate
                    .validate()
                    .map_err(|_| CellSplitTopologyCandidateErrorV1::RuntimeTopology)?;
                Ok(candidate)
            })
    }
}
