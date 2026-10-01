#![cfg(unix)]

use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;

const CHILD: &str = env!("CARGO_BIN_EXE_hepta-infer-maintenance-fault-child");

struct TestJournal {
    directory: PathBuf,
    journal: PathBuf,
}

impl TestJournal {
    #[allow(
        clippy::unwrap_used,
        reason = "This helper prepares a test fixture and must fail on invalid setup"
    )]
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "hepta-inference-process-crash-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        Self {
            journal: directory.join("control.journal"),
            directory,
        }
    }
}

impl Drop for TestJournal {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

#[test]
fn sigkill_at_every_maintenance_boundary_recovers_one_complete_generation() {
    let cases = [
        ("before-archive-write", 0),
        ("after-archive-sync", 0),
        ("before-checkpoint-write", 0),
        ("after-checkpoint-sync", 0),
        ("before-generation-write", 0),
        ("after-generation-sync", 0),
        ("after-generation-rename", 1),
        ("after-parent-sync", 1),
    ];
    for (stage, expected_generation) in cases {
        let paths = TestJournal::new(stage);
        seed_released_request(&paths.journal, stage);
        let marker = paths.directory.join(format!("{stage}.marker"));
        let mut child = Command::new(CHILD)
            .arg(&paths.journal)
            .arg(&marker)
            .arg(stage)
            .spawn()
            .unwrap();
        wait_for_marker(&marker, &mut child);
        let status = Command::new("kill")
            .arg("-KILL")
            .arg(child.id().to_string())
            .status()
            .unwrap();
        assert!(status.success(), "failed to SIGKILL child at {stage}");
        let child_status = child.wait().unwrap();
        assert!(
            !child_status.success(),
            "fault child unexpectedly succeeded at {stage}"
        );

        let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
        let request_id = format!("request-{stage}");
        assert_eq!(
            reopened.native_record(&request_id).unwrap().state,
            NativeReservationState::Released,
            "state mismatch after SIGKILL at {stage}"
        );
        assert_eq!(
            reopened.native_metrics(3_000_000).checkpoint_generation,
            expected_generation,
            "generation mismatch after SIGKILL at {stage}"
        );
    }
}

#[test]
fn an_incomplete_torn_tail_is_rejected_instead_of_replayed_or_truncated() {
    let paths = TestJournal::new("torn-tail");
    seed_released_request(&paths.journal, "torn-tail");
    let original = fs::read(&paths.journal).unwrap();
    let mut file = OpenOptions::new()
        .append(true)
        .open(&paths.journal)
        .unwrap();
    file.write_all(b"native-v1|{\"reserve\":").unwrap();
    file.sync_all().unwrap();
    drop(file);

    assert!(DurableInferenceControl::open(&paths.journal, 8).is_err());
    let after = fs::read(&paths.journal).unwrap();
    assert!(after.starts_with(&original));
    assert!(after.len() > original.len());
}

#[allow(
    clippy::unwrap_used,
    reason = "This helper prepares a test fixture and must fail on invalid setup"
)]
fn seed_released_request(journal: &Path, label: &str) {
    let request_id = format!("request-{label}");
    let mut control = DurableInferenceControl::open(journal, 8).unwrap();
    control
        .reserve_native(
            NativeRequest {
                request_id: request_id.clone(),
                principal_id: "process-crash-principal".to_string(),
                worker_generation: 1,
                model: "process-crash-model".to_string(),
                payload_digest: "a".repeat(64),
            },
            1,
        )
        .unwrap();
    control
        .stop_native_before_dispatch(&request_id, "qualification seed complete".to_string())
        .unwrap();
}

#[allow(
    clippy::unwrap_used,
    reason = "This helper prepares a test fixture and must fail on invalid setup"
)]
fn wait_for_marker(marker: &Path, child: &mut std::process::Child) {
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        if marker.is_file() {
            return;
        }
        if let Some(status) = child.try_wait().unwrap() {
            panic!("fault child exited before marker with {status}");
        }
        assert!(
            Instant::now() < deadline,
            "timed out waiting for fault child marker"
        );
        thread::sleep(Duration::from_millis(10));
    }
}
