//! Read the same installed owners before native preparation. Training material
//! and the serving Goal retain separate objectives and original physical paths.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_artifacts::*;
use codex_hepta_agent_components::learning_ledger::open_root_review_input;
use codex_hepta_agent_components::learning_ledger::read_root_review_input;
use codex_hepta_agentd::AgentdNeuronGoalScopeV3;
use codex_hepta_agentd::AgentdNeuronScopeIdentityV3;
use codex_hepta_agentd::ParameterServingScopeV1;
use codex_hepta_agentd::PreparedParameterCheckpointV1;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

pub(super) struct OriginalFacts {
    pub indexed: crate::initial_cpu_anchor::CurrentCpuNeuronMaterialProjectionV3,
    pub registration: InstalledCpuSourceV1,
    pub current: RegisteredArtifactCurrentFactsV3,
    pub baseline_id: StableId,
    pub goal_material: NeuronGenerationMaterialV2,
    pub goal_material_source: InstalledCpuSourceV1,
    pub serving: ParameterServingScopeV1,
    pub serving_source: InstalledCpuSourceV1,
    pub checkpoint: PreparedParameterCheckpointV1,
    pub checkpoint_source: InstalledCpuSourceV1,
    pub dataset: dataset_projection::PreparedDataset,
    pub snapshot: InstalledCpuSourceV1,
    pub snapshot_receipt: RegistrySnapshotReceipt,
    pub public: PathBuf,
    pub effects: PathBuf,
    pub search: InstalledCpuSourceV1,
}

pub(super) fn publish(
    directory: &Path,
    name: &str,
    bytes: &[u8],
    maximum: usize,
) -> Result<InstalledCpuSourceV1> {
    super::super::independent_owners::roles::publish_public_source(directory, name, bytes, maximum)
}

fn public_directory(parent: &Path, name: &str) -> Result<PathBuf> {
    execution::protected_directory(parent)?;
    for ancestor in parent.ancestors() {
        ensure!(
            std::fs::symlink_metadata(ancestor)?.mode() & 0o001 != 0,
            "original public Source parent is not traversable"
        );
    }
    let directory = parent.join(name);
    match std::fs::create_dir(&directory) {
        Ok(()) => {
            std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o755))?;
            std::fs::File::open(parent)?.sync_all()?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (),
        Err(error) => return Err(error.into()),
    }
    execution::protected_directory(&directory)?;
    ensure!(
        std::fs::symlink_metadata(&directory)?.permissions().mode() & 0o777 == 0o755,
        "original round public Source custody changed"
    );
    Ok(directory)
}

