//! Process-only fixtures never import torch or claim successful inference.
use super::execute;
use crate::native_memory_test_support::config;
use codex_hepta_types::Digest32;
use std::time::Duration;
use std::time::Instant;

fn prepared_worker(temp: &tempfile::TempDir) -> crate::NativeMemoryModelConfigV1 {
    let mut c = config(temp.path());
    let python = std::process::Command::new("python3")
        .args(["-c", "import sys; print(sys.executable)"])
        .output()
        .unwrap();
    assert!(python.status.success());
    c.python = String::from_utf8(python.stdout).unwrap().trim().into();
    for path in [
        "scripts/memory_cell_native",
        "scripts/memory_cell_network",
        "receipts",
    ] {
        std::fs::create_dir_all(temp.path().join(path)).unwrap();
    }
    let worker = b"import time\ntime.sleep(30)\n";
    let launcher = b"import runpy,sys\nrunpy.run_path(sys.argv[-1],run_name='__main__')\n";
    std::fs::write(
        temp.path()
            .join("scripts/memory_cell_native/native_worker.py"),
        worker,
    )
    .unwrap();
    std::fs::write(
        temp.path()
            .join("scripts/memory_cell_network/model_child.py"),
        launcher,
    )
    .unwrap();
    c.pins.worker_sha256 = Digest32::of_bytes(worker).to_string();
    c.pins.launcher_sha256 = Digest32::of_bytes(launcher).to_string();
    c
}

#[test]
fn native_memory_timeout_includes_blocked_stdin_and_keeps_failure() {
    let temp = tempfile::tempdir().unwrap();
    let mut c = prepared_worker(&temp);
    c.timeout_millis = 100;
    let input = vec![b'x'; 65_536];
    let directory = c
        .receipt_directory
        .join(Digest32::of_bytes(&input).to_string());
    let started = Instant::now();
    assert!(execute(&c, input, &tokio_util::sync::CancellationToken::new()).is_err());
    assert!(started.elapsed() < Duration::from_secs(3));
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("process.json")).unwrap()).unwrap();
    assert!(report["timed_out"] == true && report["stdin_completed"] == false);
    assert!(directory.join("stderr.log").is_file());
}

#[test]
fn native_memory_daemon_lifetime_cancels_child_and_keeps_failure() {
    let temp = tempfile::tempdir().unwrap();
    let c = prepared_worker(&temp);
    let cancellation = tokio_util::sync::CancellationToken::new();
    let other = cancellation.clone();
    let cancel = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(100));
        other.cancel();
    });
    let started = Instant::now();
    let input = b"closed fixture".to_vec();
    let directory = c
        .receipt_directory
        .join(Digest32::of_bytes(&input).to_string());
    assert!(execute(&c, input, &cancellation).is_err());
    cancel.join().unwrap();
    assert!(started.elapsed() < Duration::from_secs(3));
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("process.json")).unwrap()).unwrap();
    assert!(report["owner_cancelled"] == true);
}
