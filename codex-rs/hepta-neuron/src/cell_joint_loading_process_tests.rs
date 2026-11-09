//! Real pinned helper and original journal/witness with artificial parameters.
//! These exercise loading provenance and recovery, not trained model quality.

use std::fs::OpenOptions;

use codex_hepta_infer_core::JointTensorPacketV1;
use codex_hepta_infer_core::JointTensorV1;
use codex_hepta_infer_core::JointV4ComponentDigestsV1;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::*;
use crate::CellGenerationConfigV2;
use crate::CellGenerationJournalV2;
use crate::CellGenerationReceiptV2;
use crate::FileAnchorWitnessStore;
use crate::JointGenerationCommandV2;
use crate::JointGenerationDeliveryContractV2;
use crate::JointGenerationInputV2;
use crate::JournalScope;
use crate::verify_joint_v4_loading_receipt_v1;

fn loaded_harness() -> TestResult<(Harness, JointV4ComponentDigestsV1)> {
    let assets = synthetic::assets()?;
    let mut weights = JointTensorPacketV1::decode(&assets.weights)?;
    for (key, value) in [
        ("kind", "joint-generator-weights-v4"),
        ("observation_profile", "owner-prefix-budget-v1"),
        ("text_profile", "utf8-byte256-scalar128-v1"),
        ("media_profile", "ppm-wav16000-y4m4-v1"),
        ("core_state_profile", "persistent-v1"),
        ("inference_profile", "actor-greedy-observed-v1"),
    ] {
        weights.meta.insert(key.into(), value.into());
    }
    // Extend the original fixed synthetic packet to the exact v4 shapes.
    // Zero tensors remain explicit test data, never trained observations.
    for (name, shape) in [
        ("token_encoder.weight", vec![256, 32]),
        ("emissions.text.weight", vec![256, 64]),
        ("emissions.text.bias", vec![256]),
        ("text_recurrent.weight", vec![32, 32]),
        ("text_recurrent.bias", vec![32]),
        ("text_condition.weight", vec![32, 64]),
        ("text_condition.bias", vec![32]),
        ("actor.0.weight", vec![32, 137]),
        ("critic.0.weight", vec![32, 137]),
        ("delivery_critic.0.weight", vec![32, 137]),
    ] {
        weights.tensors.insert(
            name.into(),
            JointTensorV1 {
                data: vec![0.0; shape.iter().product()],
                shape,
            },
        );
    }
    let weights = weights.encode()?;
    let components = crate::inspect_joint_v4_generation_weights_v1(&weights)?
        .components()
        .clone();
    let mut public = JointTensorPacketV1::decode(&assets.public)?;
    public
        .meta
        .insert("kind".into(), "joint-generator-public-v4".into());
    let mut harness = Harness::with_assets(weights, public.encode()?, Arc::new(|| 10))?;
    harness.manifest.profile = JointGenerationProcessWorkerV1::LOADED_PROFILE.into();
    harness.manifest.encoder = Some(harness.worker.loaded_encoder_digest()?);
    harness.manifest.input_schema = JointGenerationProcessWorkerV1::observed_input_schema_digest();
    harness.manifest.state_schema = JointGenerationProcessWorkerV1::observed_state_schema_digest();
    harness.manifest.output_schema =
        JointGenerationProcessWorkerV1::observed_output_schema_digest();
    harness.request.predecessor.manifest_digest = harness.manifest.digest()?;
    harness.request.input = serde_json::to_vec(&JointGenerationInputV2 {
        public_digest: harness.worker.public_digest,
        delivery: JointGenerationDeliveryContractV2 {
            required_mask: 8,
            optional_mask: 7,
            budget_total_micros: harness.request.deadline_micros
                - harness.request.admitted_at_micros,
            task_deadline_micros: harness.request.deadline_micros,
        },
        command: JointGenerationCommandV2::Init {
            seed: 17,
            sampler: JointGenerationSamplerV1::Mean,
        },
    })?;
    Ok((harness, components))
}

#[derive(Clone, Copy)]
enum JournalOpenMode {
    Create,
    Reopen,
}

fn open_journal(
    harness: &Harness,
    config: &CellGenerationConfigV2,
    mode: JournalOpenMode,
) -> TestResult<CellGenerationJournalV2<FileAnchorWitnessStore>> {
    let open = |name: &str| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(matches!(mode, JournalOpenMode::Create))
            .open(harness.directory.0.join(name))
    };
    let witness = FileAnchorWitnessStore::open(
        open("loading-witness")?,
        JournalScope {
            scope_digest: Digest32::from_array(config.initial.manifest_digest),
            objective_digest: Digest32::from_array(config.task_digest),
        },
        Generation::new(config.initial.generation)?,
        /*max_records*/ 128,
    )?;
    Ok(CellGenerationJournalV2::open(
        open("loading-journal")?,
        witness,
        config.clone(),
        /*max_records*/ 128,
    )?)
}

struct LoadedCommit {
    harness: Harness,
    components: JointV4ComponentDigestsV1,
    config: CellGenerationConfigV2,
    receipt: CellGenerationReceiptV2,
}

