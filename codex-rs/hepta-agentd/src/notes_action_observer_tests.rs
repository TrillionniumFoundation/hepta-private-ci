//! Goal/receipt correctness. The production owner/status assembly integration
//! and its explicit application-model peer live in production_notes_host_tests.
use super::*;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn fixture() -> (ProductionRetainedOperation, String, NotesDocumentState) {
    let target = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let payload = json!({"schema_version":1,"action":"replace_note",
        "operation_id":"notes-act2-original","destination_id":target.destination_id(),
        "target":target,"expected_revision":7,"text":"saved original text"})
    .to_string();
    let operation = notes_operation_intent(
        &target,
        &payload,
        StableId::new("notes-owner").unwrap(),
        Generation::new(1).unwrap(),
    )
    .unwrap();
    let current = NotesDocumentState {
        target: target.clone(),
        revision: 8,
        text_sha256: Sha256Digest::for_bytes(b"saved original text"),
        receipt_pending: false,
    };
    let receipt = json!({"schema_version":1,"target":target,
        "operation_id":"notes-act2-original","payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()),
        "result":{"status":"applied","previous_revision":7,"revision":8,
            "text_sha256":current.text_sha256}}).to_string();
    (
        ProductionRetainedOperation {
            operation,
            topic: NOTES_REPLACE_TOPIC_V1.into(),
            payload_json: payload,
            state: LocalOutcomeState::Committed,
        },
        receipt,
        current,
    )
}

fn status_value(
    original: &ProductionRetainedOperation,
    receipt: Option<&str>,
    current: Option<&NotesDocumentState>,
) -> Value {
    original_notes_status(
        original,
        receipt,
        current,
        /*request_sha256*/ None,
        json!({"kind":"original_core_dynamic_tool"}),
        /*sender_observation_retained*/ None,
    )
    .unwrap()
}

#[test]
fn notes_act2_tool_success_requires_current_goal_after_readback_loss_or_drift() {
    let (original, receipt, current) = fixture();
    let succeeded = status_value(&original, Some(&receipt), Some(&current));
    for tool in [
        crate::notes_thread_tool::REPLACE_TOOL,
        crate::notes_thread_tool::STATUS_TOOL,
    ] {
        assert!(original_notes_tool_succeeded(tool, &succeeded));
        let mut later_revision = current.clone();
        later_revision.revision += 1;
        let mut changed_text = current.clone();
        changed_text.text_sha256 = Sha256Digest::for_bytes(b"later text");
        let mut older_revision = current.clone();
        older_revision.revision -= 1;
        for document in [
            None,
            Some(later_revision),
            Some(changed_text),
            Some(older_revision),
        ] {
            let unresolved = status_value(&original, Some(&receipt), document.as_ref());
            // These historical fields are deliberately identical to the
            // positive control. They used to set the tool success bit alone.
            assert_eq!(
                (
                    &unresolved["state"],
                    &unresolved["receipt_utf8"],
                    &unresolved["action_observation"]["historical_effect"]
                ),
                (
                    &succeeded["state"],
                    &succeeded["receipt_utf8"],
                    &succeeded["action_observation"]["historical_effect"]
                )
            );
            assert!(!original_notes_tool_succeeded(tool, &unresolved));
        }
        let no_receipt = status_value(&original, /*receipt*/ None, Some(&current));
        assert!(!original_notes_tool_succeeded(tool, &no_receipt));
        let mut pending_receipt = current.clone();
        pending_receipt.receipt_pending = true;
        assert!(original_notes_tool_succeeded(
            tool,
            &status_value(&original, Some(&receipt), Some(&pending_receipt))
        ));
    }
}

