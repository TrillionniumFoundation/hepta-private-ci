//! Complete prospective structural inventory through signed releases and RPCs.

use std::collections::BTreeMap;
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

use super::data;
use super::direct;

#[path = "memory_cell_v9_structure_gate.rs"]
mod gate;
#[path = "memory_cell_v9_structure_support.rs"]
mod support;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ChildConfig {
    output_dir: PathBuf,
    runtime_root: PathBuf,
}

async fn run(config: &ChildConfig) -> Value {
    assert_eq!(std::env::temp_dir(), config.runtime_root);
    let training = trainer();
    let code = support::code(&training);
    let code_digest: Digest32 = code["digest"].as_str().unwrap().parse().unwrap();
    let fixture = data::load_fixture(&training.qualification_root);
    let owner = ControlFixture::new().await;
    assert!(
        owner
            .state
            .identity()
            .layout
            .cognitive_root()
            .starts_with(&config.runtime_root)
    );
    let resolver = TrustedTestResolver::new(&owner);
    let mut release = None;
    let mut runtime = None;
    let mut generation = 0;
    let mut reports = Vec::new();
    let mut fit_calls = 0;
    for (index, stage) in fixture.stages.iter().enumerate() {
        let directory = config.output_dir.join(format!("stage-{index}"));
        std::fs::create_dir(&directory).unwrap();
        data::append(&owner, &stage.writes).await;
        let snapshot = owner.snapshot().await;
        let owner_identity = data::save(
            &directory.join("OWNER_EXPORT.json"),
            &serde_json::to_value(&snapshot).unwrap(),
        );
        let baseline = support::train(
            &training,
            &snapshot,
            2,
            None,
            &directory.join("fixed-2"),
            &code,
        )
        .await;
        if release.is_none() {
            let first = ReleaseFixture::from_populations_with_training_code(
                &snapshot,
                support::native(&baseline, "semantic"),
                support::native(&baseline, "procedure"),
                code_digest,
            );
            support::budget(&first);
            runtime = Some(attach(&owner, &first, &resolver));
            release = Some(first);
            generation = 1;
        } else {
            generation += 1;
            support::publish(
                release.as_ref().unwrap(),
                &snapshot,
                &baseline,
                generation,
                code_digest,
            );
        }
        let released = release.as_ref().unwrap();
        assert!(released.directory.path().starts_with(&config.runtime_root));
        let prefix_publication = {
            let loaded = released.host.load_current().unwrap();
            json!({"generation":loaded.generation().get(),"bundle_digest":loaded.bundle_digest(),
                "semantic_digest":loaded.semantic().digest().to_string(),"procedure_digest":loaded.procedure().digest().to_string()})
        };
        let prefix = data::evaluate(&owner, &data::Reader::Native(&resolver), &stage.prefix).await;
        assert_eq!(prefix["correct"], prefix["queries"]);
        data::save(&directory.join("completed-prefix.json"), &prefix);
        let selection = support::select(
            &training,
            &snapshot,
            &prefix,
            &directory.join("selection"),
            &code,
        )
        .await;
        let learned_count = selection["selected"]["learned"].as_u64().unwrap() as usize;
        let light_count = selection["selected"]["fixed"].as_u64().unwrap() as usize;
        data::save(
            &directory.join("SELECT_LOCK.json"),
            &json!({"source_cut":snapshot.owner_cut_digest(),
            "code_identity":code,"selection_request_digest":selection["request_digest"],"selected":selection["selected"],
            "trace_digest":selection["trace"]["trace_digest"],"future_outcomes_seen":false}),
        );
        let mut fixed = BTreeMap::new();
        fixed.insert(2, baseline);
        for count in [1, 3, 4, 5, 6, 7, 8] {
            let candidate = support::train(
                &training,
                &snapshot,
                count,
                None,
                &directory.join(format!("fixed-{count}")),
                &code,
            )
            .await;
            fixed.insert(count, candidate);
        }
        let learned = support::train(
            &training,
            &snapshot,
            learned_count,
            Some(&selection["trace"]),
            &directory.join("learned"),
            &code,
        )
        .await;
        fit_calls += 72 + 2 * learned_count;
        let mut roles = Vec::new();
        for count in 1..=8 {
            generation += 1;
            let publication =
                support::publish(released, &snapshot, &fixed[&count], generation, code_digest);
            roles.push(
                support::evaluate(
                    &owner,
                    &resolver,
                    released,
                    stage,
                    &directory,
                    &format!("fixed-{count}"),
                    &format!("fixed-{count}"),
                    publication,
                    count,
                )
                .await,
            );
        }
        for (role, fit_directory, candidate, count) in [
            (
                "prefix-selected-fixed",
                format!("fixed-{light_count}"),
                &fixed[&light_count],
                light_count,
            ),
            (
                "prefix-selected-learned",
                "learned".to_string(),
                &learned,
                learned_count,
            ),
        ] {
            generation += 1;
            let publication =
                support::publish(released, &snapshot, candidate, generation, code_digest);
            roles.push(
                support::evaluate(
                    &owner,
                    &resolver,
                    released,
                    stage,
                    &directory,
                    role,
                    &fit_directory,
                    publication,
                    count,
                )
                .await,
            );
        }
        let (direct_owner, acquisition) =
            direct::DirectOwner::acquire(&owner, 2 * support::BUDGET).await;
        data::save(
            &directory.join("direct-owner-acquisition.json"),
            &acquisition,
        );
        let mut phases = Vec::new();
        for (phase, tasks) in [("future", &stage.future), ("retention", &stage.retention)] {
            let batch = data::evaluate(&owner, &data::Reader::Direct(&direct_owner), tasks).await;
            assert_eq!(batch["correct"], batch["queries"]);
            let identity = data::save(
                &directory.join(format!("direct-owner-{phase}.json")),
                &batch,
            );
            phases.push(json!({"identity":identity,"queries":batch["queries"],"correct":batch["correct"],
                "tasks":batch["tasks"],"decisions_correct":batch["decisions_correct"],"wall_ns":batch["wall_ns"],"traffic":batch["traffic"]}));
        }
        roles.push(json!({"role":"direct-owner","publication":{"mode":"direct_owner"},"shards":0,
            "phases":phases,"logical_cache_bytes":direct_owner.logical_cache_bytes,"acquisition":acquisition}));
        drop(direct_owner);
        // Leave the measured fixed baseline selected for the production gate.
        generation += 1;
        let publication =
            support::publish(released, &snapshot, &fixed[&2], generation, code_digest);
        roles.push(
            support::evaluate(
                &owner,
                &resolver,
                released,
                stage,
                &directory,
                "keep-fixed-2",
                "fixed-2",
                publication,
                2,
            )
            .await,
        );
        let source_bytes = data::logical_files(owner.state.identity().layout.cognitive_root());
        let gate = gate::evaluate(
            released,
            &snapshot,
            stage,
            &roles,
            &directory,
            code_digest,
            source_bytes,
        );
        let report = json!({"stage":index,"id":stage.id,"directory":format!("stage-{index}"),"owner":owner_identity,
            "prefix_publication":prefix_publication,"selection":selection,"roles":roles,"structure_gate":gate,
            "actual_training_processes":9,"actual_selection_processes":1,"actual_fit_calls":72+2*learned_count,
            "source_ledger_path":owner.state.identity().layout.cognitive_root(),"artifact_owner_path":released.directory.path(),
            "source_ledger_logical_bytes":source_bytes,"artifact_owner_logical_bytes":data::logical_files(released.directory.path()),
            "traffic_after_stage":owner.client.traffic_snapshot()});
        data::save(&directory.join("STAGE.json"), &report);
        reports.push(report);
    }
    assert_eq!(support::code(&training), code);
    let report = json!({"schema":"hepta.memory.v9.structure-child.v1","pid":std::process::id(),"runtime_root":config.runtime_root,"stages":reports,
        "code_identity":code,"fixture_sha256":data::FIXTURE_SHA,"actual_training_processes":27,
        "actual_selection_processes":3,"actual_fit_calls":fit_calls,"full_cost_gain_established":false,
        "natural_language_addressing_evaluated":false,"publication_authority_granted":false});
    drop(runtime);
    drop(release);
    drop(resolver);
    owner.finish().await;
    report
}

