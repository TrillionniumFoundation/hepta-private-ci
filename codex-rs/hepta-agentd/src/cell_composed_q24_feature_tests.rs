//! Actual Q24 arithmetic through the ordinary Cell prepare/infer/commit path,
//! original durable inference control and independently witnessed Cell state.
//! Definition/calibration and training-source custody are explicit fixtures;
//! these tests do not assert a selected version or a daemon/Root acceptance run.

use std::fs::OpenOptions;

use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24FeatureWorkerV1;

fn feature_model(root: &Path) -> anyhow::Result<LoadedCellQ24ModelV1> {
    // The ordinary sparse Cell admits width >= 5 and at most 20% activity.
    // Construct real five-output model bytes before freezing the baseline;
    // the two-output GenerationV2 fixture is not a valid sparse Cell profile.
    drop(load(root, /*factor*/ 1)?);
    fs::write(
        root.join("heads"),
        matrix(
            /*rows*/ 10,
            /*cols*/ 2,
            &[Q, 0, 0, Q, 0, 0, 0, 0, 0, 0, -Q, 0, 0, -Q, 0, 0, 0, 0, 0, 0],
        ),
    )?;
    private_head::reopen(root)
}

fn definition(
    model: &LoadedCellQ24ModelV1,
    bundle: &CellCompatibilityBundleV1,
) -> anyhow::Result<CellDefinitionV1> {
    let mut definition = crate::circuit_cell::tests::support::definition();
    let c = model.components();
    definition.bundle_digest = bundle.digest()?;
    definition.state_schema_digest = c.state_schema;
    definition.native.model_digest = c.heads;
    definition.native.normalization_digest = c.normalizer;
    definition.native.generation = bundle.generation;
    definition.native.width = model.output_width();
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
    r.input_feature_dimension = model.input_width();
    r.state_width = model.output_width();
    r.calibration.generation = bundle.generation;
    r.resource_envelope.p99_latency_micros = 10_000_000;
    definition.max_queue_age_micros = 10_000_000;
    definition.semantic_digest()?;
    Ok(definition)
}

fn input(definition: &CellDefinitionV1, values: [i64; 2]) -> CellStepInputV1 {
    let mut input = crate::circuit_cell::tests::support::input("actual-q24-task");
    input.deadline_micros = 10_000_000;
    input.observation = b"HQ24I001".to_vec();
    input.observation.extend_from_slice(&2_u16.to_le_bytes());
    for value in values {
        input.observation.extend_from_slice(&value.to_le_bytes());
    }
    input.candidates = definition
        .candidates
        .iter()
        .map(|candidate| CellCandidateMaskV1 {
            candidate_id: candidate.candidate_id.clone(),
            allowed: true,
        })
        .collect();
    input
}

fn journal(
    root: &Path,
    definition: &CellDefinitionV1,
    input: &CellStepInputV1,
) -> anyhow::Result<CellOwnerJournalV1<FileAnchorWitnessStore>> {
    let file = |name| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(root.join(name))
    };
    let witness = FileAnchorWitnessStore::open(
        file("cell.witness")?,
        JournalScope {
            scope_digest: input.scope.digest(),
            objective_digest: input.objective_digest,
        },
        definition.runtime.generation,
        /*max_records*/ 32,
    )?;
    Ok(CellOwnerJournalV1::open(
        file("cell.journal")?,
        witness,
        vec![CellJournalPartitionV1 {
            scope: input.scope.clone(),
            definition: definition.clone(),
            source_frontier: input.source_frontier,
            writer_epoch: 1,
        }],
        /*max_records*/ 32,
    )?)
}

fn serve(
    root: &Path,
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: &CellCompatibilityBundleV1,
    values: [i64; 2],
) -> anyhow::Result<CellDecisionReceiptV1> {
    let definition = definition(&model, bundle)?;
    let input = input(&definition, values);
    let worker = CellQ24FeatureWorkerV1::new(model, bundle, &definition)?;
    let encoder = worker.input_encoder();
    let mut control = ControlledNeuronFeaturePortV1::new(
        DurableInferenceControl::open(root.join("control.journal"), /*capacity*/ 4)?,
        definition.clone(),
        /*worker_generation*/ 1,
        worker,
        Arc::new(|| 11),
    )?;
    let mut journal = journal(root, &definition, &input)?;
    let prepared = prepare_cell_step(
        &definition,
        &journal,
        &encoder,
        input,
        /*now_micros*/ 10,
    )?;
    let inferred = infer_cell_with_clock(prepared, &mut journal, &mut control, || 11)?;
    let proposal = decide_cell(inferred, /*now_micros*/ 12)?;
    Ok(commit_cell_step(
        &mut journal,
        proposal,
        /*now_micros*/ 13,
    )?)
}

