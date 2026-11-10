use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;

fn matrix(rows: u16, cols: u16, values: &[i64]) -> Vec<u8> {
    let mut bytes = b"HQ24M001".to_vec();
    bytes.extend_from_slice(&rows.to_le_bytes());
    bytes.extend_from_slice(&cols.to_le_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

fn load(root: &Path, diagonal: i64) -> anyhow::Result<LoadedCellTemporalQ24ModelV1> {
    let file = |name, bytes| -> anyhow::Result<File> {
        let path = root.join(name);
        fs::write(&path, bytes)?;
        Ok(File::open(path)?)
    };
    Ok(LoadedCellTemporalQ24ModelV1::open_files(
        CellTemporalQ24ModelFilesV1 {
            encoder: file("encoder", matrix(/*rows*/ 1, /*cols*/ 1, &[codec::Q]))?,
            base: file("base", matrix(/*rows*/ 1, /*cols*/ 1, &[codec::Q]))?,
            diagonal: file("diagonal", matrix(/*rows*/ 1, /*cols*/ 1, &[diagonal]))?,
            heads: file(
                "heads",
                matrix(/*rows*/ 2, /*cols*/ 1, &[codec::Q, -codec::Q]),
            )?,
        },
    )?)
}

fn configured(
    model: &LoadedCellTemporalQ24ModelV1,
) -> anyhow::Result<(CellCompatibilityBundleV1, CellGenerationConfigV2)> {
    let bundle = CellCompatibilityBundleV1 {
        artifact_id: StableId::new("temporal-fixture")?,
        generation: Generation::new(1)?,
        components: model.components().clone(),
        rollback_predecessor: None,
        training_lineage: None,
    };
    let manifest = CellBackendManifestV2 {
        profile: CellTemporalQ24GenerationWorkerV1::PROFILE.into(),
        source_digest: [1; 32],
        bundle_digest: bundle.digest()?.into_array(),
        encoder: Some(bundle.components.encoder.into_array()),
        head: Some(bundle.components.heads.into_array()),
        memory: None,
        world_model: None,
        decoder: None,
        runtime_digest: [6; 32],
        device_digest: [7; 32],
        input_schema: CellTemporalQ24GenerationWorkerV1::input_schema_digest(),
        state_schema: bundle.components.state_schema.into_array(),
        output_schema: bundle.components.output_schema.into_array(),
        learning: CellLearningBindingV2::Frozen {
            weights: model.effective_weights_digest().into_array(),
        },
        evolution: CellEvolutionBindingV2 {
            structure: [16; 32],
            lineage: [17; 32],
            source_dependencies: [18; 32],
            adoption_receipt: [19; 32],
        },
        max_input_bytes: (10 + 8 * model.input_width()) as u32,
        max_state_bytes: model.state_bytes() as u32,
        max_delta_bytes: (10 + 16 * model.output_width()) as u32,
        max_prefix_bytes: 1024,
        max_step_cost_entries: 3,
        max_ack_cost_entries: 1,
    };
    let initial = CellRuntimeSnapshotV2 {
        scope: CellGenerationScopeV2 {
            principal_digest: [20; 32],
            agent_id: "agent".into(),
            cell_id: "prediction".into(),
            run_id: "run".into(),
        },
        manifest_digest: manifest.digest()?,
        generation: 1,
        writer_epoch: 1,
        revision: 0,
        state: model.initial_state(),
        prefix: Vec::new(),
        stopped: false,
    };
    Ok((
        bundle,
        CellGenerationConfigV2 {
            manifest,
            initial,
            source_frontier: [21; 32],
            task_digest: [22; 32],
        },
    ))
}

fn request(
    config: &CellGenerationConfigV2,
    snapshot: &CellRuntimeSnapshotV2,
    id: &str,
) -> CellGenerationRequestV2 {
    let mut input = b"HQ24I001".to_vec();
    input.extend_from_slice(&1_u16.to_le_bytes());
    input.extend_from_slice(&codec::Q.to_le_bytes());
    CellGenerationRequestV2 {
        operation_id: id.into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: snapshot.clone(),
        input,
        admitted_at_micros: 10,
        deadline_micros: 100,
    }
}

fn output(value: i64) -> Vec<u8> {
    let mut bytes = b"HQ24O001".to_vec();
    bytes.extend_from_slice(&1_u16.to_le_bytes());
    bytes.extend_from_slice(&value.to_le_bytes());
    bytes.extend_from_slice(&(-value).to_le_bytes());
    bytes
}

fn open(
    root: &Path,
    config: CellGenerationConfigV2,
) -> anyhow::Result<CellGenerationJournalV2<FileAnchorWitnessStore>> {
    let file = |name| {
        OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(root.join(name))
    };
    let witness = FileAnchorWitnessStore::open(
        file("witness")?,
        JournalScope {
            scope_digest: Digest32::of_bytes(b"temporal-fixture-scope"),
            objective_digest: Digest32::of_bytes(b"objective"),
        },
        Generation::new(1)?,
        /*max_records*/ 128,
    )?;
    Ok(CellGenerationJournalV2::open(
        file("journal")?,
        witness,
        config,
        /*max_records*/ 128,
    )?)
}

#[test]
fn temporal_q24_owner_restores_and_continues_recurrence_then_stop_preserves_state()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = load(root.path(), codec::Q / 2)?;
    let (bundle, config) = configured(&model)?;
    let worker = model.into_worker(&bundle, config.manifest.clone(), Arc::new(|| 11))?;
    let mut owner = open(root.path(), config.clone())?;
    let first = request(&config, owner.snapshot()?, "first");
    owner.admit(first.clone(), /*now_micros*/ 10)?;
    let proposal = worker.execute(&config.manifest, &first, &AtomicBool::new(false))?;
    assert_eq!(proposal.output_delta, output(codec::Q));
    owner.commit(proposal, /*now_micros*/ 11)?;
    let chunk = owner.pending_output()?.unwrap().clone();
    owner.acknowledge(
        chunk,
        [30; 32],
        CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: config.task_digest,
            source_digest: config.manifest.source_digest,
        })?,
    )?;
    let saved = owner.snapshot()?.clone();
    drop(owner);
    drop(worker);
    let mut owner = open(root.path(), config.clone())?;
    assert_eq!(owner.snapshot()?, &saved);
    let worker = load(root.path(), codec::Q / 2)?.into_worker(
        &bundle,
        config.manifest.clone(),
        Arc::new(|| 11),
    )?;
    let second = request(&config, owner.snapshot()?, "second");
    owner.admit(second.clone(), /*now_micros*/ 11)?;
    let proposal = worker.execute(&config.manifest, &second, &AtomicBool::new(false))?;
    assert_eq!(proposal.output_delta, output(3 * codec::Q / 2));
    let receipt = owner.commit(proposal, /*now_micros*/ 11)?;
    assert_eq!(owner.admit(second, /*now_micros*/ 11)?, Some(receipt));
    let chunk = owner.pending_output()?.unwrap().clone();
    owner.acknowledge(
        chunk,
        [31; 32],
        CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: config.task_digest,
            source_digest: config.manifest.source_digest,
        })?,
    )?;
    let before_stop = owner.snapshot()?.state.clone();
    let mut stop = request(&config, owner.snapshot()?, "stop");
    stop.input = b"HQ24STOP".to_vec();
    owner.admit(stop.clone(), /*now_micros*/ 11)?;
    let proposal = worker.execute(&config.manifest, &stop, &AtomicBool::new(false))?;
    assert_eq!(
        (
            proposal.disposition,
            &proposal.successor_state,
            &proposal.output_delta
        ),
        (
            CellGenerationDispositionV2::Stopped,
            &before_stop,
            &Vec::new()
        )
    );
    owner.commit(proposal, /*now_micros*/ 11)?;
    let stopped = owner.snapshot()?.clone();
    drop(owner);
    let owner = open(root.path(), config)?;
    assert_eq!(owner.snapshot()?, &stopped);
    assert_eq!(owner.pending_output()?, None);
    assert_eq!(u64::from_le_bytes(stopped.state[40..48].try_into()?), 2);
    Ok(())
}

