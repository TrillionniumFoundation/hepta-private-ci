use super::*;
use pretty_assertions::assert_eq;

fn target() -> NotesTargetIdentity {
    NotesTargetIdentity { session_instance: "a".repeat(32), task_id: 1, incarnation: "b".repeat(32) }
}

fn payload() -> String {
    serde_json::json!({"schema_version":1,"action":"fence_note_operation","operation_id":"cancel",
        "destination_id":target().destination_id(),"target":target(),"original_operation_id":"original",
        "original_payload_sha256":"c".repeat(64),"expected_revision":7}).to_string()
}

fn receipt() -> serde_json::Value {
    serde_json::json!({"schema_version":1,"target":target(),"operation_id":"cancel",
        "payload_sha256":Sha256Digest::for_bytes(payload().as_bytes()).as_str(),
        "result":{"status":"fenced","original_operation_id":"original","original_payload_sha256":"c".repeat(64),
        "previous_revision":7,"revision":8,"text_sha256":"d".repeat(64)}})
}

#[test]
fn notes_fence_terminal_receipt_requires_exact_original_binding() {
    let good = receipt();
    let checked = NotesTerminalReceipt::from_json(&payload(), &good.to_string()).unwrap();
    assert_eq!(checked.outcome(), crate::LocalReconcileOutcome::Committed);
    assert_eq!(checked.document_state().unwrap(), (target(), 8, Sha256Digest::parse(&"d".repeat(64)).unwrap()));
    for (key, value) in [("original_operation_id", serde_json::json!("another")),
        ("original_payload_sha256", serde_json::json!("e".repeat(64))),
        ("previous_revision", serde_json::json!(6)), ("revision", serde_json::json!(9)),
        ("text_sha256", serde_json::json!("bad"))]
    {
        let mut changed = good.clone(); changed["result"][key] = value;
        assert!(NotesTerminalReceipt::from_json(&payload(), &changed.to_string()).is_err());
    }
    let mut changed = good;
    changed["payload_sha256"] = serde_json::json!("0".repeat(64));
    assert!(NotesTerminalReceipt::from_json(&payload(), &changed.to_string()).is_err());
}
