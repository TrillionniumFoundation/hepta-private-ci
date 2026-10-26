//! Synthetic full-state layouts for owner crash mechanics, never trained science.
use super::*;
use codex_hepta_neuron::CellTrainingCheckpointV7;
use codex_hepta_neuron::TrainedCellHeadV5;
use codex_hepta_neuron::TrainedCellModeV5;
use codex_hepta_neuron::TrainingHandoffBundleV7;

fn tensor(shape: &[usize], values: &[f64]) -> Digest32 {
    let mut bytes = must(serde_json::to_vec(&json!(["<f8", shape])));
    for value in values {
        bytes.extend_from_slice(&value.to_bits().to_le_bytes());
    }
    Digest32::of_bytes(&bytes)
}

pub fn wrap(f: &mut Fixture) -> Result<()> {
    wrap_at(f, 32)
}

pub fn wrap_at(f: &mut Fixture, candidate_step: usize) -> Result<()> {
    let mut manifest: Value = serde_json::from_slice(&fs::read(&f.conversion)?)?;
    let mut baseline_digest = None;
    let mut warmup = std::collections::BTreeMap::new();
    for index in 0..2 {
        let mut checkpoints = Vec::new();
        let mut heads = Vec::new();
        let absolute = if index == 0 { 0 } else { candidate_step };
        let horizon = if index == 0 { 0 } else { 8 };
        let cursor = if absolute == 17 { 1 } else { horizon };
        let bias = (index + 1) as f64 * 0.125;
        for task in report::TASKS {
            for mode in ["linear", "gated"] {
                for seed in report::SEEDS {
                    let cell = format!("{task}-{mode}-seed{seed}");
                    let p = if mode == "linear" { 36 } else { 52 };
                    let mut vector = vec![0.0; 3 * p];
                    let offset = if mode == "linear" { 32 } else { 40 };
                    vector[offset..offset + 4].fill(bias);
                    let metadata = json!({"schema":"hepta.cell-field-training-state.v1",
                "head":{"width":8,"classes":4,"mode":mode,"rank":2,"max_parameters":256},
                "protocol":{"optimizer":"adam","learning_rate":0.02,"l2":0.001,"beta1":0.9,"beta2":0.999,
                    "epsilon":1e-8,"gradient_clip":5.0,"sampler":"full_batch","batch_size":32,
                    "normalization":"l2_times_sqrt_width","intervention":"post-adam-additive-parameter-increment"},
                "bindings":{"protocol_sha256":owner::digest("synthetic optimizer origin").to_string(),"task":task,
                    "head_mode":mode,"seed":seed,"feature_identity":owner::digest("synthetic features").to_string()},
                "contexts":{"current_train":owner::digest("synthetic training").to_string()},"active_context":"current_train",
                "step_count":64+absolute,"sampler_draw_count":0,"external_batch_count":0,
                "rng":{"bit_generator":"PCG64","state":{"state":123,"inc":9},"has_uint32":0,"uinteger":0},
                "parameter_names":if mode=="linear" {json!(["W","b"])} else {json!(["W","a","b","g"])}});
                    let metadata = serde_json::to_vec(&metadata)?;
                    let mut committed = metadata.clone();
                    committed.extend_from_slice(tensor(&[3 * p], &vector).as_array());
                    let state = Digest32::of_bytes(&committed);
                    if index == 0 {
                        warmup.insert(cell.clone(), state);
                    }
                    let original = warmup[&cell];
                    let actions = vec![vec![0.0; p]; horizon];
                    let plan = tensor(
                        &[horizon, p],
                        &actions.iter().flatten().copied().collect::<Vec<_>>(),
                    );
                    let origin = if index == 0 {
                        state
                    } else {
                        owner::digest("synthetic origin24")
                    };
                    let chain = json!({"certificate_chain":[],
                        "receipt_chain":{"count":absolute,"sha256":owner::digest("synthetic receipt accumulator").to_string()},
                        "counters":{"committed_steps":absolute,"plans":0}});
                    let source = serde_json::to_string(
                        &json!({"schema":"hepta.cell-field-controller.v7",
                "authority":"DENY_ALL","production_authority":false,"fixture_scope":"SYNTHETIC; not scientific evidence",
                "contract":{"protocol_sha256":f.inputs.policy.protocol_digest.to_string(),
                    "optimizer_origin_protocol_sha256":owner::digest("synthetic optimizer origin").to_string(),
                    "controller_source_sha256":owner::digest("synthetic controller source").to_string(),
                    "original_warmup_state_sha256":original.to_string(),"registered_steps":32},
                "protocol_sha256":f.inputs.policy.protocol_digest.to_string(),"full_state_sha256":state.to_string(),
                "warmup_step_count":64,"registered_steps":32,"absolute_step":absolute,"plan_origin_step":absolute-cursor,
                "plan_horizon":horizon,"action_cursor":cursor,"resolved_plan_sha256":plan.to_string(),
                "run_status":if absolute==32 {"completed"} else {"active"},"failure_ledger":[],
                "certificate_chain":chain["certificate_chain"],"receipt_chain":chain["receipt_chain"],"counters":chain["counters"],
                "intended_plan_sha256":plan.to_string(),"plan_origin_state_sha256":origin.to_string(),
                "original_warmup_state_sha256":original.to_string()}),
                    )?;
                    let controller = json!({"schema":"hepta.cell-controller-handoff.v7","resume_boundary":"committed-state-with-frozen-plan",
                "protocol_sha256":f.inputs.policy.protocol_digest.to_string(),
                "optimizer_origin_protocol_sha256":owner::digest("synthetic optimizer origin").to_string(),
                "controller_source_sha256":owner::digest("synthetic controller source").to_string(),
                "state_sha256":state.to_string(),"warmup_step_count":64,"registered_steps":32,"absolute_step":absolute,
                "plan_origin_step":absolute-cursor,"plan_horizon":horizon,"action_cursor":cursor,
                "resolved_plan_sha256":plan.to_string(),"intended_plan_sha256":plan.to_string(),
                "plan_origin_state_sha256":origin.to_string(),"original_warmup_state_sha256":original.to_string(),
                "source_controller_sha256":owner::digest(&source).to_string(),"source_controller_json":source,
                "panel_anchors_sha256":owner::digest("synthetic original anchors").to_string(),
                "panel_identity_sha256":owner::digest("synthetic panels").to_string(),
                "controller_config_sha256":owner::digest("synthetic configuration").to_string(),
                "receipt_chain_sha256":Digest32::of_bytes(&serde_json::to_vec(&chain)?).to_string()});
                    checkpoints.push(CellTrainingCheckpointV7::new(
                        owner::id(&cell)?,
                        metadata,
                        vector,
                        serde_json::to_vec(&controller)?,
                        actions,
                    )?);
                    heads.push(TrainedCellHeadV5::new(
                        owner::id(&cell)?,
                        state,
                        owner::digest("synthetic features"),
                        [[0.0; 4]; 8],
                        [bias; 4],
                        if mode == "linear" {
                            TrainedCellModeV5::Linear
                        } else {
                            TrainedCellModeV5::Gated {
                                a: [0.0; 8],
                                g: [0.0; 8],
                            }
                        },
                    )?);
                    let rows = manifest["versions"][index]["heads"]
                        .as_array_mut()
                        .ok_or("heads")?;
                    rows.iter_mut()
                        .find(|row| row["cell_id"] == cell)
                        .ok_or("head")?["training_state_sha256"] = json!(state.to_string());
                }
            }
        }
        let serving = TrainedCellBundleV5::new(
            owner::id(if index == 0 {
                "all12-typed-warmup-v5"
            } else {
                "all12-typed-candidate-v5"
            })?,
            Generation::new(index as u64 + 1)?,
            owner::digest("synthetic encoder"),
            vec![0.0; 384 * 8],
            heads,
        )?;
        let name = if index == 0 {
            "predecessor"
        } else {
            "candidate"
        };
        fs::write(f.parity.join(format!("{name}.bin")), serving.encode())?;
        manifest["versions"][index]["payload_sha256"] = json!(serving.content_digest().to_string());
        let handoff = TrainingHandoffBundleV7::new(
            serving,
            f.inputs.policy.protocol_digest,
            baseline_digest,
            checkpoints,
        )?;
        if index == 0 {
            baseline_digest = Some(handoff.content_digest());
            f.inputs.predecessor = handoff.encode();
        } else {
            f.inputs.candidate = handoff.encode();
        }
    }
    let bytes = serde_json::to_vec_pretty(&manifest)?;
    fs::write(&f.conversion, &bytes)?;
    f.gate["conversion_manifest_sha256"] = json!(Digest32::of_bytes(&bytes).to_string());
    f.inputs.gate_digest = Digest32::of_bytes(&serde_json::to_vec(&f.gate)?);
    if candidate_step == 32 {
        let expected = terminal_review::commitment(&f.inputs, &f.gate)?;
        install_terminal_review(f, expected)?;
    }
    Ok(())
}