#[test]
fn temporal_q24_changed_model_refuses_old_bundle_and_state() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let original = load(root.path(), codec::Q / 2)?;
    let (bundle, config) = configured(&original)?;
    let changed = load(root.path(), codec::Q)?;
    assert!(
        changed
            .into_worker(&bundle, config.manifest.clone(), Arc::new(|| 11))
            .is_err()
    );
    let changed = load(root.path(), codec::Q)?;
    let (changed_bundle, changed_config) = configured(&changed)?;
    let worker = changed.into_worker(
        &changed_bundle,
        changed_config.manifest.clone(),
        Arc::new(|| 11),
    )?;
    let mut old_state = request(&changed_config, &config.initial, "changed-model");
    old_state.predecessor.manifest_digest = changed_config.manifest.digest()?;
    assert_eq!(
        worker.execute(
            &changed_config.manifest,
            &old_state,
            &AtomicBool::new(false)
        ),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    Ok(())
}

#[test]
fn temporal_q24_late_cancelled_and_rejected_work_preserve_state() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = load(root.path(), codec::Q / 2)?;
    let (bundle, config) = configured(&model)?;
    let clock = Arc::new(AtomicU64::new(11));
    let sampled = Arc::clone(&clock);
    let worker = model.into_worker(
        &bundle,
        config.manifest.clone(),
        Arc::new(move || sampled.fetch_add(100, Ordering::SeqCst)),
    )?;
    let request = request(&config, &config.initial, "late");
    let late = worker.execute(&config.manifest, &request, &AtomicBool::new(false))?;
    assert_eq!(
        (late.disposition, late.successor_state, late.output_delta),
        (
            CellGenerationDispositionV2::DeadlineExceeded,
            config.initial.state.clone(),
            Vec::new()
        )
    );
    let worker = load(root.path(), codec::Q / 2)?.into_worker(
        &bundle,
        config.manifest.clone(),
        Arc::new(|| 11),
    )?;
    let cancelled = worker.execute(&config.manifest, &request, &AtomicBool::new(true))?;
    assert_eq!(
        (
            cancelled.disposition,
            cancelled.successor_state,
            cancelled.output_delta
        ),
        (
            CellGenerationDispositionV2::Cancelled,
            config.initial.state.clone(),
            Vec::new()
        )
    );
    let mut invalid = request;
    invalid.input = b"invalid".to_vec();
    let rejected = worker.execute(&config.manifest, &invalid, &AtomicBool::new(false))?;
    assert_eq!(
        (
            rejected.disposition,
            rejected.successor_state,
            rejected.output_delta
        ),
        (
            CellGenerationDispositionV2::Rejected,
            config.initial.state,
            Vec::new()
        )
    );
    Ok(())
}

