//! Publish complete per-round inputs with the original atomic source writer.
//! This projection creates no generation store, request, signer or admission.
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::intelligence::MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1;
use codex_hepta_agent_components::intelligence::MAX_PARAMETER_PLASTICITY_MATERIAL_BYTES_V1;
use codex_hepta_agent_components::intelligence::encode_canonical_port_input_material_v1;
use codex_hepta_agent_components::intelligence::encode_parameter_plasticity_request_v1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use codex_hepta_neuron::encode_neuron_tick_input_v1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use super::configuration;
use super::execution;
use crate::CpuNeuronRoundMaterialsV3;
use crate::initial_cpu_anchor::InstalledCpuSourceV1;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PublishedRoundRecipeV3 {
    pub schema: String,
    pub round: AgentdSelfIterationRoundV1,
    pub canonical: InstalledCpuSourceV1,
    pub materials: InstalledCpuSourceV1,
    pub plasticity_context: InstalledCpuSourceV1,
}

/// The caller has already joined the original G/O/E and actual current facts.
/// Every complete source is immutable, including the context selected before
/// the first effect. Recovery returns the same slot or refuses changed inputs.
pub(crate) fn publish(
    execution_directory: &Path,
    materials: &CpuNeuronRoundMaterialsV3,
    worker: &InstalledCpuSourceV1,
    context: &InstalledCpuSourceV1,
) -> Result<InstalledCpuSourceV1> {
    materials.with_plan(crate::validate_cpu_neuron_parameter_materials_v2)?;
    ensure!(
        !worker.digest.parse::<Digest32>()?.is_zero(),
        "original Worker pin absent"
    );
    configuration::source(context, 1024 * 1024)?;
    execution::protected_directory(execution_directory)?;
    let round = materials.round();
    let directory =
        execution_directory.join(format!("round-materials-{}", round.identity_digest()));
    match std::fs::create_dir(&directory) {
        Ok(()) => std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o755))?,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error.into()),
    }
    let baseline_bytes = encode_neuron_generation_material_v2(materials.baseline())?;
    let request_bytes = encode_parameter_plasticity_request_v1(materials.request())?;
    let mut candidate_bindings = Vec::new();
    let mut rollback_bindings = Vec::new();
    for candidate in materials.candidates() {
        candidate_bindings.push(serde_json::json!({
            "candidate_id": candidate.candidate_id.as_str(),
            "generation": Digest32::of_bytes(&encode_neuron_generation_material_v2(&candidate.generation)?).to_string(),
            "canary_tick": Digest32::of_bytes(&encode_neuron_tick_input_v1(&candidate.canary_tick)?).to_string(),
            "canary_port": Digest32::of_bytes(&encode_canonical_port_input_material_v1(&candidate.canary_port)?).to_string(),
        }));
        rollback_bindings.push(serde_json::json!({
            "candidate_id": candidate.candidate_id.as_str(),
            "generation": Digest32::of_bytes(&encode_neuron_generation_material_v2(
                materials.rollback_for_candidate(&candidate.candidate_id)?)?).to_string(),
        }));
    }
    // Bind the full round and context first. A crash before later publication
    // cannot turn recovery into a new search window or new context admission.
    let mut binding = serde_json::json!({
        "schema": "hepta.cpu-neuron.round-material-binding.v3",
        "round": round,
        "canonical": Digest32::of_bytes(materials.canonical_envelope().canonical_bytes()).to_string(),
        "execution": codex_hepta_agentd::self_iteration_envelope_digest_v1(materials.execution_envelope()).to_string(),
        "baseline": Digest32::of_bytes(&baseline_bytes).to_string(),
        "request": Digest32::of_bytes(&request_bytes).to_string(),
        "rollback": Digest32::of_bytes(&encode_neuron_generation_material_v2(materials.rollback())?).to_string(),
        "test_plan": materials.with_plan(|plan| plan.test_plan_digest).to_string(),
        "candidates": candidate_bindings,
        "worker": worker,
        "plasticity_context": context,
    });
    if materials.candidates().len() > 1 {
        binding["rollbacks"] = serde_json::Value::Array(rollback_bindings);
    }
    source(
        &directory,
        "binding.json",
        &serde_json::to_vec(&binding)?,
        64 * 1024,
    )?;
    let canonical = source(
        &directory,
        "canonical.json",
        materials.canonical_envelope().canonical_bytes(),
        262_144,
    )?;
    let request = source(
        &directory,
        "parameter-request.json",
        &request_bytes,
        MAX_PARAMETER_PLASTICITY_MATERIAL_BYTES_V1,
    )?;
    let baseline = source(
        &directory,
        "baseline.json",
        &baseline_bytes,
        MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
    )?;
    let rollback = source(
        &directory,
        "rollback.json",
        &encode_neuron_generation_material_v2(materials.rollback())?,
        MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
    )?;
    let mut candidates = Vec::new();
    let mut rollbacks = Vec::new();
    for candidate in materials.candidates() {
        let key = Digest32::of_bytes(candidate.candidate_id.as_str().as_bytes());
        let generation = source(
            &directory,
            &format!("candidate-{key}.json"),
            &encode_neuron_generation_material_v2(&candidate.generation)?,
            MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
        )?;
        let tick = source(
            &directory,
            &format!("canary-tick-{key}.json"),
            &encode_neuron_tick_input_v1(&candidate.canary_tick)?,
            262_144,
        )?;
        let port = source(
            &directory,
            &format!("canary-port-{key}.json"),
            &encode_canonical_port_input_material_v1(&candidate.canary_port)?,
            MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1,
        )?;
        candidates.push(serde_json::json!({
            "candidate_id": candidate.candidate_id.as_str(),
            "generation": generation, "canary_tick": tick, "canary_port": port,
        }));
        if materials.candidates().len() > 1 {
            let generation = source(
                &directory,
                &format!("rollback-{key}.json"),
                &encode_neuron_generation_material_v2(
                    materials.rollback_for_candidate(&candidate.candidate_id)?,
                )?,
                MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
            )?;
            rollbacks.push(serde_json::json!({"candidate_id": candidate.candidate_id.as_str(), "generation": generation}));
        }
    }
    let test_plan = materials.with_plan(|plan| plan.test_plan_digest);
    let mut descriptor = serde_json::json!({
        "schema": "hepta.cpu-neuron.parameter-root-materials.v2",
        "canonical_envelope": canonical, "parameter_request": request,
        "baseline": baseline, "baseline_candidate_id": materials.request().admission.baseline_id.as_str(),
        "test_plan_digest": test_plan.to_string(), "candidates": candidates,
        "rollback": rollback, "worker_program": worker,
    });
    if materials.candidates().len() > 1 {
        descriptor["rollbacks"] = serde_json::Value::Array(rollbacks);
    }
    let descriptor = source(
        &directory,
        "materials.json",
        &serde_json::to_vec(&descriptor)?,
        64 * 1024,
    )?;
    let recipe = PublishedRoundRecipeV3 {
        schema: "hepta.cpu-neuron.round-recipe.v3".into(),
        round: round.clone(),
        canonical,
        materials: descriptor,
        plasticity_context: context.clone(),
    };
    source(
        &directory,
        "recipe.json",
        &serde_json::to_vec(&recipe)?,
        16 * 1024,
    )
}

