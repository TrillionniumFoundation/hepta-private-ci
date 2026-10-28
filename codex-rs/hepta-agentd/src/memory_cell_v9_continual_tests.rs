//! Real continual writes and matched parameter interventions over native RPCs.

use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_runtime_tests::attach;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_training_test_support::trainer;

#[path = "memory_cell_v9_data.rs"]
mod data;
#[path = "memory_cell_v9_fit.rs"]
mod fit;
#[path = "memory_cell_prospective_direct.rs"]
mod direct;
#[path = "memory_cell_v9_structure_tests.rs"]
mod structure;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ChildConfig { representation: String, output_dir: PathBuf }

async fn continual(config: &ChildConfig) -> Value {
    assert!(["catalog","byte"].contains(&config.representation.as_str()) && config.output_dir.is_absolute());
    let training = trainer();
    let code = fit::code_identity(&training);
    let code_digest = code["digest"].as_str().unwrap().parse::<Digest32>().unwrap();
    let fixture = data::load_fixture(&training.qualification_root);
    let owner = ControlFixture::new().await;
    let resolver = TrustedTestResolver::new(&owner);
    let mut release = None;
    let mut runtime = None;
    let mut parents = json!({});
    let mut generation = 0;
    let mut stages = Vec::new();
    for (index, stage) in fixture.stages.iter().enumerate() {
        let directory = config.output_dir.join(format!("stage-{index}"));
        std::fs::create_dir(&directory).unwrap();
        let before = if release.is_some() {
            data::save(&directory.join("BEFORE_OWNER.json"),&serde_json::to_value(owner.snapshot().await).unwrap());
            Some(data::save(&directory.join("before-retention.json"),&data::evaluate(&owner,&data::Reader::Native(&resolver),&stage.retention).await))
        } else { None };
        data::append(&owner,&stage.writes).await;
        let snapshot = owner.snapshot().await;
        let owner_identity = data::save(&directory.join("OWNER_EXPORT.json"),&serde_json::to_value(&snapshot).unwrap());
        let paired = fit::fit(&training,&owner,&config.representation,parents,&directory).await;
        data::save(&directory.join("FIT_LOCK.json"),&json!({"owner_cut":snapshot.owner_cut_digest(),
            "configuration":paired["configuration"],"code_identity":code,"request_digest":paired["request_digest"],
            "future_outcomes_seen":false,"fixture_sha256":data::FIXTURE_SHA}));
        if release.is_none() {
            let first = ReleaseFixture::from_models_with_training_code(&snapshot,
                fit::native(&paired,"zero","semantic"),fit::native(&paired,"zero","procedure"),code_digest);
            fit::set_budget(&first);
            runtime = Some(attach(&owner,&first,&resolver));
            release = Some(first);
            generation = 1;
        } else {
            generation += 1;
            fit::publish(release.as_ref().unwrap(),&snapshot,&paired,"zero",generation,code_digest);
        }
        let released = release.as_ref().unwrap();
        let prefix = data::evaluate(&owner,&data::Reader::Native(&resolver),&stage.prefix).await;
        assert_eq!(prefix["correct"],prefix["queries"],"prefix event reads use current owner facts");
        data::save(&directory.join("completed-prefix.json"),&prefix);
        let mut interventions = Vec::new();
        for (offset, intervention) in ["zero","frozen","trained","clean"].into_iter().enumerate() {
            let publication = if offset == 0 {
                let loaded = released.host.load_current().unwrap();
                json!({"generation":loaded.generation().get(),"bundle_digest":loaded.bundle_digest(),
                    "source_cut":loaded.owner_cut_digest(),"semantic_digest":loaded.semantic().digest().to_string(),
                    "procedure_digest":loaded.procedure().digest().to_string(),"intervention":intervention})
            } else { generation += 1; fit::publish(released,&snapshot,&paired,intervention,generation,code_digest) };
            let loaded = released.host.load_current().unwrap();
            let mut phases = Vec::new();
            for (name,tasks) in [("future",&stage.future),("retention",&stage.retention)] {
                for model in [loaded.semantic(),loaded.procedure()] { model.sleep().unwrap(); }
                let mut batch = data::evaluate(&owner,&data::Reader::Native(&resolver),tasks).await;
                batch["native_cost"] = json!([loaded.semantic().cost().unwrap(),loaded.procedure().cost().unwrap()]);
                phases.push(data::save(&directory.join(format!("{intervention}-{name}.json")),&batch));
            }
            interventions.push(json!({"intervention":intervention,"publication":publication,"phases":phases}));
        }
        // Predetermined continuation policy; evaluation outcomes never select it.
        generation += 1;
        let selected = fit::publish(released,&snapshot,&paired,"trained",generation,code_digest);
        parents = paired["artifacts"]["trained"].clone();
        let stage_report = json!({"stage":index,"id":stage.id,"directory":format!("stage-{index}"),
            "new_records":stage.writes.len()*3,"owner":owner_identity,"before_retention":before,
            "interventions":interventions,"continuation_selection":selected,
            "families":data::family_counts(&stage.future),"training_receipt":paired["receipt"],
            "source_ledger_logical_bytes":data::logical_files(owner.state.identity().layout.cognitive_root()),
            "artifact_owner_logical_bytes":data::logical_files(released.directory.path()),
            "traffic_after_stage":owner.client.traffic_snapshot()});
        data::save(&directory.join("STAGE.json"),&stage_report);
        stages.push(stage_report);
    }
    assert_eq!(fit::code_identity(&training),code);
    let report = json!({"schema":"hepta.memory.v9.continual-child.v1","representation":config.representation,
        "pid":std::process::id(),"code_identity":code,"fixture_sha256":data::FIXTURE_SHA,
        "stages":stages,"actual_training_processes":3,"actual_fit_calls":18,
        "logical_resident_budget_bytes_per_type":fit::RESIDENT_BUDGET,
        "natural_language_addressing_evaluated":false,"final_use_authority_granted":false});
    drop(runtime);
    drop(release);
    drop(resolver);
    owner.finish().await;
    report
}

