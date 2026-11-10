//! Real composed model bytes/control/CURRENT/journal execution. Signing custody,
//! training and evaluation are explicit fixtures, not production qualification.

use std::fs;
use std::fs::File;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::CellQ24GenerationWorkerV1;
use crate::CellQ24ModelFilesV1;
use crate::LoadedCellQ24ModelV1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::config;
use crate::neuron_generation_current::test_support::request;
use crate::neuron_generation_update_bootstrap::learning_test_decision;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;

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

#[test]
fn q24_rejects_unmapped_bundle_semantics_and_mismatched_effective_weights() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = load(root.path(), /*factor*/ 1)?;
    let baseline = bundle(&model, /*prior*/ None)?;
    let config = configured(&model, &baseline)?;
    for mutate in [
        (|c: &mut CellBundleComponentsV1| c.numeric_profile = d("other"))
            as fn(&mut CellBundleComponentsV1),
        |c| c.composition = d("other"),
        |c| c.state_semantics = d("preserve"),
        |c| c.cell_adapter = None,
        |c| c.encoder = d("other"),
        |c| c.heads = d("other"),
        |c| c.base = d("other"),
    ] {
        let mut changed = baseline.clone();
        mutate(&mut changed.components);
        let mut manifest = config.manifest.clone();
        manifest.bundle_digest = changed.digest()?.into_array();
        assert!(super::validate_manifest_contract(&changed, &manifest).is_err());
    }
    let mut manifest = config.manifest;
    manifest.learning = CellLearningBindingV2::Frozen { weights: [99; 32] };
    assert!(
        model
            .into_worker(&baseline, manifest, Arc::new(|| 11))
            .is_err()
    );
    Ok(())
}

#[test]
fn q24_rejects_trailing_bytes_oversize_shapes_and_out_of_domain_values() -> anyhow::Result<()> {
    let mut trailing = matrix(/*rows*/ 2, /*cols*/ 2, &[Q, 0, 0, Q]);
    trailing.push(0);
    for bytes in [
        trailing,
        matrix(/*rows*/ 65, /*cols*/ 1, &[0]),
        matrix(/*rows*/ 2, /*cols*/ 2, &[i64::MAX, 0, 0, Q]),
    ] {
        let root = tempfile::tempdir()?;
        drop(load(root.path(), /*factor*/ 1)?);
        fs::write(root.path().join("base"), bytes)?;
        let file = |name| File::open(root.path().join(name));
        assert!(
            LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
                base: file("base")?,
                encoder: file("encoder")?,
                heads: file("heads")?,
                organ_adapter: Some(file("organ")?),
                cell_adapter: Some(file("cell")?),
            })
            .is_err()
        );
    }
    let root = tempfile::tempdir()?;
    let model = load(root.path(), /*factor*/ 1)?;
    let bundle = bundle(&model, /*prior*/ None)?;
    let config = configured(&model, &bundle)?;
    let worker = model.into_worker(&bundle, config.manifest.clone(), Arc::new(|| 11))?;
    let mut request = CellGenerationRequestV2 {
        operation_id: "malformed-input".into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: config.initial,
        input: input(),
        admitted_at_micros: 10,
        deadline_micros: 100,
    };
    request.input.push(0);
    let result = worker.execute(&config.manifest, &request, &AtomicBool::new(false))?;
    assert_eq!(
        (result.disposition, result.output_delta),
        (CellGenerationDispositionV2::Rejected, Vec::new())
    );
    request.input = input();
    request.operation_id = "after-terminal-rejection".into();
    request.predecessor.revision = 1;
    assert_eq!(
        worker
            .execute(&config.manifest, &request, &AtomicBool::new(false))?
            .output_delta,
        output(3 * Q / 2)
    );
    Ok(())
}