/// Read the immutable original slot for this exact admitted round. A missing
/// successor never falls back to the initial generation's request or context.
pub(crate) fn retained(
    execution_directory: &Path,
    round: &AgentdSelfIterationRoundV1,
) -> Result<PublishedRoundRecipeV3> {
    execution::protected_directory(execution_directory)?;
    let directory =
        execution_directory.join(format!("round-materials-{}", round.identity_digest()));
    execution::protected_directory(&directory)?;
    let bytes = codex_hepta_supervisor::RootFleetPeerAdmissionV1::read_protected_source(
        &directory.join("recipe.json"),
        16 * 1024,
        /*private*/ false,
    )?;
    let recipe: PublishedRoundRecipeV3 = serde_json::from_slice(&bytes)?;
    ensure!(
        recipe.schema == "hepta.cpu-neuron.round-recipe.v3" && recipe.round == *round,
        "retained recipe differs from the entire original round"
    );
    let canonical = configuration::canonical_policy(&recipe.canonical)?;
    ensure!(
        canonical.digest() == round.canonical_policy_digest(),
        "retained canonical policy differs from the original reservation"
    );
    configuration::source(&recipe.materials, 64 * 1024)?;
    configuration::source(&recipe.plasticity_context, 1024 * 1024)?;
    Ok(recipe)
}

impl super::RootFrozenGeneratorServiceV1 {
    pub(super) fn round_inputs(
        &self,
        scope: &super::AgentScope,
        round: &AgentdSelfIterationRoundV1,
    ) -> Result<(
        InstalledCpuSourceV1,
        codex_hepta_agentd::CanonicalIterationEnvelopeV1,
    )> {
        if let Some(blueprint) = &scope.round_blueprint {
            configuration::source(blueprint, 262_144)?;
            let recipe = retained(&self.configuration.execution_directory, round)?;
            let canonical = configuration::canonical_policy(&recipe.canonical)?;
            Ok((recipe.materials, canonical))
        } else {
            Ok((
                scope.materials.clone(),
                configuration::canonical_policy(&scope.canonical)?,
            ))
        }
    }
}

fn source(
    directory: &Path,
    name: &str,
    bytes: &[u8],
    maximum: usize,
) -> Result<InstalledCpuSourceV1> {
    let path = directory.join(name);
    execution::immutable(&path, bytes, maximum)?;
    Ok(InstalledCpuSourceV1 {
        path,
        digest: Digest32::of_bytes(bytes).to_string(),
    })
}
