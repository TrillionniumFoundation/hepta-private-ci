//! Join the original seven-owner admission with independently read CURRENT.
use crate::RegisteredArtifactCurrentFactsV3;
use crate::initial_neuron_operational_source::HostResult;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use codex_hepta_plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

/// Original parameter/head artifacts and operational model weights have distinct
/// identities. Require the actual eligible selected artifact and whole baseline;
/// the supplied read-only owner facts were authenticated by their original owner.
pub fn validate_current_parameter_admission_v1(
    current: &RegisteredArtifactCurrentFactsV3,
    admission: &PlasticityAdmissionEvidenceV1,
    baseline: &NeuronGenerationMaterialV2,
) -> HostResult<()> {
    if current.material_digest()
        != Digest32::of_bytes(&encode_neuron_generation_material_v2(baseline)?)
    {
        return Err("parameter admission changed the original full CURRENT material".into());
    }
    let selected = current
        .current_view()
        .eligible_manifest(&admission.baseline_id)
        .ok_or("parameter/head baseline is not eligible in original CURRENT")?;
    validate_selected_tuple(
        selected,
        admission,
        baseline.native.model_digest,
        baseline.runtime.generation,
        baseline.scope.objective_digest,
        current.current_view().receipt().head_digest,
    )
}

fn validate_selected_tuple(
    selected: &ArtifactManifest,
    admission: &PlasticityAdmissionEvidenceV1,
    parameter_head: Digest32,
    generation: Generation,
    objective: Digest32,
    current_head: Digest32,
) -> HostResult<()> {
    if !matches!(
        selected.kind,
        ArtifactKind::Parameters | ArtifactKind::Model
    ) || selected.artifact_id != admission.baseline_id
        || selected.content_digest != parameter_head
        || selected.content_digest != admission.selected_artifact_digest
        || selected.generation != generation
        || selected.generation != admission.baseline_generation
        || selected.objective_digest != objective
        || selected.objective_digest != admission.objective_digest
        || selected.compatibility_digest != admission.artifact_registry_binding
        || current_head != admission.artifact_registry_head_digest
    {
        return Err("original CURRENT parameter/head artifact tuple differs from admission".into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "fixed_parameter_current_admission_v1_tests.rs"]
mod tests;
