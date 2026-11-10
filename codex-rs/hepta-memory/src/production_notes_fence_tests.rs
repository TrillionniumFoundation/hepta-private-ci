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

#[test]
fn notes_fence_proof_binds_original_cancel_and_committed_event() {
    let original = serde_json::json!({
        "schema_version": 1,
        "action": "replace_note",
        "operation_id": "original",
        "destination_id": target().destination_id(),
        "target": target(),
        "expected_revision": 7,
        "text": "late text"
    })
    .to_string();
    let cancellation = serde_json::json!({
        "schema_version": 1,
        "action": "fence_note_operation",
        "operation_id": "cancel",
        "destination_id": target().destination_id(),
        "target": target(),
        "original_operation_id": "original",
        "original_payload_sha256": Sha256Digest::for_bytes(original.as_bytes()).as_str(),
        "expected_revision": 7
    })
    .to_string();
    let receipt = serde_json::json!({
        "schema_version": 1,
        "target": target(),
        "operation_id": "cancel",
        "payload_sha256": Sha256Digest::for_bytes(cancellation.as_bytes()).as_str(),
        "result": {
            "status": "fenced",
            "original_operation_id": "original",
            "original_payload_sha256": Sha256Digest::for_bytes(original.as_bytes()).as_str(),
            "previous_revision": 7,
            "revision": 8,
            "text_sha256": Sha256Digest::for_bytes(b"").as_str()
        }
    })
    .to_string();
    let terminal_sha = Sha256Digest::for_bytes(b"terminal-event");
    let proof = NotesFenceProof::from_committed_event(
        "original",
        &original,
        "cancel",
        &cancellation,
        "event-4",
        &terminal_sha,
        &receipt,
    )
    .unwrap();
    let settlement = proof.settlement_json().unwrap();
    verify_fence_settlement(
        &settlement,
        "original",
        &original,
        "cancel",
        &cancellation,
        "event-4",
        &terminal_sha,
        &receipt,
    )
    .unwrap();

    let mut changed: serde_json::Value = serde_json::from_str(&settlement).unwrap();
    changed["cancellation_terminal_event_id"] = serde_json::json!("event-5");
    assert!(
        verify_fence_settlement(
            &changed.to_string(),
            "original",
            &original,
            "cancel",
            &cancellation,
            "event-4",
            &terminal_sha,
            &receipt,
        )
        .is_err()
    );
    let mut changed_receipt: serde_json::Value = serde_json::from_str(&receipt).unwrap();
    changed_receipt["result"]["original_operation_id"] = serde_json::json!("another");
    assert!(
        NotesFenceProof::from_committed_event(
            "original",
            &original,
            "cancel",
            &cancellation,
            "event-4",
            &terminal_sha,
            &changed_receipt.to_string(),
        )
        .is_err()
    );
}
