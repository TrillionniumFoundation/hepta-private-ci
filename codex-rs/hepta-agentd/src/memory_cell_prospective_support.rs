//! Fresh-process trials retain actual owner, parameter, release and RPC evidence.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

use crate::MemoryCellTrainerConfigV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_runtime_tests::TrustedTestResolver;
use crate::memory_cell_runtime_tests::attach;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_training_test_support::CODE_FILES;
use crate::memory_cell_training_test_support::trainer;
use crate::memory_cell_training_test_support::write_new;

use super::batches::Reader;
use super::batches::batches;
use super::batches::routing_trace;
use super::direct::DirectOwner;

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum RoutingMode {
    Fixed,
    Learned,
    DirectOwner,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Trial {
    pub id: String,
    pub seed: String,
    pub count: usize,
    pub routing_mode: RoutingMode,
    pub resident_budget_bytes: u64,
    pub expected_source_cut: Option<String>,
    pub output_dir: PathBuf,
}

pub(super) fn write_json(path: &Path, value: &Value) {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap();
    file.write_all(&serde_json::to_vec_pretty(value).unwrap())
        .unwrap();
    file.write_all(b"\n").unwrap();
    file.sync_all().unwrap();
}

fn progress(directory: &Path, phase: &str, artifact: &str) {
    let path = directory.join("PROGRESS.jsonl");
    let previous = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Vec::new(),
        Err(error) => panic!("progress read failed: {error}"),
    };
    let event = json!({"phase":phase,"artifact":artifact,
        "artifact_sha256":Digest32::of_bytes(&std::fs::read(directory.join(artifact)).unwrap()).to_string(),
        "previous_sha256":Digest32::of_bytes(&previous).to_string()});
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .unwrap();
    file.write_all(&serde_json::to_vec(&event).unwrap())
        .unwrap();
    file.write_all(b"\n").unwrap();
    file.sync_all().unwrap();
}

pub(super) fn code_digest(config: &MemoryCellTrainerConfigV1) -> Digest32 {
    let mut raw = b"hepta.memory.prospective.code.v1".to_vec();
    for name in CODE_FILES.into_iter().chain([
        "memory-cell-v7/population_training.py",
        "memory-cell-v8/learning/__init__.py",
        "memory-cell-v8/learning/allocation.py",
        "memory-cell-v8/learning/population_training.py",
        "memory-cell-v8/learning/worker.py",
    ]) {
        raw.extend_from_slice(&(name.len() as u64).to_be_bytes());
        raw.extend_from_slice(name.as_bytes());
        raw.extend_from_slice(
            Digest32::of_bytes(&std::fs::read(config.qualification_root.join(name)).unwrap())
                .as_array(),
        );
    }
    Digest32::of_bytes(&raw)
}

