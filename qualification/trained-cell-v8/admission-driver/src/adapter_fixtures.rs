//! Explicitly synthetic full-format reports under a test-only installed host pin.
//! Reuse the old immutable mechanical fixture; never relabel a real failed study.
use super::*;
use codex_hepta_neuron::CellTrainingCheckpointV7;
use codex_hepta_neuron::TrainingHandoffBundleV7;
use codex_hepta_neuron::TrainingHandoffBundleV8;
use hepta_handoff_recovery_v7::handoff_version::Handoff;
use std::path::PathBuf;

pub struct Study {
    pub fixture: Fixture,
    pub profile: PathBuf,
    pub pin: Digest32,
    pub protocol: PathBuf,
    pub evaluation: PathBuf,
    pub gate: PathBuf,
    pub predecessor: PathBuf,
    pub candidate: PathBuf,
    pub contracts: PathBuf,
}
pub fn write(path: &Path, value: &Value) -> Result<Digest32> {
    let bytes = serde_json::to_vec(value)?;
    fs::write(path, &bytes)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn contract_family(f: &mut Fixture, version: u8) -> Result<Value> {
    let mut contracts = BTreeMap::new();
    let mut predecessor = None;
    let mut conversion: Value = serde_json::from_slice(&read(&f.conversion)?)?;
    for index in 0..2 {
        let bytes = if index == 0 {
            &f.inputs.predecessor
        } else {
            &f.inputs.candidate
        };
        let bundle = TrainingHandoffBundleV7::decode(bytes, Digest32::of_bytes(bytes))?;
        let mut checkpoints = Vec::new();
        for checkpoint in bundle.checkpoints() {
            let mut wrapper: Value = serde_json::from_slice(checkpoint.controller_metadata_json())?;
            let mut source: Value =
                serde_json::from_str(string(&wrapper, "source_controller_json")?)?;
            let contract = source["contract"].as_object_mut().ok_or("contract")?;
            contract.insert(
                "configuration".into(),
                json!({"steps":32,"commit_stride":8,"fixture":"SYNTHETIC"}),
            );
            contract.insert("original_old_anchors".into(), json!([1.0, 1.0, 1.0, 1.0]));
            contract.insert(
                "training_sha256".into(),
                json!(owner::digest("synthetic training").to_string()),
            );
            for name in ["current_panel_sha256", "old_panel_sha256"] {
                contract.insert(name.into(), json!(vec![owner::digest(name).to_string(); 4]));
            }
            if version == 8 {
                v8_fixtures::snapshot(&mut source, &mut wrapper, checkpoint)?;
            }
            contracts.insert(
                checkpoint.cell_id().as_str().to_owned(),
                source["contract"].clone(),
            );
            let contract = &source["contract"];
            for (field, value) in [
                (
                    "controller_config_sha256",
                    contract["configuration"].clone(),
                ),
                (
                    "panel_anchors_sha256",
                    contract["original_old_anchors"].clone(),
                ),
                (
                    "panel_identity_sha256",
                    json!({"training_sha256":contract["training_sha256"],
                    "current_panel_sha256":contract["current_panel_sha256"],"old_panel_sha256":contract["old_panel_sha256"]}),
                ),
            ] {
                wrapper[field] =
                    json!(Digest32::of_bytes(&serde_json::to_vec(&value)?).to_string());
            }
            let source = serde_json::to_string(&source)?;
            wrapper["source_controller_sha256"] =
                json!(Digest32::of_bytes(source.as_bytes()).to_string());
            wrapper["source_controller_json"] = json!(source);
            checkpoints.push(CellTrainingCheckpointV7::new(
                checkpoint.cell_id().clone(),
                checkpoint.state_metadata_json().to_vec(),
                checkpoint.state_vector().to_vec(),
                serde_json::to_vec(&wrapper)?,
                checkpoint.planned_actions().to_vec(),
            )?);
        }
        let rebuilt = if version == 8 {
            Handoff::V8(TrainingHandoffBundleV8::new(
                bundle.serving().clone(),
                bundle.protocol_digest(),
                predecessor,
                checkpoints,
            )?)
        } else {
            Handoff::V7(TrainingHandoffBundleV7::new(
                bundle.serving().clone(),
                bundle.protocol_digest(),
                predecessor,
                checkpoints,
            )?)
        };
        conversion["versions"][index]["handoff_payload_sha256"] =
            json!(rebuilt.content_digest().to_string());
        if index == 0 {
            predecessor = Some(rebuilt.content_digest());
            f.inputs.predecessor = rebuilt.encode();
        } else {
            f.inputs.candidate = rebuilt.encode();
        }
    }
    conversion["scope"] = json!("synthetic-host-profile-mechanics");
    write(&f.conversion, &conversion)?;
    Ok(json!({"schema":"hepta.controller-contract-family.v1",
        "protocol_sha256":f.inputs.policy.protocol_digest.to_string(),"cells":contracts}))
}

pub fn new(task_upper: f64, candidate_step: usize, policy_count: usize) -> Result<Study> {
    new_version(task_upper, candidate_step, policy_count, 7)
}
pub fn new_v8(task_upper: f64, candidate_step: usize) -> Result<Study> {
    new_version(task_upper, candidate_step, 4, 8)
}
fn new_version(
    task_upper: f64,
    candidate_step: usize,
    policy_count: usize,
    version: u8,
) -> Result<Study> {
    let mut f = Fixture::new()?;
    let policies: Vec<_> = if version == 8 {
        ["future_field_h8", "myopic_h1", "loss2_h8", "full_h8"]
            .into_iter()
            .map(str::to_owned)
            .collect()
    } else {
        (0..policy_count)
            .map(|i| format!("synthetic-policy-{i}"))
            .collect()
    };
    let candidate = policies[0].clone();
    f.protocol["mpc"] = json!({"fixture":"synthetic exact-format admission test"});
    f.protocol["models"] = json!(["synthetic"]);
    f.protocol["source_counts"] = json!({"agnews":{"future_test":512,"old_test":512},
        "dbpedia":{"future_test":512,"old_test":512}});
    f.protocol["evaluation"] = json!({"tasks":report::TASKS,"heads":report::HEADS,"seeds":report::SEEDS,
        "splits":["current","future","old"],"family_size":12,"candidate":candidate,
        "policies":policies,"primary_future_baselines":[policies[1],policies[2]],
        "required_completed_policies":[policies[0],policies[1],policies[2]],"required_completed_steps":32,
        "improvement_margin":0.001,"retention_margin":0.0,"max_cpu_ratio":3.0});
    f.inputs.policy.protocol_digest = Digest32::of_bytes(&serde_json::to_vec(&f.protocol)?);
    let mut conversion: Value = serde_json::from_slice(&read(&f.conversion)?)?;
    conversion["protocol_sha256"] = json!(f.inputs.policy.protocol_digest.to_string());
    write(&f.conversion, &conversion)?;
    handoff_fixtures::wrap_at(&mut f, candidate_step)?;
    let contracts_value = contract_family(&mut f, version)?;
    let stream_header = if version == 8 {
        Some(stream_fixtures::build(&f, [3, 5])?)
    } else {
        None
    };
    let contracts = f.root.join("contracts.json");
    let contracts_digest = write(&contracts, &contracts_value)?;
    let profile = f.root.join("host-profile.json");
    let dataset = "{\"scope\":\"SYNTHETIC mechanics only\"}";
    let binding = json!({"training_code_sha256":owner::digest("synthetic controller source").to_string(),
        "runtime_sha256":owner::digest("synthetic runtime").to_string(),
        "source_dataset_sha256":Digest32::of_bytes(dataset.as_bytes()).to_string(),
        "run_seal_sha256":owner::digest("synthetic seal").to_string()});
    let mut profile_value = json!({"schema":"hepta.host-pinned-native-profile.v1","scope":"local-research-only",
        "study_scope":"fresh-independent-confirmation","fixture_scope":"SYNTHETIC test installation only",
        "controller_schema":format!("hepta.cell-field-controller.v{version}"),"candidate_format":format!("hepta.training-handoff-bundle.v{version}"),
        "family":{"tasks":report::TASKS,"heads":report::HEADS,"seeds":report::SEEDS,"steps":32},
        "thresholds":{"task_upper_strict":-0.001,"retention_upper_inclusive":0.0,"total_cpu_ratio_inclusive":3.0},
        "protocol_sha256":f.inputs.policy.protocol_digest.to_string(),"controller_contracts_sha256":contracts_digest.to_string(),
        "evaluation_schema":"hepta.synthetic-exact-format-evaluation.v1","candidate_policy":candidate,
        "conversion_scope":"synthetic-host-profile-mechanics","native_research_review":f.protocol["native_research_review"]});
    for field in profile::BINDINGS {
        profile_value[field] = binding[field].clone();
    }
    if let Some(digest) = stream_header {
        profile_value["parity_header_sha256"] = json!(digest.to_string());
    }
    let pin = write(&profile, &profile_value)?;
    let mut costs = Vec::new();
    let mut predictions = Vec::new();
    let mut completion = Vec::new();
    let mut primary = Vec::new();
    let mut cost_contrasts = Vec::new();
    for task in report::TASKS {
        for head in report::HEADS {
            for (split, baseline, upper) in [
                ("future", policies[1].as_str(), task_upper),
                ("future", policies[2].as_str(), task_upper),
                ("old", "warmup_old", 0.0),
            ] {
                primary.push(json!({"task":task,"head":head,"candidate":candidate,"split":split,"baseline":baseline,
                "threshold":if split=="future" {-0.001} else {0.0},"status":"completed", "source_components":512,
                "source_rows":512,"difference":upper,"upper_bound":upper}));
            }
            cost_contrasts.push(json!({"task":task,"head":head,"candidate":candidate,"baseline":policies[1],
            "status":"completed","threshold":3.0,"cpu_ratio":1.0,"paired_seed_cpu_ratios":[1.0,1.0,1.0]}));
            for seed in report::SEEDS {
                for (i, policy) in policies.iter().enumerate() {
                    let cost = json!({"task":task,"head":head,"seed":seed,"policy":policy,"valid_record":true,
                    "cpu_ns":1000000,"status":"completed","completed_steps":32,"registered_steps":32});
                    costs.push(cost);
                    for split in ["current", "future", "old"] {
                        predictions.push(json!({"task":task,"head":head,
                    "seed":seed,"policy":policy,"split":split,"status":"completed","execution_status":"completed","completed_steps":32}));
                    }
                    if i < 3 {
                        completion.push(json!({"task":task,"head":head,"seed":seed,"policy":policy,
                    "required_steps":32,"status":"completed","completed_steps":32,"criterion_met":true}));
                    }
                }
                predictions.push(json!({"task":task,"head":head,"seed":seed,"policy":"warmup_old","split":"old","status":"completed"}));
            }
        }
    }
    let passed = task_upper < -0.001;
    let report_value = json!({"schema":profile_value["evaluation_schema"],"study_scope":"fresh-independent-confirmation",
        "fixture_scope":"SYNTHETIC metrics; no scientific claims","candidate":candidate,
        "protocol_sha256":f.inputs.policy.protocol_digest.to_string(),"records":predictions,"cost_records":costs,
        "completion_gates":completion,"primary_contrasts":primary,"cost_contrasts":cost_contrasts,
        "registered_fits":12,"registered_policy_outputs":12*policy_count,"candidate_completed_fits":12,
        "census_complete":true,"cost_census_complete":true,"required_completion_met":true,"all_registered_gates_met":passed});
    let evaluation = f.root.join("evaluation.json");
    f.inputs.report_digest = write(&evaluation, &report_value)?;
    let definition = serde_json::to_string(
        &json!({"mpc":f.protocol["mpc"],"models":f.protocol["models"],"evaluation":f.protocol["evaluation"]}),
    )?;
    f.gate["native_profile_sha256"] = json!(pin.to_string());
    f.gate["protocol_sha256"] = json!(f.inputs.policy.protocol_digest.to_string());
    f.gate["report_sha256"] = json!(f.inputs.report_digest.to_string());
    f.gate["candidate_format"] = profile_value["candidate_format"].clone();
    f.gate["candidate_definition_sha256"] =
        json!(Digest32::of_bytes(definition.as_bytes()).to_string());
    f.gate["candidate_definition_json"] = json!(definition);
    f.gate["source_dataset_definition_json"] = json!(dataset);
    f.gate["source_predecessor_bundle_sha256"] =
        json!(owner::digest("synthetic predecessor archive").to_string());
    for field in profile::BINDINGS {
        f.gate[field] = binding[field].clone();
    }
    for field in [
        "census_complete",
        "cost_census_complete",
        "required_completion_met",
    ] {
        f.gate[field] = json!(true);
    }
    f.gate["all_registered_gates_met"] = json!(passed);
    for (i, name) in ["task", "retention", "total_cost"].into_iter().enumerate() {
        let definition = serde_json::to_string(
            &json!({"group":name,"protocol_sha256":f.inputs.policy.protocol_digest.to_string(),
            "frozen_evaluation":f.protocol["evaluation"],"aggregation":"maximum over every registered constituent; no missing values",
            "operator":if i==0 {"strict_less"} else {"less_equal"},"threshold":([-0.001,0.0,3.0][i]),
            "observation_unit":if i==2 {"paired timed seed runs per fixed ratio"} else {"minimum distinct source components among constituent contrasts"}}),
        )?;
        f.gate["comparisons"][name] = json!({"definition_json":definition,
            "comparison_sha256":Digest32::of_bytes(definition.as_bytes()).to_string(),"evidence_sha256":f.inputs.report_digest.to_string(),
            "measurement":{"status":"measured","observations":([512,512,3][i]),"lower_bound":([-710.0,-710.0,0.0][i]),
                "estimate":([task_upper,0.0,1.0][i]),"upper_bound":([task_upper,0.0,1.0][i])}});
    }
    for (path, kind) in [
        (&f.replay, "independent_replay"),
        (&f.statistics, "independent_statistics"),
    ] {
        let mut audit: Value = serde_json::from_slice(&read(path)?)?;
        audit["protocol_sha256"] = json!(f.inputs.policy.protocol_digest.to_string());
        audit["report_sha256"] = json!(f.inputs.report_digest.to_string());
        audit["native_profile_sha256"] = json!(pin.to_string());
        for field in profile::BINDINGS {
            audit[field] = binding[field].clone();
        }
        f.gate[format!("{kind}_sha256")] = json!(write(path, &audit)?.to_string());
    }
    if candidate_step == 32 {
        let terminal = terminal_review::commitment(&f.inputs, &f.gate)?;
        handoff_fixtures::install_terminal_review(&mut f, terminal)?;
    } else {
        f.gate["conversion_manifest_sha256"] =
            json!(Digest32::of_bytes(&read(&f.conversion)?).to_string());
    }
    let protocol = f.root.join("protocol.json");
    write(&protocol, &f.protocol)?;
    let predecessor = f.root.join("predecessor.handoff");
    fs::write(&predecessor, &f.inputs.predecessor)?;
    let candidate_path = f.root.join("candidate.handoff");
    fs::write(&candidate_path, &f.inputs.candidate)?;
    f.gate["predecessor_sha256"] = json!(Digest32::of_bytes(&f.inputs.predecessor).to_string());
    f.gate["candidate_sha256"] = json!(Digest32::of_bytes(&f.inputs.candidate).to_string());
    let gate = f.root.join("gate.json");
    write(&gate, &f.gate)?;
    Ok(Study {
        fixture: f,
        profile,
        pin,
        protocol,
        evaluation,
        gate,
        predecessor,
        candidate: candidate_path,
        contracts,
    })
}
impl Study {
    pub fn paths(&self) -> report::Paths<'_> {
        report::Paths {
            protocol: &self.protocol,
            evaluation: &self.evaluation,
            gate: &self.gate,
            predecessor: &self.predecessor,
            candidate: &self.candidate,
            conversion: &self.fixture.conversion,
            contracts: &self.contracts,
        }
    }
    pub fn load(&self) -> Result<(profile::Profile, report::Loaded)> {
        let profile = profile::Profile::load(&self.profile, self.pin)?;
        let loaded = report::load(&profile, &self.paths())?;
        Ok((profile, loaded))
    }
}
