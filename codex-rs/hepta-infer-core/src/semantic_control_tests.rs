use super::*;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::RetrievalSourceV1;
use crate::durable_control::native::NativeRequest;

static NONCE: AtomicU64 = AtomicU64::new(0);

struct JournalPath(PathBuf);

impl JournalPath {
    fn new() -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("time")
            .as_nanos();
        Self(std::env::temp_dir().join(format!(
            "hepta-semantic-{}-{stamp}-{nonce}.journal",
            std::process::id()
        )))
    }

    fn open(&self) -> DurableInferenceControl {
        DurableInferenceControl::open(&self.0, 32).expect("open existing owner journal")
    }
}

impl Drop for JournalPath {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
        let _ = fs::remove_file(self.0.with_extension("ready"));
    }
}

fn request(id: &str) -> SemanticRetrievalRequestV1 {
    SemanticRetrievalRequestV1 {
        operation_id: id.to_string(),
        workspace_id: "workspace.1".to_string(),
        generation: 3,
        objective_digest: "1".repeat(64),
        observation_digest: "2".repeat(64),
        bundle_digest: "3".repeat(64),
        deadline_ms: 9000,
        query: "q".to_string(),
        sources: vec![RetrievalSourceV1 {
            source_id: "source.1".to_string(),
            revision: 7,
            content_sha256: Digest32::of_bytes(b"alpha").to_string(),
            text: "alpha".to_string(),
        }],
    }
}

fn admission(id: &str) -> SemanticAdmissionV1 {
    SemanticAdmissionV1 {
        request_wire: request(id).encode().expect("request"),
        principal_id: "principal.1".to_string(),
        reservation_id: format!("reservation.{id}"),
        worker_id: "worker.1".to_string(),
        worker_generation: 3,
        maximum_tokens: 128,
        maximum_memory_bytes: 1024,
        authority_binding_digest: "4".repeat(64),
    }
}

fn completion(id: &str) -> SemanticCompletionV1 {
    let input = request(id);
    let mut reply = b"HPTARS\x01\x00".to_vec();
    reply.extend_from_slice(Digest32::of_bytes(&input.encode().expect("wire")).as_array());
    reply.extend_from_slice(&[0x33; 32]);
    reply.extend_from_slice(&2_u32.to_be_bytes());
    reply.extend_from_slice(&100_000_u32.to_be_bytes());
    reply.extend_from_slice(&900_000_u32.to_be_bytes());
    reply.extend_from_slice(&12_u64.to_be_bytes());
    reply.extend_from_slice(&0_u64.to_be_bytes());
    reply.extend_from_slice(&7_u64.to_be_bytes());
    input.decode_reply(&reply).expect("golden reply is valid");
    SemanticCompletionV1 {
        reply_wire: reply,
        observed_memory_bytes: Some(64),
    }
}

fn fenced(control: &mut DurableInferenceControl, id: &str) {
    let r = control
        .reserve_semantic(100, admission(id), 1)
        .expect("reserve");
    control
        .fence_semantic_dispatch(id, r.revision, 101)
        .expect("fence");
}

#[test]
fn full_result_reopens_and_replays_without_new_append() {
    let path = JournalPath::new();
    let expected;
    {
        let mut control = path.open();
        fenced(&mut control, "op.1");
        expected = control
            .complete_semantic("op.1", completion("op.1"))
            .expect("complete");
        assert!(expected.delivery_pending());
    }
    let mut control = path.open();
    assert_eq!(
        control.semantic_record("op.1").expect("lookup"),
        Some(&expected)
    );
    let bytes = fs::metadata(&path.0).expect("metadata").len();
    assert_eq!(
        control
            .reserve_semantic(10000, admission("op.1"), 1)
            .expect("audit replay"),
        expected
    );
    assert_eq!(
        control
            .complete_semantic("op.1", completion("op.1"))
            .expect("replay"),
        expected
    );
    assert_eq!(fs::metadata(&path.0).expect("metadata").len(), bytes);
}

