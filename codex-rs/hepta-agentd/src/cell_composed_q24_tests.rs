//! Real composed model bytes/control/CURRENT/journal execution. Signing custody,
//! training and evaluation are explicit fixtures, not production qualification.

use std::fs;
use std::fs::File;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::CellQ24GenerationWorkerV1;
use crate::CellQ24ModelFilesV1;
use crate::LoadedCellQ24ModelV1;
use crate::neuron_generation_current::test_support::config;

const Q: i64 = 1 << 24;

fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn matrix(rows: u16, cols: u16, values: &[i64]) -> Vec<u8> {
    let mut bytes = b"HQ24M001".to_vec();
    bytes.extend_from_slice(&rows.to_le_bytes());
    bytes.extend_from_slice(&cols.to_le_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

fn adapter(down: &[i64], up: &[i64]) -> Vec<u8> {
    let down = matrix(/*rows*/ 1, /*cols*/ 2, down);
    let mut bytes = b"HQ24A001".to_vec();
    bytes.extend_from_slice(&(down.len() as u16).to_le_bytes());
    bytes.extend_from_slice(&[0, 0]);
    bytes.extend(down);
    bytes.extend(matrix(/*rows*/ 2, /*cols*/ 1, up));
    bytes
}

fn load(root: &Path, factor: i64) -> anyhow::Result<LoadedCellQ24ModelV1> {
    let file = |name, bytes| -> anyhow::Result<File> {
        let path = root.join(name);
        fs::write(&path, bytes)?;
        Ok(File::open(path)?)
    };
    Ok(LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
        base: file("base", matrix(/*rows*/ 2, /*cols*/ 2, &[Q, 0, 0, 2 * Q]))?,
        encoder: file("encoder", matrix(/*rows*/ 2, /*cols*/ 2, &[Q, 0, 0, Q]))?,
        heads: file(
            "heads",
            matrix(
                /*rows*/ 4,
                /*cols*/ 2,
                &[Q, 0, 0, Q, -Q, 0, 0, -Q],
            ),
        )?,
        organ_adapter: Some(file("organ", adapter(&[Q, 0], &[Q, 0]))?),
        cell_adapter: Some(file("cell", adapter(&[0, Q], &[0, factor * Q]))?),
    })?)
}

fn bundle(
    model: &LoadedCellQ24ModelV1,
    prior: Option<&CellCompatibilityBundleV1>,
) -> anyhow::Result<CellCompatibilityBundleV1> {
    Ok(CellCompatibilityBundleV1 {
        artifact_id: StableId::new(if prior.is_some() {
            "q24-candidate"
        } else {
            "q24-baseline"
        })?,
        generation: prior.map_or_else(|| Generation::new(1), |bundle| bundle.generation.next())?,
        components: model.components().clone(),
        rollback_predecessor: prior.map(CellCompatibilityBundleV1::digest).transpose()?,
        training_lineage: prior
            .map(|bundle| {
                Ok::<_, anyhow::Error>(CellTrainingLineageV1 {
                    source_bundle: bundle.digest()?,
                    dataset: d("dataset"),
                    update_rule: d("update"),
                    evaluation_profile: d("evaluation"),
                })
            })
            .transpose()?,
    })
}

fn configured(
    model: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
) -> anyhow::Result<CellGenerationConfigV2> {
    let mut config = config()?;
    let m = &mut config.manifest;
    m.profile = CellQ24GenerationWorkerV1::PROFILE.into();
    m.bundle_digest = bundle.digest()?.into_array();
    m.encoder = Some(bundle.components.encoder.into_array());
    m.head = Some(bundle.components.heads.into_array());
    m.input_schema = CellQ24GenerationWorkerV1::input_schema_digest();
    m.state_schema = bundle.components.state_schema.into_array();
    m.output_schema = bundle.components.output_schema.into_array();
    m.learning = CellLearningBindingV2::Frozen {
        weights: model.effective_weights_digest().into_array(),
    };
    m.max_input_bytes = (10 + 8 * model.input_width()) as u32;
    m.max_state_bytes = 1;
    m.max_delta_bytes = (10 + 16 * model.output_width()) as u32;
    m.max_prefix_bytes = m.max_delta_bytes;
    config.initial.manifest_digest = m.digest()?;
    config.initial.state.clear();
    Ok(config)
}

fn input() -> Vec<u8> {
    let mut bytes = b"HQ24I001".to_vec();
    bytes.extend_from_slice(&2_u16.to_le_bytes());
    bytes.extend_from_slice(&(Q / 2).to_le_bytes());
    bytes.extend_from_slice(&(Q / 2).to_le_bytes());
    bytes
}

fn output(second: i64) -> Vec<u8> {
    let mut bytes = b"HQ24O001".to_vec();
    bytes.extend_from_slice(&2_u16.to_le_bytes());
    for value in [Q, second, -Q, -second] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

#[test]
fn q24_loaded_bytes_survive_path_replacement_and_changed_bytes_need_new_bundle()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = load(root.path(), /*factor*/ 1)?;
    let baseline = bundle(&model, /*prior*/ None)?;
    let config = configured(&model, &baseline)?;
    let worker = model.into_worker(&baseline, config.manifest.clone(), Arc::new(|| 11))?;
    let changed = load(root.path(), /*factor*/ 2)?;
    assert!(
        changed
            .into_worker(&baseline, config.manifest.clone(), Arc::new(|| 11))
            .is_err()
    );
    let request = CellGenerationRequestV2 {
        operation_id: "loaded-original".into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: config.initial,
        input: input(),
        admitted_at_micros: 10,
        deadline_micros: 100,
    };
    let result = worker.execute(&config.manifest, &request, &AtomicBool::new(false))?;
    assert_eq!(
        (
            result.disposition,
            result.output_delta,
            result.successor_state
        ),
        (
            CellGenerationDispositionV2::Stopped,
            output(3 * Q / 2),
            Vec::new()
        )
    );
    Ok(())
}
