use codex_hepta_contracts::Sha256Digest;

use super::ACK;
use super::ObservedChild;

#[test]
fn imported_ack_requires_successful_original_process_exit_and_exact_input() {
    let snapshot = "original bounded snapshot";
    let ack = serde_json::json!({
        "schema": "hepta.mem15.import-ack.v1", "pid": 123,
        "snapshot_sha256": Sha256Digest::for_bytes(snapshot.as_bytes()).as_str(),
        "imported": {"active_records": 1},
    });
    let mut observed = ObservedChild {
        receipt: serde_json::json!({"pid": 123, "exit_code": 0, "timed_out": false}),
        stdout: format!("running one child\n{ACK}{ack}\nchild passed\n"),
        stderr: String::new(),
    };
    assert!(observed.import_ack(snapshot).is_ok());
    assert!(observed.import_ack("different snapshot").is_err());
    for receipt in [
        serde_json::json!({"pid": 124, "exit_code": 0, "timed_out": false}),
        serde_json::json!({"pid": 123, "exit_code": 1, "timed_out": false}),
        serde_json::json!({"pid": 123, "exit_code": 0, "timed_out": true}),
        serde_json::json!({"pid": 123, "exit_code": null, "timed_out": false}),
    ] {
        observed.receipt = receipt;
        assert!(observed.import_ack(snapshot).is_err());
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