#[test]
fn recovered_unknown_cannot_redispatch_stop_or_release_capacity() {
    let path = JournalPath::new();
    {
        let mut control = path.open();
        fenced(&mut control, "op.1");
    }
    let mut control = path.open();
    let old = control
        .reserve_semantic(100, admission("op.1"), 1)
        .expect("same admission");
    assert!(old.execution_unknown());
    assert!(
        control
            .fence_semantic_dispatch("op.1", old.revision, 102)
            .is_err()
    );
    assert!(
        control
            .stop_semantic_before_dispatch("op.1", "timeout".to_string())
            .is_err()
    );
    let cancelled = control.cancel_semantic("op.1").expect("cancel intent");
    assert!(cancelled.execution_unknown());
    assert_eq!(
        control.reserve_semantic(100, admission("op.2"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(control);
    assert!(
        path.open()
            .semantic_record("op.1")
            .expect("lookup")
            .expect("record")
            .execution_unknown()
    );
}

#[test]
fn cancellation_before_dispatch_is_terminal_negative_and_idempotent() {
    let path = JournalPath::new();
    let mut control = path.open();
    control
        .reserve_semantic(100, admission("op.1"), 1)
        .expect("reserve");
    let stopped = control.cancel_semantic("op.1").expect("cancel");
    assert_eq!(stopped.phase, SemanticPhaseV1::NotDispatched);
    assert_eq!(control.cancel_semantic("op.1").expect("repeat"), stopped);
    assert!(
        control
            .fence_semantic_dispatch("op.1", stopped.revision, 102)
            .is_err()
    );
    control
        .reserve_semantic(100, admission("op.2"), 1)
        .expect("freed slot");
}

#[test]
fn late_result_after_cancellation_preserves_truth_without_delivery() {
    let path = JournalPath::new();
    let mut control = path.open();
    fenced(&mut control, "op.1");
    control.cancel_semantic("op.1").expect("cancel intent");
    let observed = control
        .complete_semantic("op.1", completion("op.1"))
        .expect("late observed output");
    assert_eq!(observed.phase, SemanticPhaseV1::Completed);
    assert!(observed.cancel_requested);
    assert!(!observed.delivery_pending());
    assert_eq!(observed.completion, Some(completion("op.1")));
    control
        .reserve_semantic(100, admission("op.2"), 1)
        .expect("released observed slot");
}

#[test]
fn delivery_ack_reopens_without_erasing_full_output() {
    let path = JournalPath::new();
    let expected;
    {
        let mut control = path.open();
        fenced(&mut control, "op.1");
        control
            .complete_semantic("op.1", completion("op.1"))
            .expect("complete");
        expected = control
            .acknowledge_semantic_delivery("op.1", "5".repeat(64))
            .expect("ack");
    }
    let mut control = path.open();
    let replay = control
        .acknowledge_semantic_delivery("op.1", "5".repeat(64))
        .expect("same ack");
    assert_eq!(replay, expected);
    assert!(!replay.delivery_pending());
    assert_eq!(replay.completion, Some(completion("op.1")));
    assert_eq!(
        control.acknowledge_semantic_delivery("op.1", "6".repeat(64)),
        Err(Error::Conflict)
    );
}

#[test]
fn changed_semantics_cannot_reuse_operation_identity() {
    let path = JournalPath::new();
    let mut control = path.open();
    control
        .reserve_semantic(100, admission("op.1"), 1)
        .expect("reserve");
    let mut changes = Vec::new();
    let mut other = admission("op.1");
    other.principal_id = "principal.2".to_string();
    changes.push(other);
    let mut other = admission("op.1");
    other.reservation_id = "reservation.other".to_string();
    changes.push(other);
    let mut other = admission("op.1");
    other.maximum_tokens += 1;
    changes.push(other);
    let mut input = request("op.1");
    input.workspace_id = "workspace.2".to_string();
    let mut other = admission("op.1");
    other.request_wire = input.encode().expect("other input");
    changes.push(other);
    for changed in changes {
        assert_eq!(
            control.reserve_semantic(100, changed, 1),
            Err(Error::Conflict)
        );
    }
}

#[test]
fn semantic_ids_cannot_escape_through_legacy_or_native_profiles() {
    let path = JournalPath::new();
    let mut control = path.open();
    control
        .reserve_semantic(100, admission("op.1"), 1)
        .expect("reserve");
    assert!(control.get("op.1").is_none());
    assert_eq!(control.cancel("op.1", 1), Err(Error::Conflict));
    let marker = control
        .records
        .get("op.1")
        .expect("shared identity index")
        .request
        .clone();
    assert_eq!(control.submit(100, marker), Err(Error::Conflict));
    assert_eq!(
        control.reserve_native(
            NativeRequest {
                request_id: "op.1".to_string(),
                principal_id: "principal.1".to_string(),
                worker_generation: 3,
                model: "model".to_string(),
                payload_digest: "7".repeat(64),
            },
            1
        ),
        Err(Error::Conflict)
    );
}

#[test]
fn legacy_and_native_ids_cannot_be_reused_as_semantic() {
    let path = JournalPath::new();
    let mut control = path.open();
    control
        .reserve_native(
            NativeRequest {
                request_id: "op.1".to_string(),
                principal_id: "principal.1".to_string(),
                worker_generation: 3,
                model: "model".to_string(),
                payload_digest: "7".repeat(64),
            },
            1,
        )
        .expect("native admission");
    assert_eq!(
        control.reserve_semantic(100, admission("op.1"), 1),
        Err(Error::Conflict)
    );
    control
        .submit(
            100,
            InferenceRequest {
                request_id: "op.2".to_string(),
                principal_id: "principal.1".to_string(),
                model_digest: "3".repeat(64),
                payload_digest: "7".repeat(64),
                maximum_tokens: 128,
                deadline_ms: 9000,
                semantic_digest: "8".repeat(64),
            },
        )
        .expect("legacy admission");
    assert_eq!(
        control.reserve_semantic(100, admission("op.2"), 1),
        Err(Error::Conflict)
    );
}

#[test]
fn mismatched_result_keeps_dispatch_unknown() {
    let path = JournalPath::new();
    let mut control = path.open();
    fenced(&mut control, "op.1");
    assert!(
        control
            .complete_semantic("op.1", completion("op.2"))
            .is_err()
    );
    assert!(
        control
            .semantic_record("op.1")
            .expect("lookup")
            .expect("record")
            .execution_unknown()
    );
    control
        .complete_semantic("op.1", completion("op.1"))
        .expect("actual result");
    let mut changed = completion("op.1");
    changed.observed_memory_bytes = Some(65);
    assert_eq!(
        control.complete_semantic("op.1", changed),
        Err(Error::Conflict)
    );
}

#[test]
fn missing_or_excess_resources_do_not_erase_observed_completion() {
    for measurement in [None, Some(0), Some(1025)] {
        let path = JournalPath::new();
        let mut control = path.open();
        fenced(&mut control, "op.1");
        let mut observed = completion("op.1");
        observed.observed_memory_bytes = measurement;
        let result = control
            .complete_semantic("op.1", observed.clone())
            .expect("observed result");
        assert_eq!(result.phase, SemanticPhaseV1::Completed);
        assert_eq!(result.completion, Some(observed));
        assert!(!result.within_resource_budget);
        assert!(!result.delivery_pending());
        control
            .reserve_semantic(100, admission("op.2"), 1)
            .expect("released slot");
    }
}

#[test]
fn clock_rollback_expiry_and_changed_limits_reject_before_fence() {
    let path = JournalPath::new();
    let mut control = path.open();
    let reserved = control
        .reserve_semantic(100, admission("op.1"), 1)
        .expect("reserve");
    for now in [99, 9000, u64::MAX] {
        assert_eq!(
            control.fence_semantic_dispatch("op.1", reserved.revision, now),
            Err(Error::InvalidTime)
        );
    }
    assert_eq!(
        control.reserve_semantic(100, admission("op.1"), 2),
        Err(Error::Conflict)
    );
    control
        .fence_semantic_dispatch("op.1", reserved.revision, 101)
        .expect("current time");
}

#[test]
fn journal_record_capacity_is_shared_across_profiles() {
    let path = JournalPath::new();
    let mut control = DurableInferenceControl::open(&path.0, 1).expect("one record");
    control
        .reserve_semantic(100, admission("op.1"), 1)
        .expect("reserve");
    control
        .cancel_semantic("op.1")
        .expect("terminal retains identity");
    assert_eq!(
        control.reserve_semantic(100, admission("op.2"), 1),
        Err(Error::CapacityExceeded)
    );
    assert!(
        control
            .reserve_native(
                NativeRequest {
                    request_id: "op.2".to_string(),
                    principal_id: "principal.1".to_string(),
                    worker_generation: 3,
                    model: "model".to_string(),
                    payload_digest: "7".repeat(64),
                },
                1
            )
            .is_err()
    );
}

#[test]
fn writer_lock_is_shared_and_released_only_with_owner() {
    let path = JournalPath::new();
    let mut control = path.open();
    control
        .reserve_semantic(100, admission("op.1"), 1)
        .expect("reserve");
    assert!(matches!(
        DurableInferenceControl::open(&path.0, 32),
        Err(Error::WriterUnavailable)
    ));
    drop(control);
    assert!(
        path.open()
            .semantic_record("op.1")
            .expect("lookup")
            .is_some()
    );
}

#[test]
fn incomplete_result_tail_never_restores_dispatch_permission() {
    let original = JournalPath::new();
    {
        let mut control = original.open();
        fenced(&mut control, "op.1");
    }
    let prefix = fs::read(&original.0).expect("read fenced journal");
    {
        let mut control = original.open();
        control
            .complete_semantic("op.1", completion("op.1"))
            .expect("complete");
    }
    let full = fs::read(&original.0).expect("full journal");
    let tail = &full[prefix.len()..];
    for length in [0, 1, tail.len() / 2, tail.len() - 1] {
        let path = JournalPath::new();
        fs::write(&path.0, [&prefix[..], &tail[..length]].concat()).expect("truncated copy");
        if length == 0 {
            assert!(
                path.open()
                    .semantic_record("op.1")
                    .expect("lookup")
                    .expect("record")
                    .execution_unknown()
            );
        } else {
            assert!(DurableInferenceControl::open(&path.0, 32).is_err());
        }
    }
}

#[test]
fn write_failure_poison_prevents_cached_success_or_new_admission() {
    let path = JournalPath::new();
    let mut control = path.open();
    fenced(&mut control, "op.1");
    // Retain the original locked handle while substituting a read-only FD to
    // inject a real write error. This is not a power-loss or fsync fault test.
    let _lock = control.file.try_clone().expect("retain lock");
    control.file = fs::File::open(&path.0).expect("read-only handle");
    assert!(matches!(
        control.complete_semantic("op.1", completion("op.1")),
        Err(Error::Io(_))
    ));
    assert_eq!(
        control.semantic_record("op.1"),
        Err(Error::WriterUnavailable)
    );
    assert_eq!(
        control.reserve_semantic(100, admission("op.2"), 1),
        Err(Error::WriterUnavailable)
    );
}

#[test]
fn remaining_result_space_cannot_be_consumed_by_unrelated_append() {
    let path = JournalPath::new();
    let mut control = path.open();
    fenced(&mut control, "op.1");
    // Test the pre-write byte admission boundary without allocating 64 MiB.
    control.journal_bytes = super::super::MAX_JOURNAL_BYTES - FUTURE_RECORD_BYTES;
    assert_eq!(control.append("\n"), Err(Error::CapacityExceeded));
    let completed = control
        .complete_semantic("op.1", completion("op.1"))
        .expect("reserved result room");
    assert_eq!(completed.phase, SemanticPhaseV1::Completed);
}

#[test]
fn completed_unacknowledged_delivery_keeps_its_own_headroom() {
    let path = JournalPath::new();
    let mut control = path.open();
    fenced(&mut control, "op.1");
    control
        .complete_semantic("op.1", completion("op.1"))
        .expect("complete");
    assert_eq!(control.semantic.pending_result_bytes(), DELIVERY_ACK_BYTES);
    control.journal_bytes = super::super::MAX_JOURNAL_BYTES - DELIVERY_ACK_BYTES;
    assert_eq!(control.append("\n"), Err(Error::CapacityExceeded));
    control
        .acknowledge_semantic_delivery("op.1", "5".repeat(64))
        .expect("reserved ack room");
    assert_eq!(control.semantic.pending_result_bytes(), 0);
}

#[test]
fn reused_reservation_cannot_hide_a_second_operation() {
    let path = JournalPath::new();
    let mut control = path.open();
    control
        .reserve_semantic(100, admission("op.1"), 2)
        .expect("reserve");
    let mut other = admission("op.2");
    other.reservation_id = admission("op.1").reservation_id;
    assert_eq!(
        control.reserve_semantic(100, other, 2),
        Err(Error::Conflict)
    );
}

#[test]
fn legacy_event_cannot_reinterpret_a_semantic_identity_during_replay() {
    let path = JournalPath::new();
    {
        let mut control = path.open();
        control
            .reserve_semantic(100, admission("op.1"), 1)
            .expect("reserve");
    }
    let mut file = fs::OpenOptions::new()
        .append(true)
        .open(&path.0)
        .expect("fault injector");
    file.write_all(b"cancel|op.1|1\n")
        .expect("inject incompatible event");
    file.sync_all().expect("sync");
    assert!(DurableInferenceControl::open(&path.0, 32).is_err());
}

#[cfg(unix)]
#[test]
#[ignore = "invoked only by the forced-termination parent with explicit test input"]
fn semantic_crash_child() {
    let path = PathBuf::from(std::env::var_os("HEPTA_SEMANTIC_CRASH_PATH").expect("test path"));
    let phase = std::env::var("HEPTA_SEMANTIC_CRASH_PHASE").expect("test phase");
    let mut control = DurableInferenceControl::open(&path, 32).expect("child owner");
    control
        .reserve_semantic(100, admission("op.1"), 1)
        .expect("child reserve");
    if phase != "reserved" {
        control
            .fence_semantic_dispatch("op.1", 1, 101)
            .expect("child fence");
    }
    if phase == "completed" || phase == "acknowledged" {
        control
            .complete_semantic("op.1", completion("op.1"))
            .expect("child complete");
    }
    if phase == "acknowledged" {
        control
            .acknowledge_semantic_delivery("op.1", "5".repeat(64))
            .expect("child ack");
    }
    let mut ready = fs::File::create(path.with_extension("ready")).expect("barrier");
    ready.write_all(b"ready").expect("barrier write");
    ready.sync_all().expect("barrier sync");
    loop {
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

#[cfg(unix)]
#[test]
fn forced_process_termination_preserves_each_committed_boundary() {
    use std::process::Command;
    use std::process::Stdio;
    use std::time::Duration;
    use std::time::Instant;
    struct ChildGuard(std::process::Child);
    impl Drop for ChildGuard {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    for phase in ["reserved", "fenced", "completed", "acknowledged"] {
        let path = JournalPath::new();
        let mut child = ChildGuard(
            Command::new(std::env::current_exe().expect("test executable"))
                .args([
                    "--exact",
                    "durable_control::semantic::tests::semantic_crash_child",
                    "--ignored",
                    "--nocapture",
                ])
                .env("HEPTA_SEMANTIC_CRASH_PATH", &path.0)
                .env("HEPTA_SEMANTIC_CRASH_PHASE", phase)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .expect("spawn real owner"),
        );
        let started = Instant::now();
        while !path.0.with_extension("ready").exists() {
            assert!(
                started.elapsed() < Duration::from_secs(10),
                "child barrier timeout: {phase}"
            );
            assert!(
                child.0.try_wait().expect("status").is_none(),
                "child exited before barrier"
            );
            std::thread::sleep(Duration::from_millis(10));
        }
        child.0.kill().expect("SIGKILL child owner");
        assert!(!child.0.wait().expect("wait for death").success());
        let mut control = path.open();
        let recovered = control
            .semantic_record("op.1")
            .expect("lookup")
            .expect("record")
            .clone();
        match phase {
            "reserved" => {
                control
                    .fence_semantic_dispatch("op.1", recovered.revision, 102)
                    .expect("first dispatch");
            }
            "fenced" => {
                assert!(recovered.execution_unknown());
                assert!(
                    control
                        .fence_semantic_dispatch("op.1", recovered.revision, 102)
                        .is_err()
                );
            }
            "completed" => {
                assert_eq!(recovered.completion, Some(completion("op.1")));
                assert!(recovered.delivery_pending());
            }
            "acknowledged" => {
                assert_eq!(recovered.delivery_ack_digest, Some("5".repeat(64)));
                assert!(!recovered.delivery_pending());
            }
            _ => panic!("unexpected test phase"),
        }
    }
}

/// Explicit opt-in storage measurement, not a model or post-compaction result.
#[test]
#[ignore = "real fsync/reopen growth measurement selected explicitly by maintenance CI"]
fn semantic_journal_retained_history_curve() {
    use std::time::Instant;
    let path = JournalPath::new();
    let mut previous = 0;
    let mut previous_bytes = 0;
    let mut curve = Vec::new();
    for count in [64, 256, 1024] {
        let mut control = DurableInferenceControl::open(&path.0, 2048).expect("owner");
        let started = Instant::now();
        for index in previous..count {
            let id = format!("measured.{index}");
            fenced(&mut control, &id);
            control
                .complete_semantic(&id, completion(&id))
                .expect("observed result");
            control
                .acknowledge_semantic_delivery(&id, "5".repeat(64))
                .expect("ack");
        }
        let append_us = started.elapsed().as_micros();
        drop(control);
        let bytes = fs::metadata(&path.0).expect("journal length").len();
        assert!(bytes > previous_bytes);
        let started = Instant::now();
        let mut control = DurableInferenceControl::open(&path.0, 2048).expect("reopen");
        let reopen_us = started.elapsed().as_micros();
        for index in 0..count {
            let id = format!("measured.{index}");
            let recovered = control
                .reserve_semantic(10000, admission(&id), 1)
                .expect("replay");
            assert_eq!(recovered.phase, SemanticPhaseV1::Completed);
            assert_eq!(recovered.completion, Some(completion(&id)));
            assert_eq!(recovered.delivery_ack_digest, Some("5".repeat(64)));
            assert!(!recovered.delivery_pending());
            assert!(!recovered.execution_unknown());
        }
        assert_eq!(fs::metadata(&path.0).expect("replay length").len(), bytes);
        drop(control);
        curve.push(serde_json::json!({
            "retained_records": count, "new_records": count - previous,
            "journal_bytes": bytes, "append_and_fsync_us": append_us,
            "reopen_us": reopen_us, "all_results_replayed": true,
            "replay_appended_bytes": 0
        }));
        previous = count;
        previous_bytes = bytes;
    }
    println!(
        "HEPTA_SEMANTIC_GROWTH={}",
        serde_json::json!({
            "schema": "hepta.semantic-journal.growth.v1", "curve": curve,
            "compaction_performed": false, "model_executed": false,
            "long_term_slo_established": false
        })
    );
}
