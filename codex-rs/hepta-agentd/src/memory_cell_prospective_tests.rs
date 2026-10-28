//! Prospective graph learning is compared with fixed inventories and a
//! lightweight selector on the same completed prefix. All arms run in fresh
//! OS processes. Publication identities in these fixtures are explicit test
//! seams; this experiment does not grant autonomous deployment authority.

use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;

#[path = "memory_cell_prospective_batches.rs"]
mod batches;
#[path = "memory_cell_prospective_direct.rs"]
mod direct;
#[path = "memory_cell_prospective_support.rs"]
mod support;

use support::RoutingMode;
use support::Trial;
use support::write_json;

fn protocol_identity() -> Value {
    let root = codex_utils_cargo_bin::repo_root().unwrap();
    let files: Vec<_> = [
        "codex-rs/hepta-agentd/src/memory_cell_prospective_tests.rs",
        "codex-rs/hepta-agentd/src/memory_cell_prospective_support.rs",
        "codex-rs/hepta-agentd/src/memory_cell_prospective_batches.rs",
        "codex-rs/hepta-agentd/src/memory_cell_prospective_direct.rs",
        "codex-rs/hepta-neuron/src/memory_population.rs",
        "codex-rs/hepta-neuron/src/memory_population_learned.rs",
        "codex-rs/hepta-agentd/src/memory_cell_bundle.rs",
        "qualification/memory-cell-v8/learning/score.py",
        "qualification/memory-cell-v8/learning/evidence.py",
        "qualification/memory-cell-v8/learning/fit_evidence.py",
        "qualification/memory-cell-v8/learning/costs.py",
    ].into_iter().map(|path| json!({"path":path,"sha256":Digest32::of_bytes(&std::fs::read(root.join(path)).unwrap()).to_string()})).collect();
    json!({"schema":"hepta.memory.future-coaccess.v1","source_files":files,
        "training_code_digest":support::code_digest(&crate::memory_cell_training_test_support::trainer()).to_string(),
        "fixed_inventory":[1,2,3,4,5,6,7,8],"new_written_entities":24,
        "prefix":{"tasks":16,"reads_per_task":6,"operation":"current"},
        "selection":{"tasks":4,"reads_per_task":6},"future":{"tasks":12,"reads_per_task":6},
        "retention":{"tasks":4,"reads_per_task":6},"resident_budget_per_type_bytes":16384,
        "selection_rule":"past decision errors, then past complete batch wall, then shard count",
        "weights":{"wrong_future_decision":1000000000,"wall_ns":1,"retained_logical_byte":100,"application_transport_byte":10,"process_peak_rss_byte":1},
        "full_cost_required_but_unavailable":["storage_byte_time_integral","simultaneous_process_rss_byte_time_integral"],
        "source_commit":std::env::var("GITHUB_SHA").ok(),"externally_authored_or_iid":false})
}

async fn execute(trial: &Trial, progress: &Path) -> Value {
    std::fs::create_dir(&trial.output_dir).unwrap();
    let path = trial.output_dir.join("CONFIG.json");
    write_json(&path, &serde_json::to_value(trial).unwrap());
    let started = Instant::now();
    let mut child = tokio::process::Command::new(std::env::current_exe().unwrap())
        .args(["--ignored", "--exact", "memory_cell_prospective_tests::support::memory_cell_trial_child", "--nocapture", "--test-threads=1"])
        .env("MEMORY_CELL_V8_TRIAL_CONFIG", &path)
        .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped()).kill_on_drop(true).spawn().unwrap();
    let child_pid = child.id().unwrap();
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    let finished = async {
        let out = async { let mut raw = Vec::new(); stdout.take(131073).read_to_end(&mut raw).await.unwrap(); raw };
        let err = async { let mut raw = Vec::new(); stderr.take(131073).read_to_end(&mut raw).await.unwrap(); raw };
        let (out, err) = tokio::join!(out, err);
        (child.wait().await.unwrap(), out, err)
    };
    let outcome = tokio::time::timeout(Duration::from_secs(300), finished).await;
    let lifecycle_wall_ns = started.elapsed().as_nanos();
    let (status, stdout, stderr) = match outcome {
        Ok(value) => value,
        Err(error) => {
            child.kill().await.unwrap(); let _ = child.wait().await;
            write_json(progress, &json!({"trial":trial.id,"child_pid":child_pid,"failed":"deadline", "lifecycle_wall_ns":lifecycle_wall_ns}));
            panic!("bounded actual trial exceeded deadline: {error}");
        }
    };
    let execution = json!({"trial":trial.id,"child_pid":child_pid,"parent_pid":std::process::id(),
        "exit_code":status.code(),"lifecycle_wall_ns":lifecycle_wall_ns,
        "stdout_bytes":stdout.len(),"stderr_bytes":stderr.len(),
        "stdout":String::from_utf8_lossy(&stdout),"stderr":String::from_utf8_lossy(&stderr)});
    write_json(progress, &execution);
    assert!(stdout.len() <= 131072 && stderr.len() <= 131072, "bounded child diagnostics");
    assert!(status.success(), "actual trial failed: {execution}");
    let raw = std::fs::read(trial.output_dir.join("TRIAL.json")).unwrap(); assert!(raw.len() <= 16 * 1024 * 1024);
    let mut result: Value = serde_json::from_slice(&raw).unwrap();
    assert_eq!(result["child_pid"], child_pid);
    assert_ne!(child_pid, std::process::id());
    result["parent_execution"] = execution;
    result["raw_trial_sha256"] = json!(Digest32::of_bytes(&raw).to_string());
    result["materialized_trial_logical_bytes"] = json!(std::fs::read_dir(&trial.output_dir).unwrap()
        .map(|entry| entry.unwrap().metadata().unwrap().len()).sum::<u64>());
    result
}

