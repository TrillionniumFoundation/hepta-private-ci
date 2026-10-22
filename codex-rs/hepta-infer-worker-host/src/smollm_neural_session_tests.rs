//! A supervisor's nonzero exit cannot be replaced by a success-shaped receipt.
//! These are controlled process/receipt fixtures, not model execution evidence.

use std::fs;
use std::process::Command;
use std::process::Stdio;

use super::*;

#[test]
fn terminal_unload_requires_successful_supervisor_and_original_child_receipt() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    for (command, exit_code, outcome, expected) in [
        (
            "exit 7",
            7,
            "success",
            "neural supervisor did not exit successfully",
        ),
        (
            "exit 0",
            0,
            "budget-exceeded",
            "neural unload lacks a successful original owned-child receipt",
        ),
    ] {
        let directory = tempfile::tempdir().unwrap();
        let worker = directory.path().join("session/worker");
        fs::create_dir_all(&worker).unwrap();
        let receipt = serde_json::json!({
            "outcome":outcome, "exit_code":0, "stop_reason":null,
            "waited_child_reaped":true, "owned_child_reap_resolved":true,
            "waited_child_observation_error":null, "observed_wall_ns":1,
            "waited_child_peak_rss_bytes":4096,
            "budget":{"wall_seconds":600, "rss_bytes":8589934592_u64},
        });
        fs::write(
            worker.join("supervisor.json"),
            serde_json::to_vec(&receipt).unwrap(),
        )
        .unwrap();
        let mut supervisor = Command::new("/bin/sh")
            .args(["-c", command])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        // Reap this controlled supervisor before composition, without a sleep
        // race. std::process::Child retains its exact status for try_wait.
        assert_eq!(supervisor.wait().unwrap().code(), Some(exit_code));
        let mut session = Session::new(
            File::open(directory.path()).unwrap(),
            supervisor,
            runtime.handle().clone(),
        );
        assert_eq!(session.shutdown(), Err(expected.to_owned()));
        assert!(session.supervisor.is_some());
    }
}
