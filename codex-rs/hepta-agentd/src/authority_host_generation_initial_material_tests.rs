//! Pure, explicit component model/target. Only original native matrix loading
//! and worker definition checks are reused; there is no RuntimeFixture, fake
//! CURRENT, task completion or business outcome in this setup.

use crate::CellQ24FeatureWorkerV1;
use crate::CellQ24GenerationWorkerV1;
use crate::CellQ24ModelFilesV1;
use crate::CircuitTaskSourceInputV1;
use crate::LoadedCellQ24ModelV1;
use crate::circuit_cell::tests::support as cell;
use crate::neuron_generation_current::test_support::config as version_config;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::fs;
use std::fs::File;
use std::path::Path;
use std::sync::Arc;
const Q: i64 = 1 << 24;

pub(super) fn model(
    root: &Path,
) -> anyhow::Result<(
    Arc<LoadedCellQ24ModelV1>,
    CellCompatibilityBundleV1,
    CellDefinitionV1,
)> {
    let matrix = |rows: u16, values: &[i64]| {
        let mut bytes = b"HQ24M001".to_vec();
        bytes.extend_from_slice(&rows.to_le_bytes());
        bytes.extend_from_slice(&2_u16.to_le_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes
    };
    let file = |name, bytes| -> anyhow::Result<File> {
        let path = root.join(name);
        fs::write(&path, bytes)?;
        Ok(File::open(path)?)
    };
    let model = Arc::new(LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
        base: file("base", matrix(/*rows*/ 2, &[Q, 0, 0, Q]))?,
        encoder: file("encoder", matrix(/*rows*/ 2, &[Q, 0, 0, Q]))?,
        heads: file(
            "heads",
            matrix(
                /*rows*/ 10,
                &[Q, 0, 0, Q, 0, 0, 0, 0, 0, 0, Q, 0, 0, Q, 0, 0, 0, 0, 0, 0],
            ),
        )?,
        organ_adapter: None,
        cell_adapter: None,
    })?);
    let bundle = CellCompatibilityBundleV1 {
        artifact_id: StableId::new("selected-candidate")?,
        generation: Generation::new(1)?,
        components: model.components().clone(),
        rollback_predecessor: None,
        training_lineage: None,
    };
    let definition = definition(&model, &bundle)?;
    Ok((model, bundle, definition))
}

pub(super) fn definition(
    model: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
) -> anyhow::Result<CellDefinitionV1> {
    let mut definition = cell::definition();
    let c = model.components();
    definition.bundle_digest = bundle.digest()?;
    definition.state_schema_digest = c.state_schema;
    definition.native.model_digest = c.heads;
    definition.native.normalization_digest = c.normalizer;
    definition.native.generation = bundle.generation;
    definition.candidates[1].kind = CellCandidateKindV1::Action;
    let r = &mut definition.runtime;
    r.generation = bundle.generation;
    r.model_id = bundle.artifact_id.clone();
    r.model_manifest_digest = bundle.digest()?;
    r.encoder_digest = c.encoder;
    r.head_digest = c.heads;
    r.weights_digest = model.effective_weights_digest();
    r.tokenizer_digest = c.tokenizer;
    r.preprocessor_digest = c.normalizer;
    r.normalization_digest = c.normalizer;
    r.quantization_digest = c.numeric_profile;
    r.runtime_digest = CellQ24FeatureWorkerV1::runtime_profile_digest();
    r.native_config_digest = definition.native.digest()?;
    r.calibration.generation = bundle.generation;
    r.resource_envelope.p99_latency_micros = 10_000_000;
    definition.max_queue_age_micros = 10_000_000;
    definition.semantic_digest()?;
    Ok(definition)
}

pub(super) fn configuration(
    model: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
    definition: &CellDefinitionV1,
    source: &CircuitTaskSourceInputV1,
    generation: u64,
) -> anyhow::Result<CellGenerationConfigV2> {
    let mut config = version_config()?;
    let m = &mut config.manifest;
    m.profile = CellQ24GenerationWorkerV1::PROFILE.into();
    m.bundle_digest = bundle.digest()?.into_array();
    m.encoder = Some(bundle.components.encoder.into_array());
    m.head = Some(bundle.components.heads.into_array());
    m.input_schema = CellQ24GenerationWorkerV1::input_schema_digest();
    m.state_schema = bundle.components.state_schema.into_array();
    m.output_schema = bundle.components.output_schema.into_array();
    m.runtime_digest = definition.runtime.runtime_digest.into_array();
    m.device_digest = definition.runtime.device_digest.into_array();
    m.learning = CellLearningBindingV2::Frozen {
        weights: model.effective_weights_digest().into_array(),
    };
    m.max_input_bytes = (10 + 8 * model.input_width()) as u32;
    m.max_state_bytes = 1;
    m.max_delta_bytes = (10 + 16 * model.output_width()) as u32;
    m.max_prefix_bytes = m.max_delta_bytes;
    config.initial.scope = CellGenerationScopeV2 {
        principal_digest: source.scope.principal_digest.into_array(),
        agent_id: source.scope.agent_id.to_string(),
        cell_id: source.scope.cell_id.to_string(),
        run_id: source.scope.run_id.to_string(),
    };
    config.initial.manifest_digest = m.digest()?;
    config.initial.generation = generation;
    config.initial.writer_epoch = generation;
    config.initial.state.clear();
    config.source_frontier = source.source_frontier.into_array();
    config.task_digest = crate::circuit_feature_task_digest_v1(definition, source)?.into_array();
    Ok(config)
}

pub(super) fn load(
    root: &Path,
) -> anyhow::Result<(
    Arc<LoadedCellQ24ModelV1>,
    CellCompatibilityBundleV1,
    CellDefinitionV1,
)> {
    let model = Arc::new(LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
        base: File::open(root.join("base"))?,
        encoder: File::open(root.join("encoder"))?,
        heads: File::open(root.join("heads"))?,
        organ_adapter: None,
        cell_adapter: None,
    })?);
    let bundle = CellCompatibilityBundleV1 {
        artifact_id: StableId::new("selected-candidate")?,
        generation: Generation::new(1)?,
        components: model.components().clone(),
        training_lineage: None,
        rollback_predecessor: None,
    };
    let definition = definition(&model, &bundle)?;
    Ok((model, bundle, definition))
}

pub(super) fn source(agent: &str) -> anyhow::Result<CircuitTaskSourceInputV1> {
    let mut scope = cell::scope("original-initial-component-A");
    scope.agent_id = StableId::new(agent)?;
    let mut observation = b"HQ24I001".to_vec();
    observation.extend_from_slice(&2_u16.to_le_bytes());
    for value in [Q, Q / 4] {
        observation.extend_from_slice(&value.to_le_bytes());
    }
    Ok(CircuitTaskSourceInputV1 {
        scope,
        source_frontier: Digest32::of_bytes(b"initial-component-source"),
        objective_digest: Digest32::of_bytes(b"initial-component-unexecuted-objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"initial-component-ndu"),
        monotonic_micros: 10,
        deadline_micros: 60_000_010,
        observation,
        candidates: cell::definition()
            .candidates
            .iter()
            .map(|candidate| CellCandidateMaskV1 {
                candidate_id: candidate.candidate_id.clone(),
                allowed: true,
            })
            .collect(),
        lease_duration_ms: 60_000,
    })
}