#[test]
fn q24_cancel_and_expired_completion_commit_no_output_and_keep_measured_cost() -> anyhow::Result<()>
{
    for cancelled in [false, true] {
        let root = tempfile::tempdir()?;
        let model = load(root.path(), /*factor*/ 1)?;
        let bundle = bundle(&model, /*prior*/ None)?;
        let config = configured(&model, &bundle)?;
        let clock = Arc::new(AtomicU64::new(11));
        let source = Arc::clone(&clock);
        let worker = model.into_worker(
            &bundle,
            config.manifest.clone(),
            Arc::new(move || source.fetch_add(100, Ordering::SeqCst)),
        )?;
        let request = CellGenerationRequestV2 {
            operation_id: "terminal-cut".into(),
            task_digest: config.task_digest,
            source_frontier: config.source_frontier,
            predecessor: config.initial,
            input: input(),
            admitted_at_micros: 10,
            deadline_micros: 100,
        };
        let result = worker.execute(&config.manifest, &request, &AtomicBool::new(cancelled))?;
        let expected = if cancelled {
            CellGenerationDispositionV2::Cancelled
        } else {
            CellGenerationDispositionV2::DeadlineExceeded
        };
        assert_eq!(
            (
                result.disposition,
                result.output_delta,
                result.successor_state
            ),
            (expected, Vec::new(), Vec::new())
        );
        assert!(
            serde_json::to_value(&result.cost)?["entries"][0]["metrics"]["wall_micros"].is_number()
        );
    }
    Ok(())
}

fn control(
    path: &Path,
    worker: CellQ24GenerationWorkerV1,
    config: &CellGenerationConfigV2,
) -> anyhow::Result<ControlledCellGenerationPortV2> {
    Ok(ControlledCellGenerationPortV2::spawn(
        DurableInferenceControl::open(path, /*capacity*/ 32)?,
        ControlledCellGenerationConfigV2 {
            scope: config.initial.scope.clone(),
            manifest: config.manifest.clone(),
            worker_generation: config.initial.writer_epoch,
            queue_capacity: 2,
            rpc_timeout: Duration::from_secs(1),
        },
        Arc::new(worker),
        Arc::new(|| 11),
    )?)
}

fn execute_and_read(
    control: &mut ControlledCellGenerationPortV2,
    manifest: &CellBackendManifestV2,
    request: &CellGenerationRequestV2,
) -> anyhow::Result<CellGenerationProposalV2> {
    // Fresh admission starts an independent worker. Read its original durable
    // result without redispatching or changing the request identity.
    assert_eq!(
        control.execute_generation(manifest, request),
        Err(CellGenerationErrorV2::Pending),
    );
    let limit = Instant::now() + Duration::from_secs(5);
    loop {
        anyhow::ensure!(
            Instant::now() < limit,
            "original Q24 admission did not settle within the test deadline"
        );
        if let Some(proposal) = control.read_generation(request)? {
            return Ok(proposal);
        }
        std::thread::sleep(Duration::from_millis(1));
    }
}

