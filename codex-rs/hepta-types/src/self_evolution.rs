use crate::AuthorityPosture;
use crate::Digest32;
use crate::Generation;
use crate::StableId;

/// Stable authority-free handoff between independent evaluation and runtime
/// control. Producing this witness requires an evaluator/selector policy in the
/// learning layer; consuming it grants no merge, promotion, release or effect
/// authority by itself.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionWitnessV1 {
    pub selection_id: StableId,
    pub predecessor_id: StableId,
    pub predecessor_generation: Generation,
    pub candidate_id: StableId,
    pub candidate_generation: Generation,
    pub candidate_artifact_digest: Digest32,
    pub rollback_digest: Digest32,
    pub no_change_baseline_id: StableId,
    pub dataset_digest: Digest32,
    pub ledger_head_digest: Digest32,
    pub evaluation_evidence_digest: Digest32,
    pub evaluation_authentication_digest: Digest32,
    pub selector_id: StableId,
    pub selector_evidence_digest: Digest32,
    pub selection_digest: Digest32,
    pub authority: AuthorityPosture,
}