async fn fit_population(
    config: &MemoryCellTrainerConfigV1,
    owner: &ControlFixture,
    count: usize,
    trace: Option<&Value>,
    path: &Path,
) -> Value {
    let before = code_digest(config);
    let snapshot = owner.snapshot().await;
    let configuration = json!({"shard_count":count,"seed":91317,"steps":600,"dimension":48,"total_hidden":64,"threshold":0.5});
    let request = serde_json::to_vec(&json!({"schema":"hepta.memory.prospective-population-fit.v1", "export":snapshot,
        "configuration":configuration,"routing_mode":if trace.is_some() {"learned"} else {"fixed"},"routing_trace":trace})).unwrap();
    let started = Instant::now();
    let mut child = tokio::process::Command::new(&config.python)
        .args(["-I", "-u", "-B"])
        .arg(
            config
                .qualification_root
                .join("memory-cell-v8/learning/worker.py"),
        )
        .env("OPENBLAS_NUM_THREADS", "1")
        .env("OMP_NUM_THREADS", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let mut input = child.stdin.take().unwrap();
    let output = child.stdout.take().unwrap();
    let errors = child.stderr.take().unwrap();
    let execution = async {
        let send = async {
            input.write_all(&request).await.unwrap();
            input.shutdown().await.unwrap();
            drop(input);
        };
        let receive = async {
            let mut raw = Vec::new();
            output
                .take(16 * 1024 * 1024 + 1)
                .read_to_end(&mut raw)
                .await
                .unwrap();
            raw
        };
        let stderr = async {
            let mut raw = Vec::new();
            errors.take(8193).read_to_end(&mut raw).await.unwrap();
            raw
        };
        let (_, raw, diagnostics) = tokio::join!(send, receive, stderr);
        let status = child.wait().await.unwrap();
        assert!(
            status.success(),
            "actual fit failed: {}",
            String::from_utf8_lossy(&diagnostics)
        );
        assert!(raw.len() <= 16 * 1024 * 1024 && diagnostics.len() <= 8192);
        (raw, diagnostics)
    };
    let (raw, diagnostics) = match tokio::time::timeout(Duration::from_secs(60), execution).await {
        Ok(result) => result,
        Err(error) => {
            child.kill().await.unwrap();
            let _ = child.wait().await;
            panic!("bounded genuine fit exceeded deadline: {error}");
        }
    };
    let mut result: Value = serde_json::from_slice(&raw).unwrap();
    assert_eq!(code_digest(config), before);
    assert_eq!(
        result["request_digest"],
        Digest32::of_bytes(&request).to_string()
    );
    assert_eq!(
        result["owner_cut_digest"],
        snapshot.owner_cut_digest().to_string()
    );
    assert_eq!(result["configuration"], configuration);
    assert_eq!(result["receipt"]["fit_calls"], 2 * count);
    result["host_measurement"] = json!({"whole_training_process_wall_ns":started.elapsed().as_nanos(),
        "request_bytes":request.len(),"request_json":String::from_utf8(request).unwrap(),
        "response_bytes":raw.len(),"stderr_bytes":diagnostics.len(),"training_code_digest":before.to_string()});
    // Preserve the exact worker bytes: native arrays and floating-point
    // training diagnostics must remain reproducible across JSON encoders.
    write_json(
        path,
        &json!({"schema":"hepta.memory.prospective-fit-evidence.v1",
        "response_json":String::from_utf8(raw).unwrap(),"host_measurement":result["host_measurement"]}),
    );
    result
}

fn native<'a>(value: &'a Value, kind: &str) -> &'a [u8] {
    value["artifacts"][kind]["native"]
        .as_str()
        .unwrap()
        .as_bytes()
}

fn files_under(path: &Path) -> Vec<Value> {
    let mut paths = std::fs::read_dir(path)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .collect::<Vec<_>>();
    paths.sort();
    let mut files = Vec::new();
    for path in paths {
        let metadata = std::fs::symlink_metadata(&path).unwrap();
        assert!(
            !metadata.file_type().is_symlink(),
            "cost enumeration must not follow symlinks"
        );
        if metadata.is_dir() {
            files.extend(files_under(&path));
        } else if metadata.is_file() {
            files.push(json!({"file":path.file_name().unwrap().to_string_lossy(),"logical_bytes":metadata.len()}));
        }
    }
    files
}

fn host_peak_rss_bytes() -> Option<u64> {
    // Linux VmHWM includes the fresh native trial process, not its separate
    // Python workers. Their peaks are saved in each complete fit receipt.
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    status
        .lines()
        .find(|line| line.starts_with("VmHWM:"))?
        .split_whitespace()
        .nth(1)?
        .parse::<u64>()
        .ok()?
        .checked_mul(1024)
}