#[tokio::test]
#[ignore = "all fixed structures, observed specialization and native budget/action gate"]
async fn actual_memory_cell_v9_observed_structure_budget_and_actions() {
    let started = Instant::now();
    let output = PathBuf::from(
        std::env::var_os("MEMORY_CELL_V9_STRUCTURE_RECEIPT_PATH")
            .expect("explicit new structure output"),
    );
    assert!(output.is_absolute() && !output.exists());
    std::fs::create_dir_all(output.parent().unwrap()).unwrap();
    let artifacts = output.with_extension("artifacts");
    std::fs::create_dir(&artifacts).unwrap();
    let directory = artifacts.join("trial");
    std::fs::create_dir(&directory).unwrap();
    let temporary = tempfile::Builder::new()
        .prefix("hm9-")
        .tempdir_in("/tmp")
        .unwrap();
    let training = trainer();
    let code = support::code(&training);
    let protocol = std::fs::read(
        training
            .qualification_root
            .join("memory-cell-v9/learning/STRUCTURE_PROTOCOL.json"),
    )
    .unwrap();
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(artifacts.join("PROTOCOL.json"))
        .unwrap();
    std::io::Write::write_all(&mut file, &protocol).unwrap();
    file.sync_all().unwrap();
    let config_path = artifacts.join("child-config.json");
    data::save(
        &config_path,
        &serde_json::to_value(ChildConfig {
            output_dir: directory.clone(),
            runtime_root: temporary.path().to_path_buf(),
        })
        .unwrap(),
    );
    data::save(
        &artifacts.join("MANIFEST.json"),
        &json!({"code_identity":code,"fixture_sha256":data::FIXTURE_SHA,
        "protocol_sha256":Digest32::of_bytes(&protocol).to_string(),"runtime_root":temporary.path(),"future_outcomes_seen":false}),
    );
    let resources = artifacts.join("resources.json");
    let stderr = artifacts.join("stderr.log");
    let mut child = tokio::process::Command::new(&training.python)
        .args(["-I", "-B"])
        .arg(
            training
                .qualification_root
                .join("memory-cell-v9/learning/resource_monitor.py"),
        )
        .arg("--output")
        .arg(&resources)
        .arg("--samples")
        .arg(artifacts.join("samples.jsonl"))
        .arg("--root")
        .arg(&directory)
        .arg("--root")
        .arg(temporary.path())
        .args(["--interval-ms", "200", "--timeout-seconds", "3600"])
        .arg("--stdout")
        .arg(artifacts.join("stdout.log"))
        .arg("--stderr")
        .arg(&stderr)
        .arg("--")
        .arg(std::env::current_exe().unwrap())
        .args([
            "--ignored",
            "--exact",
            "memory_cell_v9_continual_tests::structure::memory_cell_v9_structure_child",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("MEMORY_CELL_V9_STRUCTURE_CHILD_CONFIG", &config_path)
        .env("TMPDIR", temporary.path())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let status = match tokio::time::timeout(Duration::from_secs(3660), child.wait()).await {
        Ok(result) => result.unwrap(),
        Err(error) => {
            child.kill().await.unwrap();
            let _ = child.wait().await;
            super::log_monitor_failure(&resources, &stderr);
            panic!("structure child deadline: {error}");
        }
    };
    if !status.success() {
        super::log_monitor_failure(&resources, &stderr);
    }
    assert!(
        status.success(),
        "structure child failed; original logs/failed receipts retained"
    );
    let raw = std::fs::read(directory.join("CHILD.json")).unwrap();
    let child_report: Value = serde_json::from_slice(&raw).unwrap();
    let resource_raw = std::fs::read(&resources).unwrap();
    temporary.close().unwrap();
    assert_eq!(support::code(&training), code);
    data::save(
        &output,
        &json!({"schema":"hepta.memory.v9.actual-structure.v1","fixture_sha256":data::FIXTURE_SHA,
        "artifact_directory":artifacts.file_name().unwrap().to_str().unwrap(),"code_identity":code,"child":child_report,
        "child_identity":{"bytes":raw.len(),"sha256":Digest32::of_bytes(&raw).to_string()},
        "resource_identity":{"bytes":resource_raw.len(),"sha256":Digest32::of_bytes(&resource_raw).to_string()},
        "parent_supervision_wall_ns":started.elapsed().as_nanos(),"full_cost_gain_established":false}),
    );
}

#[tokio::test]
#[ignore = "fresh supervised structure child helper"]
async fn memory_cell_v9_structure_child() {
    let Some(path) = std::env::var_os("MEMORY_CELL_V9_STRUCTURE_CHILD_CONFIG") else {
        return;
    };
    let config: ChildConfig =
        serde_json::from_slice(&std::fs::read(PathBuf::from(path)).unwrap()).unwrap();
    assert!(config.output_dir.is_absolute());
    let report = run(&config).await;
    data::save(&config.output_dir.join("CHILD.json"), &report);
}
