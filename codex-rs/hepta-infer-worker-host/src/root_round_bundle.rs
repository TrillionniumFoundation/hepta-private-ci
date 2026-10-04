//! Publish one complete recipe only after the original final admission and S3.
use super::*;
use crate::CpuNeuronRoundMaterialsV3;
use crate::InstalledSelfIterationIndependentOwnersConfigV1;
use crate::evolving_agentd::installed_cycle::InstalledRoundBundleV1;
use crate::evolving_agentd::installed_cycle::PreparedCandidateAdmissionV1;

pub(super) fn publish(
    execution_directory: &Path,
    blueprint: &blueprint::Blueprint,
    materials: &CpuNeuronRoundMaterialsV3,
    context: &InstalledCpuSourceV1,
    candidates: Vec<PreparedCandidateAdmissionV1>,
    rollbacks: Vec<PreparedCandidateAdmissionV1>,
) -> Result<()> {
    let source = recipe::publish(
        execution_directory,
        materials,
        &blueprint.worker_program,
        context,
    )?;
    let recipe_bytes = configuration::source(&source, 16 * 1024)?;
    let original: recipe::PublishedRoundRecipeV3 = serde_json::from_slice(&recipe_bytes)?;
    let directory = source
        .path
        .parent()
        .context("original recipe directory absent")?;
    let protected = CpuNeuronParameterRootMaterialsV2::from_protected_source(
        &original.materials,
        blueprint.worker_program.digest.parse()?,
    )?;
    let client_bytes = configuration::source(&blueprint.independent_client_template, 64 * 1024)?;
    let mut client: InstalledSelfIterationIndependentOwnersConfigV1 =
        serde_json::from_slice(&client_bytes)?;
    ensure!(
        client.learning_trust == blueprint.learning_trust,
        "original client learning trust Source changed"
    );
    client.round_digest = materials.round().identity_digest().to_string();
    client.canonical_policy_digest = materials.canonical_envelope().digest().to_string();
    client.execution_digest = materials.round().execution_envelope_digest().to_string();
    client.materials_digest =
        crate::self_iteration_independent_owner_materials_digest_v1(&protected)?.to_string();
    let client_source = original_facts::publish(
        directory,
        "independent-owner-client.json",
        &serde_json::to_vec(&client)?,
        64 * 1024,
    )?;
    let owner_bytes = configuration::source(&blueprint.independent_owners_template, 64 * 1024)?;
    let mut owner: crate::RootSelfIterationOwnersRoundConfigurationV1 =
        serde_json::from_slice(&owner_bytes)?;
    owner.round_digest = materials.round().identity_digest().to_string();
    owner.client_configuration = client_source.clone();
    owner.materials = original.materials.clone();
    // Each Round retains private consumed effect slots and a separate readable
    // immutable input area, using the existing original directory guards.
    let effects = directory.join("independent-owner-effects");
    super::super::independent_owners::roles::prepare_effect_directory(&effects)?;
    owner.public_source_directory = directory.to_owned();
    owner.consumer_directory = effects.join("consumers");
    owner.evaluation_directory = effects.join("evaluations");
    super::super::independent_owners::roles::prepare_effect_directory(&owner.consumer_directory)?;
    super::super::independent_owners::roles::prepare_effect_directory(&owner.evaluation_directory)?;
    let owner_source = original_facts::publish(
        directory,
        "independent-owner-service.json",
        &serde_json::to_vec(&owner)?,
        64 * 1024,
    )?;
    let checked = crate::RootSelfIterationOwnersRoundConfigurationV1::read(
        &owner_source.path,
        materials.round(),
    )?;
    ensure!(
        serde_json::to_vec(&checked.0)? == serde_json::to_vec(&owner)?,
        "whole installed original owner routing changed"
    );
    InstalledSelfIterationIndependentOwnersV1::from_protected_source(
        &client_source,
        materials.round().clone(),
        &protected,
    )?;
    protected.revalidate_sources()?;
    let rollback = rollbacks
        .first()
        .context("complete exact rollback frontier absent")?
        .clone();
    let mut bundle = InstalledRoundBundleV1 {
        schema: "hepta.installed-round-bundle.v1".into(),
        round: materials.round().clone(),
        materials: original.materials,
        plasticity_context: context.clone(),
        independent_owners: client_source,
        candidates,
        rollback,
        rollbacks,
    };
    bundle.rollback_sources()?;
    if bundle.candidates.len() == 1 {
        bundle.rollbacks.clear();
    }
    ensure!(
        configuration::source(&blueprint.independent_client_template, 64 * 1024)? == client_bytes
            && configuration::source(&blueprint.independent_owners_template, 64 * 1024)?
                == owner_bytes
            && configuration::source(&source, 16 * 1024)? == recipe_bytes,
        "whole original templates or recipe changed before final publication"
    );
    original_facts::publish(
        directory,
        "bundle.json",
        &serde_json::to_vec(&bundle)?,
        crate::local_cpu_parameter_root_materials_v2::MAX_PARAMETER_ROUND_DESCRIPTOR_BYTES_V2 as usize,
    )?;
    Ok(())
}
