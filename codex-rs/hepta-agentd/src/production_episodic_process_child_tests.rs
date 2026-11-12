use codex_hepta_contracts::Sha256Digest;

use super::ACK;
use super::ObservedChild;

#[test]
fn imported_ack_requires_successful_original_process_exit_and_exact_input() {
    let body = serde_json::json!({"authority_id": "fixture-authority", "namespace": "bridge-fixture", "generation": 1, "records": ["fixture-record"]});
    let snapshot_sha256 = super::super::super::canonical_digest(&body).expect("canonical fixture");
    let snapshot = serde_json::json!({"body": body, "sha256": snapshot_sha256}).to_string();
    let ack = serde_json::json!({
        "schema": "hepta.mem15.import-ack.v1", "pid": 123,
        "snapshot_sha256": Sha256Digest::for_bytes(snapshot.as_bytes()).as_str(),
        "imported": {"active_records": 1, "authority_id": body["authority_id"],
            "namespace": body["namespace"], "generation": body["generation"],
            "snapshot_sha256": snapshot_sha256},
    });
    let mut observed = ObservedChild {
        receipt: serde_json::json!({"pid": 123, "exit_code": 0, "timed_out": false}),
        stdout: format!("running one child\n{ACK}{ack}\nchild passed\n"),
        stderr: String::new(),
    };
    assert!(observed.import_ack(&snapshot).is_ok());
    assert!(observed.import_ack("different snapshot").is_err());
    for receipt in [
        serde_json::json!({"pid": 124, "exit_code": 0, "timed_out": false}),
        serde_json::json!({"pid": 123, "exit_code": 1, "timed_out": false}),
        serde_json::json!({"pid": 123, "exit_code": 0, "timed_out": true}),
        serde_json::json!({"pid": 123, "exit_code": null, "timed_out": false}),
    ] {
        observed.receipt = receipt;
        assert!(observed.import_ack(&snapshot).is_err());
    }
    observed.receipt = serde_json::json!({"pid": 123, "exit_code": 0, "timed_out": false});
    for field in ["authority_id", "namespace", "generation", "snapshot_sha256"] {
        let mut wrong = ack.clone();
        wrong["imported"][field] = serde_json::json!("wrong owner receipt identity");
        observed.stdout = format!("{ACK}{wrong}\n");
        assert!(observed.import_ack(&snapshot).is_err());
    }
}

#[test]
fn missing_or_repeated_ack_cannot_start_c() {
    for stdout in [String::new(), format!("{ACK}{{}}\n{ACK}{{}}\n")] {
        let observed = ObservedChild {
            receipt: serde_json::json!({"pid": 123, "exit_code": 0, "timed_out": false}),
            stdout,
            stderr: String::new(),
        };
        assert!(observed.import_ack("snapshot").is_err());
    }
}