pub fn install_terminal_review(f: &mut Fixture, expected: Value) -> Result<()> {
    let digest = Digest32::of_bytes(&serde_json::to_vec(&expected)?);
    let mut converted: Value = serde_json::from_slice(&fs::read(&f.conversion)?)?;
    converted["evaluated_terminal_checkpoints"] = expected;
    let bytes = serde_json::to_vec_pretty(&converted)?;
    fs::write(&f.conversion, &bytes)?;
    f.gate["conversion_manifest_sha256"] = json!(Digest32::of_bytes(&bytes).to_string());
    f.gate["evaluated_terminal_checkpoints_sha256"] = json!(digest.to_string());
    for (path, kind) in [
        (&f.replay, "independent_replay"),
        (&f.statistics, "independent_statistics"),
    ] {
        let mut audit: Value = serde_json::from_slice(&fs::read(path)?)?;
        audit["evaluated_terminal_checkpoints_sha256"] = json!(digest.to_string());
        let bytes = serde_json::to_vec_pretty(&audit)?;
        fs::write(path, &bytes)?;
        f.gate[format!("{kind}_sha256")] = json!(Digest32::of_bytes(&bytes).to_string());
    }
    f.inputs.gate_digest = Digest32::of_bytes(&serde_json::to_vec(&f.gate)?);
    Ok(())
}