fn select_from_past(arms: &[Value]) -> usize {
    arms.iter().min_by_key(|arm| {
        let past = &arm["evaluations"][0];
        (past["tasks"].as_u64().unwrap() - past["decisions_correct"].as_u64().unwrap(),
            past["socket_and_native_wall_ns"].as_u64().unwrap(), arm["trial"]["count"].as_u64().unwrap())
    }).unwrap()["trial"]["count"].as_u64().unwrap() as usize
}

#[tokio::test]
#[ignore = "actual independent-process NumPy/native/SQLite prospective comparison"]
async fn actual_memory_cell_prospective_learning_future_combinations_and_retention() {
    let output = std::env::var_os("MEMORY_CELL_V8_LEARNING_RECEIPT_PATH").map(PathBuf::from)
        .unwrap_or_else(|| std::env::temp_dir().join(format!("memory-v8-learning-{}.json", std::process::id())));
    assert!(output.is_absolute() && !output.exists());
    std::fs::create_dir_all(output.parent().unwrap()).unwrap();
    let directory = output.with_extension("artifacts"); std::fs::create_dir(&directory).unwrap();
    let protocol = protocol_identity();
    let seed = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos().to_string();
    let manifest = json!({"schema":"hepta.memory.prospective-lock.v1","seed":seed,"protocol":protocol});
    write_json(&directory.join("MANIFEST.json"), &manifest);
    let mut arms = Vec::new();
    let mut cut = None;
    for count in 1..=8 {
        let trial = Trial { id: format!("fixed-{count}"), seed: seed.clone(), count, routing_mode: RoutingMode::Fixed,
            resident_budget_bytes: 16_384, expected_source_cut: cut.clone(), output_dir: directory.join(format!("fixed-{count}")) };
        let result = execute(&trial, &directory.join(format!("fixed-{count}-execution.json"))).await;
        cut = Some(result["source_cut"].as_str().unwrap().to_string());
        arms.push(result);
    }
    let selection_started = Instant::now();
    let selected_count = select_from_past(&arms);
    // The complete selector input is retained. No future or retention outcome
    // appears in this input; the same choice is used by both active policies.
    let selector_input: Vec<_> = arms.iter().map(|arm| json!({"count":arm["trial"]["count"],"selection":arm["evaluations"][0]})).collect();
    write_json(&directory.join("SELECTION_LOCK.json"), &json!({"selected_count":selected_count,"input":selector_input,
        "fixed_inventory_selection_search_is_charged":true,"future_outcomes_are_selector_input":false}));
    let selector_wall_ns = selection_started.elapsed().as_nanos();
    for (id, mode) in [("lightweight-prefix-selector", RoutingMode::Fixed), ("learned-coaccess", RoutingMode::Learned), ("direct-owner", RoutingMode::DirectOwner)] {
        let trial = Trial { id: id.to_string(), seed: seed.clone(), count: selected_count, routing_mode: mode,
            resident_budget_bytes: 16_384, expected_source_cut: cut.clone(), output_dir: directory.join(id) };
        arms.push(execute(&trial, &directory.join(format!("{id}-execution.json"))).await);
    }
    assert_eq!(protocol_identity(), protocol, "model, protocol and source stayed frozen");
    let mut future_ids = None;
    for arm in &arms {
        assert_eq!(arm["source_cut"].as_str(), cut.as_deref());
        assert_eq!(arm["evaluations"][1]["phase"], "future");
        assert_eq!(arm["evaluations"][2]["phase"], "retention");
        let ids: Vec<_> = arm["evaluations"][1]["records"].as_array().unwrap().iter()
            .map(|record| record["request_digest"].clone()).collect();
        if let Some(expected) = &future_ids { assert_eq!(&ids, expected); } else { future_ids = Some(ids); }
    }
    let report = json!({"schema":"hepta.memory.v8.actual-prospective-comparison.v1", "manifest":manifest,
        "source_cut":cut,"selected_count_from_prefix":selected_count,"arms":arms,
        "selector_wall_ns":selector_wall_ns,
        "future_requests_identical_across_arms":true,"fresh_process_per_arm":true,
        "total_actual_trials":11,"completed_native_future_evaluations":true,
        "population_risk_established":false,"general_memory_emergence_established":false,
        "full_cost_gate":"not_established","automatic_proposal_or_release_authority":false});
    write_json(&output, &report);
    println!("MEMORY_CELL_V8_LEARNING_RECEIPT_PATH={}", output.display());
}

#[test]
fn memory_cell_prefix_selector_is_unchanged_by_future_answer_or_cost_poisoning() {
    let mut arms = vec![json!({"trial":{"count":2},"evaluations":[{"tasks":4,"decisions_correct":4,"socket_and_native_wall_ns":20},
        {"decisions_correct":0,"socket_and_native_wall_ns":999}]}),
        json!({"trial":{"count":4},"evaluations":[{"tasks":4,"decisions_correct":4,"socket_and_native_wall_ns":10},
        {"decisions_correct":0,"socket_and_native_wall_ns":999}]})];
    let before = select_from_past(&arms);
    arms[0]["evaluations"][1] = json!({"decisions_correct":100000,"socket_and_native_wall_ns":0});
    arms[1]["evaluations"][1] = json!({"decisions_correct":0,"socket_and_native_wall_ns":u64::MAX});
    assert_eq!(select_from_past(&arms), before);
}