fn commit_loaded() -> TestResult<LoadedCommit> {
    let (harness, components) = loaded_harness()?;
    let config = CellGenerationConfigV2 {
        manifest: harness.manifest.clone(),
        initial: harness.request.predecessor.clone(),
        source_frontier: harness.request.source_frontier,
        task_digest: harness.request.task_digest,
    };
    let mut journal = open_journal(&harness, &config, JournalOpenMode::Create)?;
    assert_eq!(
        journal.admit(harness.request.clone(), /*now_micros*/ 1)?,
        None
    );
    journal.observe_dispatch_time(harness.request.digest()?, /*observed_at_micros*/ 10)?;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Advanced);
    assert!(!proposal.successor_state.is_empty());
    assert_eq!(proposal.cost.entries().len(), 5);
    let receipt = journal.commit(proposal.clone(), /*now_micros*/ 20)?;
    assert_eq!(receipt.cost, proposal.cost);
    verify_joint_v4_loading_receipt_v1(
        &harness.manifest,
        &components,
        harness.request.task_digest,
        &receipt,
    )?;
    drop(journal);
    Ok(LoadedCommit {
        harness,
        components,
        config,
        receipt,
    })
}

#[test]
fn actual_model_loading_commitment_survives_original_journal_and_witness_reopen() -> TestResult {
    let f = commit_loaded()?;
    let intent = f.harness.request.intent()?;
    let before = fs::read(f.harness.directory.0.join("loading-journal"))?;
    let witness_before = fs::read(f.harness.directory.0.join("loading-witness"))?;
    let mut reopened = open_journal(&f.harness, &f.config, JournalOpenMode::Reopen)?;
    let recovered = reopened
        .receipt_for_intent(&intent)?
        .ok_or("missing committed loading receipt")?;
    assert_eq!(recovered, f.receipt);
    verify_joint_v4_loading_receipt_v1(
        &f.harness.manifest,
        &f.components,
        intent.task_digest,
        &recovered,
    )?;
    // Exact replay exposes the original event; it does not execute another child.
    assert_eq!(
        reopened.admit(f.harness.request.clone(), /*now_micros*/ 30)?,
        Some(recovered)
    );
    let mut wrong_intent = intent;
    wrong_intent.input_digest = [91; 32];
    assert_eq!(
        reopened.receipt_for_intent(&wrong_intent),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(reopened.retained_bytes()?, before);
    assert_eq!(
        fs::read(f.harness.directory.0.join("loading-witness"))?,
        witness_before
    );
    Ok(())
}

#[test]
fn loading_receipt_rejects_cross_model_components_request_runtime_and_task() -> TestResult {
    let f = commit_loaded()?;
    let verify = |manifest: &CellBackendManifestV2,
                  components: &JointV4ComponentDigestsV1,
                  task,
                  receipt: &CellGenerationReceiptV2| {
        verify_joint_v4_loading_receipt_v1(manifest, components, task, receipt)
    };
    for index in 0..13 {
        let mut changed = f.components.clone();
        let different = Digest32::of_bytes(b"foreign component");
        match index {
            0 => changed.base = different,
            1 => changed.organ_adapter = Some(different),
            2 => changed.cell_adapter = Some(different),
            3 => changed.heads = different,
            4 => changed.composition = different,
            5 => changed.encoder = different,
            6 => changed.tokenizer = different,
            7 => changed.normalizer = different,
            8 => changed.calibration = different,
            9 => changed.numeric_profile = different,
            10 => changed.output_schema = different,
            11 => changed.state_schema = different,
            _ => changed.state_semantics = different,
        }
        assert_eq!(
            verify(
                &f.harness.manifest,
                &changed,
                f.config.task_digest,
                &f.receipt
            ),
            Err(CellGenerationErrorV2::InvalidBinding)
        );
    }
    for index in 0..6 {
        let mut changed = f.harness.manifest.clone();
        match index {
            0 => changed.runtime_digest = [92; 32],
            1 => changed.device_digest = [92; 32],
            2 => changed.bundle_digest = [92; 32],
            3 => changed.source_digest = [92; 32],
            4 => changed.learning = CellLearningBindingV2::Frozen { weights: [92; 32] },
            _ => changed.profile = JointGenerationProcessWorkerV1::OBSERVED_PROFILE.into(),
        }
        assert_eq!(
            verify(&changed, &f.components, f.config.task_digest, &f.receipt),
            Err(CellGenerationErrorV2::InvalidBinding)
        );
    }
    let mut changed = f.receipt.clone();
    changed.request_digest = [93; 32];
    assert_eq!(
        verify(
            &f.harness.manifest,
            &f.components,
            f.config.task_digest,
            &changed
        ),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(
        verify(&f.harness.manifest, &f.components, [94; 32], &f.receipt),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    Ok(())
}

#[test]
fn generic_successful_codec_cost_is_not_a_native_loading_receipt() -> TestResult {
    let f = commit_loaded()?;
    for index in 0..4 {
        let mut changed = f.receipt.clone();
        let mut cost = CellTaskCostV2::new(changed.cost.identity())?;
        for mut entry in changed.cost.entries().iter().cloned() {
            if entry.stage == CellCostStageV2::Codec {
                match index {
                    0 => {
                        entry.event_id = Digest32::of_parts(&[
                            b"hepta.joint.child-phase.v1\0",
                            &changed.request_digest,
                            &[0],
                        ])
                        .into_array()
                    }
                    1 => entry.stage = CellCostStageV2::Inference,
                    2 => entry.outcome = CellCostOutcomeV2::Failed,
                    _ => continue,
                }
            }
            cost.record(entry)?;
        }
        changed.cost = cost;
        changed.cost.validate()?;
        assert_eq!(
            verify_joint_v4_loading_receipt_v1(
                &f.harness.manifest,
                &f.components,
                f.config.task_digest,
                &changed
            ),
            Err(CellGenerationErrorV2::InvalidBinding)
        );
    }
    Ok(())
}