async fn monitored_child(parent: &Path, representation: &str) -> Value {
    let started = Instant::now();
    let training = trainer();
    let directory = parent.join(representation);
    std::fs::create_dir(&directory).unwrap();
    let temporary = directory.join("runtime");
    std::fs::create_dir(&temporary).unwrap();
    let configuration = ChildConfig { representation:representation.to_string(),output_dir:directory.clone() };
    let config_path = parent.join(format!("{representation}-config.json"));
    data::save(&config_path,&serde_json::to_value(configuration).unwrap());
    let resources = parent.join(format!("{representation}-resources.json"));
    let mut child = tokio::process::Command::new(&training.python)
        .args(["-I","-B"]).arg(training.qualification_root.join("memory-cell-v9/learning/resource_monitor.py"))
        .arg("--output").arg(&resources).arg("--samples").arg(parent.join(format!("{representation}-samples.jsonl")))
        .arg("--root").arg(&directory).args(["--interval-ms","20","--timeout-seconds","600"])
        .arg("--stdout").arg(parent.join(format!("{representation}-stdout.log")))
        .arg("--stderr").arg(parent.join(format!("{representation}-stderr.log")))
        .arg("--").arg(std::env::current_exe().unwrap())
        .args(["--ignored","--exact","memory_cell_v9_continual_tests::memory_cell_v9_continual_child","--nocapture","--test-threads=1"])
        .env("MEMORY_CELL_V9_CHILD_CONFIG",&config_path).env("TMPDIR",temporary)
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::inherit()).kill_on_drop(true).spawn().unwrap();
    let status = match tokio::time::timeout(Duration::from_secs(660),child.wait()).await {
        Ok(status) => status.unwrap(),
        Err(error) => { child.kill().await.unwrap(); let _ = child.wait().await; panic!("monitored child deadline: {error}"); }
    };
    assert!(status.success(),"V9 monitored child failed; inspect preserved logs and resource receipt");
    let raw = std::fs::read(directory.join("CHILD.json")).unwrap();
    let report: Value = serde_json::from_slice(&raw).unwrap();
    let resource_raw = std::fs::read(&resources).unwrap();
    json!({"representation":representation,"directory":representation,"child":report,
        "parent_supervision_wall_ns":started.elapsed().as_nanos(),
        "child_identity":{"bytes":raw.len(),"sha256":Digest32::of_bytes(&raw).to_string()},
        "resource_identity":{"path":resources.file_name().unwrap().to_str().unwrap(),"bytes":resource_raw.len(),"sha256":Digest32::of_bytes(&resource_raw).to_string()}})
}

#[tokio::test]
#[ignore = "actual continual NumPy parameter interventions and native owner RPCs"]
async fn actual_memory_cell_v9_continual_causal_parameter_memory() {
    let started = Instant::now();
    let output = PathBuf::from(std::env::var_os("MEMORY_CELL_V9_CONTINUAL_RECEIPT_PATH").expect("explicit new V9 receipt path"));
    assert!(output.is_absolute() && !output.exists());
    std::fs::create_dir_all(output.parent().unwrap()).unwrap();
    let directory = output.with_extension("artifacts");
    std::fs::create_dir(&directory).unwrap();
    let training = trainer();
    let code = fit::code_identity(&training);
    let protocol_raw = std::fs::read(training.qualification_root.join("memory-cell-v9/learning/PROTOCOL.json")).unwrap();
    let mut protocol_file = std::fs::OpenOptions::new().create_new(true).write(true).open(directory.join("PROTOCOL.json")).unwrap();
    std::io::Write::write_all(&mut protocol_file,&protocol_raw).unwrap();
    protocol_file.sync_all().unwrap();
    data::save(&directory.join("MANIFEST.json"),&json!({"schema":"hepta.memory.v9.continual-lock.v1",
        "code_identity":code,"fixture_sha256":data::FIXTURE_SHA,"representations":["catalog","byte"],
        "interventions":["zero","frozen","trained","clean"],"stages":3,
        "resident_budget_per_type":fit::RESIDENT_BUDGET,"future_outcomes_seen":false}));
    let mut children = Vec::new();
    for representation in ["catalog","byte"] { children.push(monitored_child(&directory,representation).await); }
    assert_eq!(fit::code_identity(&training),code);
    data::save(&output,&json!({"schema":"hepta.memory.v9.actual-continual.v1","fixture_sha256":data::FIXTURE_SHA,
        "artifact_directory":directory.file_name().unwrap().to_str().unwrap(),"code_identity":code,
        "children":children,"actual_training_processes":6,"actual_fit_calls":36,
        "parent_wall_ns_before_final_receipt":started.elapsed().as_nanos(),
        "full_cost_gain_established":false,"independent_domains_are_iid_samples":false}));
    println!("MEMORY_CELL_V9_CONTINUAL_RECEIPT_PATH={}",output.display());
}

#[tokio::test]
#[ignore = "fresh-process child helper, launched only by the actual V9 parent"]
async fn memory_cell_v9_continual_child() {
    let Some(path) = std::env::var_os("MEMORY_CELL_V9_CHILD_CONFIG") else { return; };
    let config: ChildConfig = serde_json::from_slice(&std::fs::read(PathBuf::from(path)).unwrap()).unwrap();
    let report = continual(&config).await;
    data::save(&config.output_dir.join("CHILD.json"),&report);
}