#[test]
fn q24_shared_loaded_allocation_keeps_two_cell_journals_and_ack_isolated() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let model = Arc::new(load(root.path(), /*factor*/ 1)?);
    let baseline = bundle(&model, /*prior*/ None)?;
    let first = configured(&model, &baseline)?;
    let mut second = first.clone();
    second.initial.scope.cell_id = "shared-cell-b".into();
    second.initial.scope.run_id = "shared-run-b".into();
    second.task_digest = d("shared-task-b").into_array();
    second.manifest.source_digest = d("shared-source-b").into_array();
    second.initial.manifest_digest = second.manifest.digest()?;
    let worker_a = model.shared_worker(&baseline, first.manifest.clone(), Arc::new(|| 11))?;
    let worker_b = model.shared_worker(&baseline, second.manifest.clone(), Arc::new(|| 11))?;
    assert_eq!(Arc::strong_count(&model), 3);
    let mut wrong = second.manifest.clone();
    wrong.learning = CellLearningBindingV2::Frozen { weights: [99; 32] };
    assert!(
        model
            .shared_worker(&baseline, wrong, Arc::new(|| 11))
            .is_err()
    );
    assert_eq!(Arc::strong_count(&model), 3);
    // Replacing every source path cannot mutate the already shared matrices.
    drop(load(root.path(), /*factor*/ 2)?);
    let fixture_a = Fixture::new(first)?;
    let fixture_b = Fixture::new(second)?;
    let mut control_a = control(
        &root.path().join("control-a"),
        worker_a,
        &fixture_a.old_config,
    )?;
    let mut control_b = control(
        &root.path().join("control-b"),
        worker_b,
        &fixture_b.old_config,
    )?;
    let mut a = fixture_a.old_journal()?;
    let mut b = fixture_b.old_journal()?;
    let mut request_a = request(&a, &fixture_a.old_config, "shared-operation")?;
    let mut request_b = request(&b, &fixture_b.old_config, "shared-operation")?;
    request_a.input = input();
    request_b.input = input();
    assert!(b.admit(request_a.clone(), /*now_micros*/ 10).is_err());
    a.admit(request_a.clone(), /*now_micros*/ 10)?;
    a.commit(
        execute_and_read(&mut control_a, &fixture_a.old_config.manifest, &request_a)?,
        /*now_micros*/ 11,
    )?;
    assert!(b.pending_output()?.is_none());
    b.admit(request_b.clone(), /*now_micros*/ 10)?;
    b.commit(
        execute_and_read(&mut control_b, &fixture_b.old_config.manifest, &request_b)?,
        /*now_micros*/ 11,
    )?;
    let chunk_a = a.pending_output()?.cloned().unwrap();
    let chunk_b = b.pending_output()?.cloned().unwrap();
    assert_eq!(chunk_a.bytes, output(3 * Q / 2));
    assert_eq!(chunk_b.bytes, output(3 * Q / 2));
    let ack_cost = |config: &CellGenerationConfigV2| {
        CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: config.task_digest,
            source_digest: config.manifest.source_digest,
        })
    };
    let before = fixture_b.bytes("old-journal")?;
    assert!(
        b.acknowledge(
            chunk_a.clone(),
            d("cross-cell-ack").into_array(),
            ack_cost(&fixture_b.old_config)?
        )
        .is_err()
    );
    assert_eq!(fixture_b.bytes("old-journal")?, before);
    a.acknowledge(
        chunk_a,
        d("ack-a").into_array(),
        ack_cost(&fixture_a.old_config)?,
    )?;
    a.drain()?;
    drop(a);
    assert!(fixture_a.old_journal()?.is_drained()?);
    drop(b);
    let mut b = fixture_b.old_journal()?;
    assert_eq!(b.pending_output()?, Some(&chunk_b));
    b.acknowledge(
        chunk_b,
        d("ack-b").into_array(),
        ack_cost(&fixture_b.old_config)?,
    )?;
    b.drain()?;
    control_a.shutdown()?;
    control_b.shutdown()?;
    Ok(())
}

