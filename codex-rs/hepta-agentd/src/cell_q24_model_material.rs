//! One unchanged pure material digest for local and original remote admission.
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::Digest32;
use crate::CellQ24ModelProposalErrorV1;

pub(crate) fn original_model_material_digest(
    training_evidence: Digest32,
    candidate: &CellBackendManifestV2,
    fixed: &CellBackendManifestV2,
    candidate_cut: Digest32,
    fixed_cut: Digest32,
    plan: Digest32,
    qualification: Digest32,
) -> Result<Digest32, CellQ24ModelProposalErrorV1> {
    Ok(Digest32::of_parts(&[
        b"hepta.cell.q24.model-proposal-material.v1\0", training_evidence.as_array(),
        &serde_json::to_vec(candidate).map_err(|_| CellQ24ModelProposalErrorV1::Binding("candidate manifest encoding"))?,
        &serde_json::to_vec(fixed).map_err(|_| CellQ24ModelProposalErrorV1::Binding("fixed manifest encoding"))?,
        candidate_cut.as_array(), fixed_cut.as_array(), plan.as_array(), qualification.as_array(),
    ]))
}