#[test]
fn notes_act2_tool_success_keeps_read_and_original_navigation_semantics() {
    let (mut original, receipt, current) = fixture();
    let succeeded = status_value(&original, Some(&receipt), Some(&current));
    for tool in [
        crate::notes_thread_tool::REPLACE_TOOL,
        crate::notes_thread_tool::STATUS_TOOL,
    ] {
        for (field, flag) in [
            ("write_admission", "refused_later_replace_in_original_turn"),
            ("status", "unknown"),
        ] {
            let mut refused = succeeded.clone();
            refused[field] = json!(flag);
            assert!(!original_notes_tool_succeeded(tool, &refused));
        }
        let mut missing_goal = succeeded.clone();
        missing_goal
            .as_object_mut()
            .unwrap()
            .remove("action_observation");
        assert!(!original_notes_tool_succeeded(tool, &missing_goal));
        original.state = LocalOutcomeState::Indeterminate;
        assert!(!original_notes_tool_succeeded(
            tool,
            &status_value(&original, Some(&receipt), Some(&current))
        ));
    }
    let mut read = json!({"document":NotesActionDocumentV1::from(&current)});
    assert!(original_notes_tool_succeeded(
        crate::notes_thread_tool::READ_TOOL,
        &read
    ));
    read["status"] = json!("unknown");
    assert!(!original_notes_tool_succeeded(
        crate::notes_thread_tool::READ_TOOL,
        &read
    ));
    assert!(!original_notes_tool_succeeded("unregistered_tool", &succeeded));
}

#[test]
fn notes_act2_success_requires_original_receipt_and_exact_current_goal() {
    let (original, receipt, current) = fixture();
    assert_eq!(
        serde_json::to_value(NotesActionDocumentV1::from(&current)).unwrap(),
        json!({"target":current.target,"revision":current.revision,
            "text_sha256":current.text_sha256.as_str(),"receipt_pending":current.receipt_pending})
    );
    let observed = observe_notes_action(&original, Some(&receipt), Some(&current)).unwrap();
    assert_eq!(
        observed,
        NotesActionObservationV1 {
            schema_version: 1,
            operation_id: "notes-act2-original".into(),
            payload_sha256: Sha256Digest::for_bytes(original.payload_json.as_bytes()),
            original_target: current.target.clone(),
            expected_revision: 7,
            goal_revision: Some(8),
            expected_text_sha256: current.text_sha256.clone(),
            historical_effect: HistoricalNotesEffectV1::Applied,
            terminal_receipt_sha256: Some(Sha256Digest::for_bytes(receipt.as_bytes())),
            current_document: Some(NotesActionDocumentV1::from(&current)),
            current_goal: ActionGoalStateV1::Satisfied,
            runtime_state: ActionRuntimeStateV1::Terminal {
                outcome: ActionTerminalOutcomeV1::Succeeded
            },
        }
    );
    let no_receipt = observe_notes_action(&original, /*receipt*/ None, Some(&current)).unwrap();
    assert_eq!(
        (
            no_receipt.runtime_state,
            no_receipt.current_goal,
            no_receipt.historical_effect
        ),
        (
            ActionRuntimeStateV1::Unknown,
            ActionGoalStateV1::Satisfied,
            HistoricalNotesEffectV1::Unknown
        )
    );
}

#[test]
fn notes_act2_readback_loss_drift_and_regression_preserve_history_without_success() {
    let (original, receipt, mut current) = fixture();
    let unavailable = observe_notes_action(&original, Some(&receipt), /*current*/ None).unwrap();
    assert_eq!(
        (
            unavailable.runtime_state,
            unavailable.current_goal,
            unavailable.historical_effect
        ),
        (
            ActionRuntimeStateV1::Unknown,
            ActionGoalStateV1::Unknown,
            HistoricalNotesEffectV1::Applied
        )
    );
    for (revision, incarnation, text, expected) in [
        (8, "3", "saved original text", ActionGoalStateV1::Unknown),
        (7, "2", "saved original text", ActionGoalStateV1::Unknown),
        (
            9,
            "2",
            "saved original text",
            ActionGoalStateV1::Unsatisfied,
        ),
        (8, "2", "later text", ActionGoalStateV1::Unsatisfied),
    ] {
        current.revision = revision;
        current.target.incarnation = incarnation.repeat(32);
        current.text_sha256 = Sha256Digest::for_bytes(text.as_bytes());
        let observed = observe_notes_action(&original, Some(&receipt), Some(&current)).unwrap();
        assert_eq!(
            (
                observed.runtime_state,
                observed.current_goal,
                observed.historical_effect
            ),
            (
                ActionRuntimeStateV1::Unknown,
                expected,
                HistoricalNotesEffectV1::Applied
            )
        );
        assert_eq!(
            observed.terminal_receipt_sha256,
            unavailable.terminal_receipt_sha256
        );
    }
}