async fn run_trial(trial: Trial) -> Value {
    assert!((1..=8).contains(&trial.count) && trial.output_dir.is_absolute());
    let started = Instant::now();
    let fixture = ControlFixture::new().await;
    let expected = write_new(&fixture, &trial.seed, 0..24).await;
    let snapshot = fixture.snapshot().await;
    if let Some(cut) = &trial.expected_source_cut {
        assert_eq!(&snapshot.owner_cut_digest().to_string(), cut);
    }
    let config = trainer();
    write_json(
        &trial.output_dir.join("START.json"),
        &json!({"trial":trial,"source_cut":snapshot.owner_cut_digest(),
        "training_code_digest":code_digest(&config).to_string(),"child_pid":std::process::id()}),
    );
    write_json(
        &trial.output_dir.join("OWNER_EXPORT.json"),
        &serde_json::to_value(&snapshot).unwrap(),
    );
    progress(&trial.output_dir, "source_ready", "OWNER_EXPORT.json");
    if matches!(trial.routing_mode, RoutingMode::DirectOwner) {
        fixture.ready();
        let (direct, acquisition) =
            DirectOwner::acquire(&fixture, trial.resident_budget_bytes * 2).await;
        write_json(
            &trial.output_dir.join("owner-acquisition.json"),
            &acquisition,
        );
        progress(
            &trial.output_dir,
            "owner_acquired",
            "owner-acquisition.json",
        );
        let reader = Reader::Direct(&direct);
        let before_retention = batches(&fixture, &reader, &expected, "retention").await;
        write_json(
            &trial.output_dir.join("before-retention.json"),
            &before_retention,
        );
        progress(
            &trial.output_dir,
            "retention_before",
            "before-retention.json",
        );
        let prefix = batches(&fixture, &reader, &expected, "prefix").await;
        write_json(&trial.output_dir.join("completed-prefix.json"), &prefix);
        progress(
            &trial.output_dir,
            "prefix_complete",
            "completed-prefix.json",
        );
        write_json(
            &trial.output_dir.join("FIT_LOCK.json"),
            &json!({"source_cut":snapshot.owner_cut_digest(),
            "training_executed":false,"direct_owner_cache_bytes":direct.logical_cache_bytes,
            "future_protocol":"hepta.memory.future-coaccess.v1","future_outcomes_seen":false}),
        );
        progress(&trial.output_dir, "fit_locked", "FIT_LOCK.json");
        let mut evaluations = Vec::new();
        for phase in ["selection", "future", "retention"] {
            let result = batches(&fixture, &reader, &expected, phase).await;
            write_json(&trial.output_dir.join(format!("{phase}.json")), &result);
            progress(&trial.output_dir, phase, &format!("{phase}.json"));
            evaluations.push(result);
        }
        let source_files = files_under(fixture.state.identity().layout.cognitive_root());
        let source_bytes: u64 = source_files
            .iter()
            .map(|file| file["logical_bytes"].as_u64().unwrap())
            .sum();
        let report = json!({"schema":"hepta.memory.prospective-trial.v1","trial":trial,"child_pid":std::process::id(),
            "source_cut":snapshot.owner_cut_digest(),"training_code_digest":null,"bootstrap_training":null,
            "candidate_training":null,"training_processes":[],"training_fit_calls":0,"model_storage_bytes":0,
            "prefix":prefix,"before_retention":before_retention,"routing_trace":null,"evaluations":evaluations,
            "host_peak_rss_bytes":host_peak_rss_bytes(),"source_ledger_logical_bytes":source_bytes,"source_files":source_files,
            "artifact_owner_logical_bytes":0,"artifact_files":[],"direct_owner_cache_logical_bytes":direct.logical_cache_bytes,
            "owner_acquisition":acquisition,"traffic":fixture.client.traffic_snapshot(),"child_work_wall_ns":started.elapsed().as_nanos(),
            "fresh_process_per_arm":true,"catalog_contains_explicit_values":true,"future_protocol_held_from_routing_fit":true,
            "externally_authored_or_iid_tasks":false,"exclusive_communication_wall_ns":null,"autonomous_release_authority":false});
        drop(direct);
        fixture.finish().await;
        return report;
    }
    let bootstrap = fit_population(
        &config,
        &fixture,
        /*count*/ 4,
        /*trace*/ None,
        &trial.output_dir.join("bootstrap-fit.json"),
    )
    .await;
    progress(&trial.output_dir, "bootstrap_fit", "bootstrap-fit.json");
    let release = ReleaseFixture::from_populations_with_training_code(
        &snapshot,
        native(&bootstrap, "semantic"),
        native(&bootstrap, "procedure"),
        code_digest(&config),
    );
    let resolver = TrustedTestResolver::new(&fixture);
    let runtime = attach(&fixture, &release, &resolver);
    let initial = release.host.load_current().unwrap();
    for model in [initial.semantic(), initial.procedure()] {
        model
            .set_resident_budget(trial.resident_budget_bytes)
            .unwrap();
    }
    let reader = Reader::Native(&resolver);
    let before_retention = batches(&fixture, &reader, &expected, "retention").await;
    write_json(
        &trial.output_dir.join("before-retention.json"),
        &before_retention,
    );
    progress(
        &trial.output_dir,
        "retention_before",
        "before-retention.json",
    );
    let prefix = batches(&fixture, &reader, &expected, "prefix").await;
    assert_eq!(
        prefix["correct"], prefix["queries"],
        "the observed prefix uses owner event facts"
    );
    write_json(&trial.output_dir.join("completed-prefix.json"), &prefix);
    progress(
        &trial.output_dir,
        "prefix_complete",
        "completed-prefix.json",
    );
    drop(initial);
    let trace = routing_trace(snapshot.owner_cut_digest().digest(), &prefix);
    write_json(&trial.output_dir.join("ROUTING_TRACE.json"), &trace);
    let candidate = fit_population(
        &config,
        &fixture,
        trial.count,
        match trial.routing_mode {
            RoutingMode::Fixed => None,
            RoutingMode::Learned => Some(&trace),
            RoutingMode::DirectOwner => unreachable!("direct branch returned"),
        },
        &trial.output_dir.join("candidate-fit.json"),
    )
    .await;
    progress(&trial.output_dir, "candidate_fit", "candidate-fit.json");
    let proposal = release.prepare_populations(
        &snapshot,
        /*generation*/ 2,
        native(&candidate, "semantic"),
        native(&candidate, "procedure"),
        code_digest(&config),
    );
    release.host.publish(proposal.clone(), &snapshot).unwrap();
    release.install(&proposal).unwrap();
    let loaded = release.host.load_current().unwrap();
    for model in [loaded.semantic(), loaded.procedure()] {
        model
            .set_resident_budget(trial.resident_budget_bytes)
            .unwrap();
    }
    // This lock is created before any selection/future/retention query. The
    // learner has received only the owner export and the completed prefix.
    write_json(
        &trial.output_dir.join("FIT_LOCK.json"),
        &json!({"source_cut":snapshot.owner_cut_digest(),
        "bundle_digest":loaded.bundle_digest(),"routing_trace_digest":trace["trace_digest"],
        "future_protocol":"hepta.memory.future-coaccess.v1","future_outcomes_seen":false}),
    );
    progress(&trial.output_dir, "fit_locked", "FIT_LOCK.json");
    let mut evaluations = Vec::new();
    for phase in ["selection", "future", "retention"] {
        for model in [loaded.semantic(), loaded.procedure()] {
            model.sleep().unwrap();
        }
        let mut result = batches(&fixture, &reader, &expected, phase).await;
        result["native_cost_after_phase"] = json!([
            loaded.semantic().cost().unwrap(),
            loaded.procedure().cost().unwrap()
        ]);
        write_json(&trial.output_dir.join(format!("{phase}.json")), &result);
        progress(&trial.output_dir, phase, &format!("{phase}.json"));
        evaluations.push(result);
    }
    let source_files = files_under(fixture.state.identity().layout.cognitive_root());
    let artifact_files = files_under(release.directory.path());
    let source_bytes: u64 = source_files
        .iter()
        .map(|file| file["logical_bytes"].as_u64().unwrap())
        .sum();
    let artifact_bytes: u64 = artifact_files
        .iter()
        .map(|file| file["logical_bytes"].as_u64().unwrap())
        .sum();
    let report = json!({"schema":"hepta.memory.prospective-trial.v1","trial":trial,"child_pid":std::process::id(),
        "source_cut":snapshot.owner_cut_digest(),"training_code_digest":code_digest(&config).to_string(),
        "bootstrap_training":bootstrap["receipt"],"candidate_training":candidate["receipt"],
        "training_processes":[bootstrap["host_measurement"],candidate["host_measurement"]],
        "prefix":prefix,"before_retention":before_retention,"routing_trace":trace,"evaluations":evaluations,
        "host_peak_rss_bytes":host_peak_rss_bytes(),"source_ledger_logical_bytes":source_bytes,"source_files":source_files,
        "artifact_owner_logical_bytes":artifact_bytes,"artifact_files":artifact_files,
        "traffic":fixture.client.traffic_snapshot(),"child_work_wall_ns":started.elapsed().as_nanos(),
        "fresh_process_per_arm":true,"catalog_contains_explicit_values":true,
        "future_protocol_held_from_routing_fit":true,"externally_authored_or_iid_tasks":false,
        "exclusive_communication_wall_ns":null,"autonomous_release_authority":false});
    drop(loaded);
    drop(runtime);
    drop(resolver);
    drop(release);
    fixture.finish().await;
    report
}

#[tokio::test]
#[ignore = "child helper; only the parent prospective test supplies its absolute configuration"]
async fn memory_cell_trial_child() {
    let Some(path) = std::env::var_os("MEMORY_CELL_V8_TRIAL_CONFIG") else {
        return;
    };
    let path = PathBuf::from(path);
    assert!(path.is_absolute());
    let raw = std::fs::read(path).unwrap();
    assert!(raw.len() <= 16_384);
    let trial: Trial = serde_json::from_slice(&raw).unwrap();
    let output = trial.output_dir.join("TRIAL.json");
    let report = run_trial(trial).await;
    write_json(&output, &report);
    println!("MEMORY_CELL_V8_TRIAL_COMPLETE={}", output.display());
}
