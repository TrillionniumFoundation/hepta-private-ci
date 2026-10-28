//! Pinned, bounded worker execution retains original paired-model byte strings.

use std::path::Path;
use std::collections::BTreeMap;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

use crate::MemoryCellTrainerConfigV1;
use crate::memory_cell_training_test_support::CODE_FILES;

use super::data::save;

pub(super) const RESIDENT_BUDGET: u64 = 262_144;

pub(super) fn code_identity(config: &MemoryCellTrainerConfigV1) -> Value {
    let mut files = BTreeMap::new();
    for name in CODE_FILES.into_iter().chain([
        "memory-cell-v9/learning/__init__.py", "memory-cell-v9/learning/paired.py",
        "memory-cell-v9/learning/byte_model.py", "memory-cell-v9/learning/worker.py",
        "memory-cell-v9/learning/PROTOCOL.json", "memory-cell-v9/learning/resource_monitor.py",
        "memory-cell-v9/learning/resource_samples.py",
        "memory-cell-v9/learning/resource_cleanup.py",
    ]) {
        let raw = std::fs::read(config.qualification_root.join(name)).unwrap();
        files.insert(name.to_string(), json!({"bytes":raw.len(),"sha256":Digest32::of_bytes(&raw).to_string()}));
    }
    let raw = serde_json::to_vec(&files).unwrap();
    json!({"files":files,"digest":Digest32::of_bytes(&raw).to_string()})
}

pub(super) async fn fit(config: &MemoryCellTrainerConfigV1, snapshot: &codex_hepta_memory::MemoryCellOwnerSnapshotV1,
    representation: &str, parents: Value, directory: &Path) -> Value {
    let code = code_identity(config);
    // Train from the exact export already retained by the caller. A second
    // snapshot could cross a wall-clock second and change its observation time.
    let configuration = json!({"seed":91317,"steps":600,"dimension":48,"hidden":32,
        "threshold":if representation == "catalog" {0.5} else {0.9}});
    let frame = json!({"schema":"hepta.memory.v9.paired-fit.v1",
        "representation":representation,"configuration":configuration,"export":snapshot,"parents":parents});
    let result = execute(config,&frame,"memory-cell-v9/learning/worker.py",&code,directory).await;
    assert_eq!(code_identity(config),code);
    assert_eq!(result["owner_cut_digest"],snapshot.owner_cut_digest().to_string());
    assert_eq!(result["configuration"],configuration);
    assert_eq!(result["representation"],representation);
    assert_eq!(result["receipt"]["actual_fit_calls"],6);
    result
}

pub(super) async fn execute(config: &MemoryCellTrainerConfigV1, frame: &Value,
    script: &str, code: &Value, directory: &Path) -> Value {
    let request = serde_json::to_vec(frame).unwrap();
    assert!(request.len() <= 16 * 1024 * 1024);
    save(&directory.join("FIT_REQUEST.json"),&json!({"request_json":String::from_utf8(request.clone()).unwrap(),
        "request_sha256":Digest32::of_bytes(&request).to_string(),"code_identity":code}));
    let started = Instant::now();
    let mut child = tokio::process::Command::new(&config.python)
        .args(["-I","-u","-B"]).arg(config.qualification_root.join(script))
        .env("OPENBLAS_NUM_THREADS","1").env("OMP_NUM_THREADS","1")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).kill_on_drop(true).spawn().unwrap();
    let pid = child.id().unwrap();
    let mut input = child.stdin.take().unwrap();
    let output = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    let execute = async {
        let send = async { input.write_all(&request).await.unwrap(); input.shutdown().await.unwrap(); drop(input); };
        let receive = async { let mut raw = Vec::new(); output.take(16 * 1024 * 1024 + 1).read_to_end(&mut raw).await.unwrap(); raw };
        let errors = async { let mut raw = Vec::new(); stderr.take(8193).read_to_end(&mut raw).await.unwrap(); raw };
        let (_, raw, errors) = tokio::join!(send,receive,errors);
        (child.wait().await.unwrap(),raw,errors)
    };
    let (status,raw,errors) = match tokio::time::timeout(Duration::from_secs(60),execute).await {
        Ok(value) => value,
        Err(error) => { child.kill().await.unwrap(); let _ = child.wait().await;
            save(&directory.join("FIT_FAILURE.json"),&json!({"pid":pid,"deadline_seconds":60,"error":error.to_string()}));
            panic!("bounded paired fit exceeded deadline: {error}"); }
    };
    save(&directory.join("FIT_RESPONSE.json"),&json!({"response_json":String::from_utf8_lossy(&raw),
        "response_bytes":raw.len(),"stderr":String::from_utf8_lossy(&errors),"stderr_bytes":errors.len(),
        "request_bytes":request.len(),"child_pid":pid,"exit_code":status.code(),
        "whole_worker_wall_ns":started.elapsed().as_nanos(),"code_identity":code}));
    assert!(status.success(),"paired training failed: {}",String::from_utf8_lossy(&errors));
    assert!(raw.len() <= 16 * 1024 * 1024 && errors.len() <= 8192);
    let result: Value = serde_json::from_slice(&raw).unwrap();
    assert_eq!(result["request_digest"],Digest32::of_bytes(&request).to_string());
    result
}

pub(super) fn native<'a>(fit: &'a Value, intervention: &str, kind: &str) -> &'a [u8] {
    fit["artifacts"][intervention][kind]["native"].as_str().unwrap().as_bytes()
}

pub(super) fn set_budget(release: &crate::memory_cell_release::test_support::ReleaseFixture) {
    let selected = release.host.load_current().unwrap();
    for cell in [selected.semantic(),selected.procedure()] { cell.set_resident_budget(RESIDENT_BUDGET).unwrap(); }
}

pub(super) fn publish(release: &crate::memory_cell_release::test_support::ReleaseFixture,
    snapshot: &codex_hepta_memory::MemoryCellOwnerSnapshotV1, fit: &Value, intervention: &str,
    generation: u64, code: Digest32) -> Value {
    let proposal = release.prepare_models(snapshot,generation,native(fit,intervention,"semantic"),
        native(fit,intervention,"procedure"),code);
    release.host.publish(proposal.clone(),snapshot).unwrap();
    release.install(&proposal).unwrap();
    set_budget(release);
    let loaded = release.host.load_current().unwrap();
    json!({"generation":loaded.generation().get(),"bundle_digest":loaded.bundle_digest(),
        "source_cut":loaded.owner_cut_digest(),"semantic_digest":loaded.semantic().digest().to_string(),
        "procedure_digest":loaded.procedure().digest().to_string(),"intervention":intervention})
}