#[test]
fn q24_actual_composition_uses_original_publication_next_task_and_cold_readback()
-> anyhow::Result<()> {
    let old_files = tempfile::tempdir()?;
    let new_files = tempfile::tempdir()?;
    let old_model = load(old_files.path(), /*factor*/ 1)?;
    let next_model = load(new_files.path(), /*factor*/ 2)?;
    let baseline = bundle(&old_model, /*prior*/ None)?;
    let candidate = bundle(&next_model, Some(&baseline))?;
    let old_config = configured(&old_model, &baseline)?;
    let mut next_config = configured(&next_model, &candidate)?;
    next_config.initial.scope.run_id = "next-run".into();
    next_config.initial.generation = 2;
    next_config.initial.writer_epoch = 2;
    next_config.task_digest = d("next task").into_array();
    let f = Fixture::new_with_target(old_config, next_config)?;
    let mut old_control = control(
        &old_files.path().join("control"),
        old_model.into_worker(&baseline, f.old_config.manifest.clone(), Arc::new(|| 11))?,
        &f.old_config,
    )?;
    let mut old = f.old_journal()?;
    let mut old_request = request(&old, &f.old_config, "actual-before-update")?;
    old_request.input = input();
    old.admit(old_request.clone(), /*now_micros*/ 10)?;
    old.commit(
        execute_and_read(&mut old_control, &f.old_config.manifest, &old_request)?,
        /*now_micros*/ 11,
    )?;
    let chunk = old.pending_output()?.cloned().unwrap();
    assert_eq!(chunk.bytes, output(3 * Q / 2));
    old.acknowledge(
        chunk,
        d("observed delivery").into_array(),
        CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: f.old_config.task_digest,
            source_digest: f.old_config.manifest.source_digest,
        })?,
    )?;
    old.drain()?;
    old_control.shutdown()?;

    // Only the learning role attestations below are synthetic fixtures.
    let decision = learning_test_decision(&f, baseline, "none")?
        .snapshot()
        .clone();
    let mut coordinator = LearningIterationCoordinatorV1::new(decision.request, decision.owners)?;
    for receipt in decision.receipts.into_iter().take(2) {
        coordinator.record(receipt, 20)?;
    }
    let candidate_digest = candidate.digest()?;
    for observation in [
        LearningIterationObservationV1::Training {
            candidate: Box::new(candidate.clone()),
            steps: 1,
            milliseconds: 1,
            artifact_bytes: 64,
        },
        LearningIterationObservationV1::Evaluation {
            candidate_bundle: candidate_digest,
            evaluation_profile: d("evaluation"),
            disposition: LearningEvaluationDispositionV1::Qualified,
        },
        LearningIterationObservationV1::Proposal {
            candidate_bundle: candidate_digest,
            proposal_id: coordinator.snapshot().request.operation_id.clone(),
            composition_digest: d("proposal composition"),
            disposition: LearningProposalDispositionV1::UpdateCandidates,
        },
    ] {
        coordinator.record(learning_test_receipt(&coordinator, observation), 20)?;
    }
    let operation_id = super::learning_updated_task_operation_id_v1(&coordinator)?.to_string();
    let prepared = crate::prepare_agentd_generation_update_v1(
        f.current.clone(),
        f.authorities()?,
        old,
        f.selection()?,
        f.target_create()?,
        crate::AgentdGenerationUpdateRequestV1 {
            operation_id: operation_id.clone(),
        },
    )?;
    let intent_digest = prepared.intent_digest();
    let signed = f.sign(prepared.final_use_binding())?;
    f.lose_publication_ack();
    assert!(prepared.publish(&signed).is_err());
    let recovery = || -> anyhow::Result<_> {
        Ok(crate::recover_agentd_generation_update_v1(
            f.reopen_current()?,
            f.authorities()?,
            f.selection()?,
            f.target_reopen()?,
            crate::AgentdGenerationUpdateRecoveryV1 {
                operation_id: operation_id.clone(),
                intent_digest,
            },
        )?)
    };
    let mut ready = recovery()?;
    let selected = ready.read_learning_updated_selection(&coordinator, &f.old_config.manifest)?;
    coordinator.record(learning_test_receipt(&coordinator, selected), 20)?;
    let mut next_request = request(&ready.journal, &f.target_config, "actual-after-update")?;
    next_request.input = input();
    assert!(
        ready
            .read_learning_updated_next_use(
                &coordinator,
                &f.old_config.manifest,
                &next_request.intent()?
            )
            .is_err()
    );
    let mut next_control = control(
        &new_files.path().join("control"),
        next_model.into_worker(
            &candidate,
            f.target_config.manifest.clone(),
            Arc::new(|| 11),
        )?,
        &f.target_config,
    )?;
    ready
        .journal
        .admit(next_request.clone(), /*now_micros*/ 10)?;
    let proposal = execute_and_read(&mut next_control, &f.target_config.manifest, &next_request)?;
    ready.journal.commit(proposal.clone(), /*now_micros*/ 11)?;
    assert_eq!(
        ready.journal.pending_output()?.unwrap().bytes,
        output(2 * Q)
    );
    assert_eq!(
        next_control.execute_generation(&f.target_config.manifest, &next_request)?,
        proposal
    );
    let used = ready.read_learning_updated_next_use(
        &coordinator,
        &f.old_config.manifest,
        &next_request.intent()?,
    )?;
    let bytes = f.bytes("target-journal")?;
    drop(ready);
    let recovered = recovery()?;
    assert_eq!(
        recovered.read_learning_updated_next_use(
            &coordinator,
            &f.old_config.manifest,
            &next_request.intent()?
        )?,
        used
    );
    assert_eq!(f.bytes("target-journal")?, bytes);
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    next_control.shutdown()?;
    Ok(())
}

#[path = "cell_composed_q24_candidate_tests.rs"]
mod private_head;
