//! Reopen the original completed publisher before projecting a complete
//! read-only registration. Publication and every ACK remain the native owner.
use super::*;
use codex_hepta_agent_components::intelligence_eval::ParameterRoleSourceV3;
use codex_hepta_agent_components::intelligence_eval::inspect_registered_artifact_current_material_v3;
use codex_hepta_agent_components::intelligence_eval::project_registered_artifact_manifest_configuration_v3;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use std::os::unix::fs::PermissionsExt;

pub(crate) fn project(
    registration_template: &InstalledCpuSourceV1,
    publication: &crate::initial_cpu_anchor::ParameterPreRegisteredPublicationV1,
    material: &NeuronGenerationMaterialV2,
    publication_configuration: &InstalledCpuSourceV1,
    subject: &codex_hepta_types::StableId,
    public_directory: &Path,
) -> Result<InstalledCpuSourceV1> {
    let observed = crate::initial_cpu_anchor::observe_parameter_pre_registered_artifacts_v1(
        &publication_configuration.path,
        publication_configuration.digest.parse()?,
    ).map_err(|error| anyhow::anyhow!("{error}"))?
        .context("whole native four-artifact publication is not completed")?;
    let original = serde_json::to_vec(publication)?;
    ensure!(serde_json::to_vec(&observed)? == original
        && publication.material_digest == Digest32::of_bytes(
            &encode_neuron_generation_material_v2(material)?).to_string(),
        "complete native publication differs from original material or receipts");
    let manifests = [0, 1, 2].map(|index| {
        let artifact = &publication.publications[index];
        (ParameterRoleSourceV3 {
            path: artifact.manifest.path.clone(), digest: artifact.manifest.digest.clone(),
        }, artifact.admission_digest.parse::<Digest32>())
    });
    let manifests = manifests.map(|(source, admission)| admission.map(|admission| (source, admission)));
    let mut complete = Vec::new();
    for manifest in manifests { complete.push(manifest?); }
    let manifests = complete.try_into().map_err(|_| anyhow::anyhow!("three native manifests"))?;
    let bytes = project_registered_artifact_manifest_configuration_v3(
        &registration_template.path,
        registration_template.digest.parse()?,
        &manifests, material, subject, now_ms()?,
    ).map_err(|error| anyhow::anyhow!("{error}"))?;
    execution::protected_directory(public_directory)?;
    ensure!(std::fs::symlink_metadata(public_directory)?.permissions().mode() & 0o777 == 0o755,
        "original public registration directory is not traversable");
    let key = Digest32::of_parts(&[
        b"hepta.original-parameter-publication-registration.v1\0", &original, &bytes,
    ]);
    let path = public_directory.join(format!("registration-{key}.json"));
    execution::immutable(&path, &bytes, 64 * 1024)?;
    let projected = InstalledCpuSourceV1 { path, digest: Digest32::of_bytes(&bytes).to_string() };
    let facts = inspect_registered_artifact_current_material_v3(
        &projected.path, projected.digest.parse()?, material, subject, now_ms()?,
    ).map_err(|error| anyhow::anyhow!("{error}"))?;
    facts.revalidate_current(now_ms()?).map_err(|error| anyhow::anyhow!("{error}"))?;
    ensure!(serde_json::to_vec(&crate::initial_cpu_anchor::observe_parameter_pre_registered_artifacts_v1(
        &publication_configuration.path, publication_configuration.digest.parse()?,
    ).map_err(|error| anyhow::anyhow!("{error}"))?
        .context("original native publication disappeared")?)? == original,
        "original completed publication changed during registration projection");
    Ok(projected)
}