#[test]
fn q24_feature_real_trained_rows_execute_in_fresh_ordinary_cell_inputs() -> anyhow::Result<()> {
    let model_root = tempfile::tempdir()?;
    let baseline = Arc::new(feature_model(model_root.path())?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let original_heads = fs::read(model_root.path().join("heads"))?;
    let original_components = baseline.components().clone();
    let values = [Q / 4, Q / 2];
    let before_root = tempfile::tempdir()?;
    let before = serve(before_root.path(), Arc::clone(&baseline), &selected, values)?;
    assert_eq!(
        before.representation.drive_q24,
        vec![Q / 2, 3 * Q / 2, 0, 0, 0]
    );
    assert_eq!(
        before.representation.prediction_q24,
        vec![-Q / 2, -3 * Q / 2, 0, 0, 0]
    );
    let rule = CellQ24SgdRuleV1 {
        epochs: 2,
        learning_rate_q24: Q / 2,
    };
    for (head, target, changed_index) in [
        (CellQ24PrivateHeadV1::Drive { index: 0 }, 2 * Q, 0),
        (CellQ24PrivateHeadV1::Prediction { index: 0 }, 0, 5),
    ] {
        let data = batch(target)?;
        let (plan, _) = plan(Arc::clone(&baseline), &selected, &data, head, rule, "none")?;
        let CellQ24TrainingOutcomeV1::Candidate(candidate) =
            plan.fit(data, rule, &AtomicBool::new(false))?
        else {
            anyhow::bail!("real fixed-row optimizer did not change bytes")
        };
        let CellQ24TrainedCandidateV1 { model, bundle, .. } = *candidate;
        let model = Arc::new(model);
        let expected = predict(&model, &bundle, values, "generation-comparison")?;
        let task_root = tempfile::tempdir()?;
        let actual = serve(task_root.path(), Arc::clone(&model), &bundle, values)?;
        let flat: Vec<_> = actual
            .representation
            .drive_q24
            .iter()
            .chain(&actual.representation.prediction_q24)
            .copied()
            .collect();
        assert_eq!(flat, expected);
        let prior: Vec<_> = before
            .representation
            .drive_q24
            .iter()
            .chain(&before.representation.prediction_q24)
            .copied()
            .collect();
        assert_ne!(flat[changed_index], prior[changed_index]);
        for index in 0..flat.len() {
            if index != changed_index {
                assert_eq!(flat[index], prior[index]);
            }
        }
        assert!(actual.cost.resident_bytes > 0 && actual.cost.transient_allocation_bytes > 0);
        assert_eq!(actual.cost.consumed_input_bytes, 26);
        assert_eq!(actual.cost.truncated_input_bytes, 0);
    }
    assert_eq!(baseline.components(), &original_components);
    assert_eq!(fs::read(model_root.path().join("heads"))?, original_heads);
    Ok(())
}

#[test]
fn q24_feature_original_pending_reopens_control_and_cell_without_native_reexecution()
-> anyhow::Result<()> {
    let model_root = tempfile::tempdir()?;
    let model = Arc::new(feature_model(model_root.path())?);
    let bundle = bundle(&model, /*prior*/ None)?;
    let definition = definition(&model, &bundle)?;
    let input = input(&definition, [Q / 4, Q / 2]);
    let root = tempfile::tempdir()?;
    let worker = CellQ24FeatureWorkerV1::new(Arc::clone(&model), &bundle, &definition)?;
    let encoder = worker.input_encoder();
    let mut control = ControlledNeuronFeaturePortV1::new(
        DurableInferenceControl::open(root.path().join("control.journal"), /*capacity*/ 4)?,
        definition.clone(),
        /*worker_generation*/ 1,
        worker,
        Arc::new(|| 11),
    )?;
    let mut cell = journal(root.path(), &definition, &input)?;
    let prepared = prepare_cell_step(
        &definition,
        &cell,
        &encoder,
        input.clone(),
        /*now_micros*/ 10,
    )?;
    let inferred = infer_cell_with_clock(prepared, &mut cell, &mut control, || 11)?;
    let original = decide_cell(inferred, /*now_micros*/ 12)?.receipt().clone();
    let pending = cell
        .pending_inference(&input.scope)?
        .expect("actual pending Cell admission");
    drop((cell, control));
    let control_bytes = fs::read(root.path().join("control.journal"))?;
    let cell_bytes = fs::read(root.path().join("cell.journal"))?;
    let witness_bytes = fs::read(root.path().join("cell.witness"))?;
    let mut cell = journal(root.path(), &definition, &input)?;
    assert_eq!(cell.pending_inference(&input.scope)?, Some(pending));
    let worker = CellQ24FeatureWorkerV1::new(Arc::clone(&model), &bundle, &definition)?;
    let mut control = ControlledNeuronFeaturePortV1::new(
        DurableInferenceControl::open(root.path().join("control.journal"), /*capacity*/ 4)?,
        definition.clone(),
        /*worker_generation*/ 1,
        worker,
        Arc::new(|| panic!("readback sampled a new native execution clock")),
    )?;
    let mut alias = input.clone();
    alias.observation[10] ^= 1;
    assert!(
        recover_cell_inference(
            &definition,
            &cell,
            &encoder,
            alias,
            &mut control,
            /*now_micros*/ 14
        )
        .is_err()
    );
    let inferred = recover_cell_inference(
        &definition,
        &cell,
        &encoder,
        input.clone(),
        &mut control,
        /*now_micros*/ 14,
    )?;
    assert_eq!(
        fs::read(root.path().join("control.journal"))?,
        control_bytes
    );
    assert_eq!(fs::read(root.path().join("cell.journal"))?, cell_bytes);
    assert_eq!(fs::read(root.path().join("cell.witness"))?, witness_bytes);
    let committed = commit_cell_step(
        &mut cell,
        decide_cell(inferred, /*now_micros*/ 14)?,
        /*now_micros*/ 15,
    )?;
    assert_eq!(committed, original);
    let snapshot = cell.snapshot(&input.scope)?;
    drop(cell);
    let cell = journal(root.path(), &definition, &input)?;
    assert_eq!(cell.snapshot(&input.scope)?, snapshot);
    assert_eq!(
        cell.lookup(
            &input.scope,
            &input.operation_id,
            committed.semantic_request_digest
        )?,
        Some(committed)
    );
    assert!(
        encoder
            .encode(&CellEncodingRequestV1 {
                scope: &input.scope,
                source_frontier: input.source_frontier,
                encoder_digest: definition.runtime.encoder_digest,
                observation: &input.observation,
                checkpoint: snapshot.checkpoint.as_ref(),
            })
            .is_err()
    );
    Ok(())
}

#[test]
fn q24_feature_rejects_changed_material_pins_and_noncanonical_input() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = Arc::new(feature_model(root.path())?);
    let bundle = bundle(&model, /*prior*/ None)?;
    let original = definition(&model, &bundle)?;
    for field in ["weights", "encoder", "runtime", "quantization", "manifest"] {
        let mut changed = original.clone();
        match field {
            "weights" => changed.runtime.weights_digest = d("changed"),
            "encoder" => changed.runtime.encoder_digest = d("changed"),
            "runtime" => changed.runtime.runtime_digest = d("changed"),
            "quantization" => changed.runtime.quantization_digest = d("changed"),
            "manifest" => changed.runtime.model_manifest_digest = d("changed"),
            _ => anyhow::bail!("unknown fixture mutation"),
        }
        assert!(CellQ24FeatureWorkerV1::new(Arc::clone(&model), &bundle, &changed).is_err());
    }
    let encoder = CellQ24FeatureWorkerV1::new(model, &bundle, &original)?.input_encoder();
    let mut input = input(&original, [Q / 4, Q / 2]);
    input.observation.push(0);
    assert!(
        encoder
            .encode(&CellEncodingRequestV1 {
                scope: &input.scope,
                source_frontier: input.source_frontier,
                encoder_digest: original.runtime.encoder_digest,
                observation: &input.observation,
                checkpoint: None,
            })
            .is_err()
    );
    Ok(())
}