#[test]
fn q24_factory_selects_temporal_and_rejects_profile_and_genesis_mismatch() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = load(root.path(), codec::Q / 2)?;
    let (bundle, config) = configured(&model)?;
    let files = || -> anyhow::Result<crate::CellQ24BackendFilesV1> {
        Ok(crate::CellQ24BackendFilesV1::Temporal(
            CellTemporalQ24ModelFilesV1 {
                encoder: File::open(root.path().join("encoder"))?,
                base: File::open(root.path().join("base"))?,
                diagonal: File::open(root.path().join("diagonal"))?,
                heads: File::open(root.path().join("heads"))?,
            },
        ))
    };
    let worker = crate::load_cell_q24_backend_v1(files()?, &bundle, &config, Arc::new(|| 11))?;
    assert_eq!(
        worker
            .execute(
                &config.manifest,
                &request(&config, &config.initial, "factory"),
                &AtomicBool::new(false)
            )?
            .output_delta,
        output(codec::Q)
    );
    let mut mismatch = config.clone();
    mismatch.manifest.profile = crate::CellQ24GenerationWorkerV1::PROFILE.into();
    mismatch.initial.manifest_digest = mismatch.manifest.digest()?;
    assert!(matches!(
        crate::load_cell_q24_backend_v1(files()?, &bundle, &mismatch, Arc::new(|| 11)),
        Err(CellGenerationErrorV2::InvalidBinding)
    ));
    let mut mismatch = config.clone();
    mismatch.initial.state[50] = 1;
    assert!(matches!(
        crate::load_cell_q24_backend_v1(files()?, &bundle, &mismatch, Arc::new(|| 11)),
        Err(CellGenerationErrorV2::InvalidBinding)
    ));
    let wrong_files = crate::CellQ24BackendFilesV1::Composed(crate::CellQ24ModelFilesV1 {
        encoder: File::open(root.path().join("encoder"))?,
        base: File::open(root.path().join("base"))?,
        heads: File::open(root.path().join("heads"))?,
        organ_adapter: None,
        cell_adapter: None,
    });
    assert!(matches!(
        crate::load_cell_q24_backend_v1(wrong_files, &bundle, &config, Arc::new(|| 11)),
        Err(CellGenerationErrorV2::InvalidBinding)
    ));
    Ok(())
}
