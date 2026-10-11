//! Measures the shipped single-writer journal; emits observations, not SLO claims.

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;
use std::time::SystemTime;

use super::ControlReceipt;
use super::DurableInferenceControl;
use super::Error;
use super::InferenceRequest;
use super::RequestState;

struct JournalDirectory(PathBuf);

impl Drop for JournalDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
#[ignore = "explicit bounded real-filesystem history measurement"]
fn bounded_single_writer_history_emits_append_update_recovery_memory_and_disk_curve() {
    let nonce = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let directory = JournalDirectory(std::env::temp_dir().join(format!(
        "hepta-infer-history-{}-{nonce}",
        std::process::id()
    )));
    fs::create_dir(&directory.0).expect("isolated journal directory");
    let path = directory.0.join("control.journal");
    let capacity = 1_024;
    let mut control = DurableInferenceControl::open(&path, capacity).expect("journal owner");
    let mut requests = BTreeMap::new();
    let mut previous_count = 0;
    let mut previous_bytes = 0;
    for count in [32, 256, capacity] {
        let mut append_us = Vec::new();
        for index in previous_count..count {
            let request = InferenceRequest {
                request_id: format!("history.{index}"),
                principal_id: "principal.1".into(),
                model_digest: "1".repeat(64),
                payload_digest: "2".repeat(64),
                maximum_tokens: 128,
                deadline_ms: 10_000,
                semantic_digest: "3".repeat(64),
            };
            let started = Instant::now();
            control
                .submit(/*now_ms*/ 100, request.clone())
                .expect("durable append");
            append_us.push(started.elapsed().as_micros());
            requests.insert(request.request_id.clone(), request);
        }
        // A second owner never measures an imaginary concurrent-writer path.
        assert!(matches!(
            DurableInferenceControl::open(&path, capacity),
            Err(Error::WriterUnavailable)
        ));
        let last_id = format!("history.{}", count - 1);
        let started = Instant::now();
        control
            .cancel(&last_id, /*expected_revision*/ 1)
            .expect("durable update");
        let update_us = started.elapsed().as_micros();
        let before_retry = fs::metadata(&path).expect("journal bytes").len();
        assert_eq!(
            control
                .cancel(&last_id, /*expected_revision*/ 2)
                .expect("exact cancel retry"),
            ControlReceipt {
                request_id: last_id,
                revision: 2,
                state: RequestState::Cancelled,
                idempotent: true,
                terminal_observed: true,
            }
        );
        // Conflicting identity rejection and idempotent retries append no bytes.
        let mut conflict = requests.get("history.0").expect("first request").clone();
        conflict.payload_digest = "4".repeat(64);
        assert_eq!(
            control.submit(/*now_ms*/ 100, conflict),
            Err(Error::Conflict)
        );
        assert_eq!(
            fs::metadata(&path).expect("unchanged journal").len(),
            before_retry
        );
        let expected: Vec<_> = requests
            .keys()
            .map(|id| control.get(id).expect("record").clone())
            .collect();
        drop(control);
        let started = Instant::now();
        control = DurableInferenceControl::open(&path, capacity).expect("full history recovery");
        let recovery_us = started.elapsed().as_micros();
        let recovered: Vec<_> = requests
            .keys()
            .map(|id| control.get(id).expect("recovered record").clone())
            .collect();
        assert_eq!(recovered, expected);
        let disk_bytes = fs::metadata(&path).expect("retained history").len();
        assert!(disk_bytes > previous_bytes);
        append_us.sort_unstable();
        let percentile = |percent: usize| append_us[(append_us.len() - 1) * percent / 100];
        #[cfg(target_os = "linux")]
        let resident_kib = Some(
            fs::read_to_string("/proc/self/status")
                .expect("process memory")
                .lines()
                .find_map(|line| {
                    line.strip_prefix("VmRSS:")
                        .and_then(|value| value.split_whitespace().next())
                        .and_then(|value| value.parse::<u64>().ok())
                })
                .expect("resident memory"),
        );
        #[cfg(not(target_os = "linux"))]
        let resident_kib: Option<u64> = None;
        println!(
            "{}",
            serde_json::json!({
                "schema": "hepta.inference-control.single-writer-history.v1",
                "requests": count,
                "capacity": capacity,
                "append_samples": append_us.len(),
            "append_p50_us": percentile(/*percent*/ 50),
            "append_p95_us": percentile(/*percent*/ 95),
            "append_p99_us": percentile(/*percent*/ 99),
                "update_us": update_us,
                "recovery_us": recovery_us,
                "resident_kib": resident_kib,
                "disk_bytes": disk_bytes,
                "records_preserved": recovered.len(),
                "compaction_implemented": false,
                "concurrent_writers_implemented": false,
            })
        );
        previous_count = count;
        previous_bytes = disk_bytes;
    }
    let mut over_capacity = requests.get("history.0").expect("request template").clone();
    over_capacity.request_id = "history.capacity-overflow".into();
    assert_eq!(
        control.submit(/*now_ms*/ 100, over_capacity),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(
        fs::metadata(&path)
            .expect("bounded rejection preserves bytes")
            .len(),
        previous_bytes
    );
    drop(control);
    let bytes = fs::read(&path).expect("complete journal");
    fs::write(&path, &bytes[..bytes.len() - 1]).expect("inject incomplete durable tail");
    assert!(matches!(
        DurableInferenceControl::open(&path, capacity),
        Err(Error::CorruptJournal("incomplete line"))
    ));
    fs::write(&path, bytes).expect("restore original evidence");
    let restored = DurableInferenceControl::open(&path, capacity)
        .expect("recovery after restored complete bytes");
    assert!(restored.get("history.1023").is_some());
}