#[test]
fn notes_act2_receipt_retirement_is_not_waiting_input_and_source_state_is_not_evidence() {
    let (mut original, receipt, mut current) = fixture();
    // Source and receipt are separate reads; a later valid receipt can arrive
    // after an earlier Indeterminate source snapshot.
    original.state = LocalOutcomeState::Indeterminate;
    current.receipt_pending = true;
    assert_eq!(
        observe_notes_action(&original, Some(&receipt), Some(&current))
            .unwrap()
            .runtime_state,
        ActionRuntimeStateV1::Terminal {
            outcome: ActionTerminalOutcomeV1::Succeeded
        }
    );
    original.state = LocalOutcomeState::Committed;
    assert_eq!(
        observe_notes_action(&original, /*receipt*/ None, Some(&current))
            .unwrap()
            .runtime_state,
        ActionRuntimeStateV1::Unknown
    );
    for state in [LocalOutcomeState::Rejected, LocalOutcomeState::RolledBack] {
        original.state = state;
        let contradictory =
            observe_notes_action(&original, Some(&receipt), Some(&current)).unwrap();
        assert_eq!(
            (
                contradictory.runtime_state,
                contradictory.current_goal,
                contradictory.historical_effect
            ),
            (
                ActionRuntimeStateV1::Unknown,
                ActionGoalStateV1::Satisfied,
                HistoricalNotesEffectV1::Applied
            )
        );
    }
}

#[test]
fn notes_act2_changed_operation_and_receipt_bindings_are_refused() {
    let (mut original, receipt, current) = fixture();
    for (pointer, value) in [
        ("/schema_version", json!(2)),
        ("/operation_id", json!("another-operation")),
        ("/target/incarnation", json!("3".repeat(32))),
        ("/payload_sha256", json!("0".repeat(64))),
        ("/result/previous_revision", json!(6)),
        ("/result/revision", json!(9)),
        ("/result/text_sha256", json!("0".repeat(64))),
        ("/result/status", json!("unknown")),
    ] {
        let mut changed: Value = serde_json::from_str(&receipt).unwrap();
        *changed.pointer_mut(pointer).unwrap() = value;
        assert!(
            observe_notes_action(&original, Some(&changed.to_string()), Some(&current)).is_err(),
            "{pointer}"
        );
    }
    original.topic = "another.topic".into();
    assert!(observe_notes_action(&original, Some(&receipt), Some(&current)).is_err());
    original.topic = NOTES_REPLACE_TOPIC_V1.into();
    original.payload_json = original
        .payload_json
        .replace("saved original text", "changed text");
    assert!(observe_notes_action(&original, Some(&receipt), Some(&current)).is_err());
}

#[test]
fn notes_act2_old_nonapplication_receipt_is_not_a_rejection_tombstone() {
    let (mut original, receipt, mut current) = fixture();
    original.state = LocalOutcomeState::Rejected;
    current.revision = 7;
    let mut rejected: Value = serde_json::from_str(&receipt).unwrap();
    for reason in [
        "revision_conflict",
        "operation_conflict",
        "revision_exhausted",
        "target_mismatch",
        "ui_deadline_elapsed",
        "receipt_pending",
    ] {
        rejected["result"] = json!({"status":"not_applied","reason":reason,"current_revision":7});
        let observed =
            observe_notes_action(&original, Some(&rejected.to_string()), Some(&current)).unwrap();
        assert_eq!(
            (
                observed.runtime_state,
                observed.current_goal,
                observed.historical_effect
            ),
            (
                ActionRuntimeStateV1::Unknown,
                ActionGoalStateV1::Unsatisfied,
                HistoricalNotesEffectV1::NotApplied
            )
        );
    }
    rejected["result"]["reason"] = json!("unrecognized_reason");
    assert!(observe_notes_action(&original, Some(&rejected.to_string()), Some(&current)).is_err());
}