pub(super) fn current_registration(
    template: &InstalledCpuSourceV1,
    material: &NeuronGenerationMaterialV2,
    subject: &StableId,
    public: &Path,
) -> Result<(InstalledCpuSourceV1, RegisteredArtifactCurrentFactsV3)> {
    let original = read_registered_artifact_manifest_sources_v3(
        &template.path,
        template.digest.parse()?,
        now_ms()?,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let mut manifests = Vec::new();
    for (bytes, admission) in original {
        let pin = Digest32::of_bytes(&bytes);
        let source = publish(
            public,
            &format!("complete-manifest-{pin}.bin"),
            &bytes,
            128 * 1024,
        )?;
        manifests.push((
            ParameterRoleSourceV3 {
                path: source.path,
                digest: source.digest,
            },
            admission,
        ));
    }
    let manifests = manifests
        .try_into()
        .map_err(|_| anyhow::anyhow!("three whole original manifests"))?;
    let bytes = project_registered_artifact_manifest_configuration_v3(
        &template.path,
        template.digest.parse()?,
        &manifests,
        material,
        subject,
        now_ms()?,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let pin = Digest32::of_bytes(&bytes);
    let source = publish(
        public,
        &format!("current-registration-{pin}.json"),
        &bytes,
        64 * 1024,
    )?;
    let facts = inspect_registered_artifact_current_material_v3(
        &source.path,
        pin,
        material,
        subject,
        now_ms()?,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    Ok((source, facts))
}

pub(super) async fn collect(
    blueprint: &blueprint::Blueprint,
    client: &AgentdClient,
    before: &codex_hepta_supervisor::SupervisordAgentStatus,
    agent: &AgentId,
    home_root: &Path,
    round: &AgentdSelfIterationRoundV1,
    execution_directory: &Path,
) -> Result<Option<OriginalFacts>> {
    let subject = StableId::new(agent.as_str())?;
    let indexed = crate::initial_cpu_anchor::read_current_cpu_neuron_material_projection_v3(
        &blueprint.model_resolver,
        &blueprint.initial_material,
        &subject,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (generation, serving, raw_response) = client
        .inspect_parameter_serving_scope_source_v1(round.clone())
        .await?;
    current::validate_runtime_generation(before, generation)?;
    // A newly selected model can legitimately precede the serving switch.
    // This observation cannot turn that ordinary interval into an E verdict.
    if serving.neuron_generation != indexed.identity.generation.get()
        || serving.configuration_digest != indexed.identity.configuration_digest
        || serving.body_bundle_digest != indexed.identity.body_digest
    {
        return Ok(None);
    }
    let goal_material = match serving.goal_ordinal {
        Some(ordinal) => crate::initial_cpu_anchor::project_cpu_neuron_goal_material_v3(
            &indexed.material,
            agent,
            home_root,
            &AgentdNeuronGoalScopeV3 {
                ordinal,
                identity: AgentdNeuronScopeIdentityV3 {
                    model_generation: serving.neuron_generation,
                    subject_scope_digest: serving.scope.scope_digest,
                    objective_digest: serving.scope.objective_digest,
                    runtime_configuration_digest: serving.configuration_digest,
                    body_bundle_digest: serving.body_bundle_digest,
                },
            },
        )
        .map_err(|error| anyhow::anyhow!("{error}"))?,
        None => {
            ensure!(
                serving.scope == indexed.material.scope,
                "original static owner differs from complete training material"
            );
            indexed.material.clone()
        }
    };
    let public = public_directory(
        execution_directory,
        &format!("round-preparation-{}", round.identity_digest()),
    )?;
    let search = search_projection::project(blueprint, &indexed.material, &public)?;
    let effects = public.join("original-effects");
    super::super::independent_owners::roles::prepare_effect_directory(&effects)?;
    let goal_bytes = encode_neuron_generation_material_v2(&goal_material)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let goal_material_source = publish(
        &public,
        "actual-goal-material.json",
        &goal_bytes,
        codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
    )?;
    // Retain one original frame for this actual process generation. Repeated
    // observations have new request IDs; preserve the first frame unchanged
    // while comparing its whole typed facts to the newly authenticated query.
    let response_path = public.join(format!(
        "serving-response-{}-{generation}.bin",
        before
            .spawn_generation
            .context("actual spawn generation absent")?
    ));
    let response_bytes = if response_path.try_exists()? {
        read_root_review_input(
            &response_path,
            codex_hepta_contracts::MAX_ORIGINAL_PARAMETER_SERVING_RESPONSE_BYTES_V1 as u64,
        )
        .map_err(|error| anyhow::anyhow!("{error}"))?
    } else {
        raw_response.clone()
    };
    let retained =
        codex_hepta_contracts::decode_original_parameter_serving_scope_response_v1(&response_bytes)
            .map_err(anyhow::Error::msg)?;
    let live =
        codex_hepta_contracts::decode_original_parameter_serving_scope_response_v1(&raw_response)
            .map_err(anyhow::Error::msg)?;
    ensure!(
        retained.schema_version == live.schema_version
            && retained.agent_id == live.agent_id
            && retained.spawn_generation == live.spawn_generation
            && retained.current_generation == live.current_generation
            && retained.payload == live.payload,
        "retained original Serving frame differs from same current peer facts"
    );
    execution::immutable(
        &response_path,
        &response_bytes,
        codex_hepta_contracts::MAX_ORIGINAL_PARAMETER_SERVING_RESPONSE_BYTES_V1,
    )?;
    let serving_source = InstalledCpuSourceV1 {
        path: response_path,
        digest: Digest32::of_bytes(&response_bytes).to_string(),
    };
    let (checkpoint, checkpoint_source) = checkpoint_projection::collect(
        client,
        before,
        agent,
        round,
        &goal_material,
        &goal_material_source,
        &public,
    )
    .await?;
    checkpoint.checkpoint(&goal_material)?;
    ensure!(
        checkpoint.scope == serving.scope
            && checkpoint.neuron_generation == serving.neuron_generation
            && checkpoint.configuration_digest == serving.configuration_digest
            && checkpoint.body_bundle_digest == serving.body_bundle_digest
            && checkpoint.goal_ordinal == serving.goal_ordinal,
        "same held actual Goal/checkpoint facts changed"
    );
    let template = indexed
        .current_registration_configuration
        .as_ref()
        .unwrap_or(&blueprint.initial_registration);
    let (registration, current) =
        current_registration(template, &indexed.material, &subject, &public)?;
    let (snapshot_path, snapshot_receipt) = current
        .protected_current_registry_source(now_ms()?)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let registry = read_registry_snapshot(
        open_root_review_input(&snapshot_path).map_err(|error| anyhow::anyhow!("{error}"))?,
        snapshot_receipt,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let matching: Vec<_> = [ArtifactKind::Parameters, ArtifactKind::Model]
        .into_iter()
        .flat_map(|kind| {
            registry.eligible_candidates(kind, indexed.material.scope.objective_digest)
        })
        .filter(|manifest| {
            manifest.generation == indexed.material.runtime.generation
                && manifest.content_digest == indexed.material.native.model_digest
                && current
                    .current_view()
                    .eligible_manifest(&manifest.artifact_id)
                    == Some(*manifest)
        })
        .collect();
    ensure!(
        matching.len() == 1,
        "exact original CURRENT numerical baseline is ambiguous or absent"
    );
    let baseline_id = matching[0].artifact_id.clone();
    let snapshot_bytes = read_root_review_input(&snapshot_path, 64 * 1024 * 1024)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    ensure!(
        Digest32::of_bytes(&snapshot_bytes) == snapshot_receipt.file_digest
            && snapshot_bytes.len() == snapshot_receipt.encoded_bytes,
        "whole original CURRENT snapshot Source differs"
    );
    let snapshot = publish(
        &public,
        &format!("registry-{}.bin", snapshot_receipt.file_digest),
        &snapshot_bytes,
        64 * 1024 * 1024,
    )?;
    let Some(dataset) =
        dataset_projection::collect(blueprint, client, before, round, &public, &effects).await?
    else {
        return Ok(None);
    };
    let (generation, after_serving, _) = client
        .inspect_parameter_serving_scope_source_v1(round.clone())
        .await?;
    current::validate_runtime_generation(before, generation)?;
    ensure!(
        serving == after_serving,
        "actual complete Serving scope changed during factual preparation"
    );
    indexed
        .revalidate()
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    current
        .revalidate_current(now_ms()?)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    Ok(Some(OriginalFacts {
        indexed,
        registration,
        current,
        baseline_id,
        goal_material,
        goal_material_source,
        serving,
        serving_source,
        checkpoint,
        checkpoint_source,
        dataset,
        snapshot,
        snapshot_receipt,
        public,
        effects,
        search,
    }))
}
