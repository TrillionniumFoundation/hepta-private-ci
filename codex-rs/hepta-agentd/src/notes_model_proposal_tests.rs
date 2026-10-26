use super::*;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::NotesTargetIdentity;
use pretty_assertions::assert_eq;

fn route() -> AgentdNotesModelRoute {
    AgentdNotesModelRoute {
        thread_id: "thread-original".into(),
        app_server_session_id: "session-original".into(),
        principal_scope_digest: Digest32::of_bytes(b"fixture principal scope"),
        registered_tool_schema_sha256: Digest32::of_bytes(
            AgentdNotesModelRoute::TOOL_DEFINITION_JSON.as_bytes(),
        ),
    }
}

fn params() -> DynamicToolCallParams {
    DynamicToolCallParams {
        thread_id: "thread-original".into(),
        turn_id: "turn-original".into(),
        call_id: "call-original".into(),
        namespace: Some(NOTES_MODEL_NAMESPACE.into()),
        tool: NOTES_MODEL_TOOL.into(),
        arguments: json!({"text":"待确认的模型原文"}),
    }
}

fn reviewed() -> NotesDocumentState {
    NotesDocumentState {
        target: NotesTargetIdentity {
            session_instance: "1".repeat(32),
            task_id: 7,
            incarnation: "2".repeat(32),
        },
        revision: 3,
        text_sha256: Sha256Digest::for_bytes(b"original predecessor"),
        receipt_pending: false,
    }
}

#[test]
fn model_proposal_changed_arguments_keep_original_effect_id_but_change_confirmation() {
    let original = params();
    let id = proposal_id("owner-original", &route(), &original).unwrap();
    let view = proposal_view(id.clone(), &original, Some(&reviewed())).unwrap();
    let mut changed = original.clone();
    changed.arguments = json!({"text":"changed replacement"});
    assert_eq!(
        proposal_id("owner-original", &route(), &changed).unwrap(),
        id
    );
    assert_ne!(
        proposal_view(id.clone(), &changed, Some(&reviewed()))
            .unwrap()
            .proposal_sha256,
        view.proposal_sha256
    );
    changed.call_id = "another-call".into();
    assert_ne!(
        proposal_id("owner-original", &route(), &changed).unwrap(),
        id
    );
    assert_ne!(
        proposal_id("another-owner", &route(), &original).unwrap(),
        id
    );
    let mut moved = route();
    moved.app_server_session_id = "another-session".into();
    assert_ne!(
        proposal_id("owner-original", &moved, &original).unwrap(),
        id
    );
    let mut wrong_route = original;
    wrong_route.thread_id = "another-thread".into();
    assert!(proposal_id("owner-original", &route(), &wrong_route).is_err());
}

#[test]
fn model_preview_digest_binds_each_predecessor_field_and_cannot_confirm_recovery() {
    let params = params();
    let id = proposal_id("owner-original", &route(), &params).unwrap();
    let original = proposal_view(id.clone(), &params, Some(&reviewed())).unwrap();
    for field in ["target", "revision", "text", "receipt"] {
        let mut changed = reviewed();
        match field {
            "target" => changed.target.task_id += 1,
            "revision" => changed.revision += 1,
            "text" => changed.text_sha256 = Sha256Digest::for_bytes(b"concurrent edit"),
            "receipt" => changed.receipt_pending = true,
            _ => unreachable!(),
        }
        assert_ne!(
            proposal_view(id.clone(), &params, Some(&changed))
                .unwrap()
                .proposal_sha256,
            original.proposal_sha256
        );
    }
    let recovered = proposal_view(id, &params, /*reviewed*/ None).unwrap();
    assert_eq!(recovered.phase, NotesModelPhase::Retained);
    assert_eq!(recovered.reviewed_document, None);
    assert_ne!(recovered.proposal_sha256, original.proposal_sha256);
    assert!(unresolved_response(&recovered, "original-run", NotesModelResult::Applied).is_err());
    assert!(unresolved_response(&recovered, "original-run", NotesModelResult::Rejected).is_err());
    assert!(
        !unresolved_response(&recovered, "original-run", NotesModelResult::Unknown)
            .unwrap()
            .success
    );
}

#[test]
fn model_arguments_are_literal_bounded_utf8_and_cannot_select_authority() {
    let mut call = params();
    call.arguments = json!({"text":"literal\n原文"});
    assert_eq!(proposed_text(&call).unwrap(), "literal\n原文");
    call.arguments = json!({"text":"x", "target":"replacement"});
    assert!(proposed_text(&call).is_err());
    call.arguments = json!({"text":" \n\t"});
    assert!(proposed_text(&call).is_err());
    call.arguments = json!({"text":"中".repeat(1366)});
    assert!(proposed_text(&call).is_err());
}

#[test]
fn late_owner_terminal_preserves_the_original_unknown_model_reply_and_tracking() {
    // Pure projection fixture. Actual original SQLite read/reopen and effect
    // counts are exercised by the owner and Notes Objective integration tests.
    let params = params();
    let id = proposal_id("fixture-owner", &route(), &params).unwrap();
    let mut proposal = proposal_view(id, &params, /*reviewed*/ None).unwrap();
    proposal.phase = NotesModelPhase::ReplyObserved;
    proposal.result = Some(NotesModelResult::Unknown);
    assert!(!proposal.can_release_tracking());
    let run_id = "notes.literal.fixture";
    let target = reviewed().target;
    let payload_json = serde_json::to_string(&json!({
        "schema_version":1, "action":"replace_note", "operation_id":run_id,
        "destination_id":target.destination_id(), "target":target,
        "expected_revision":3, "text":proposal.text,
    }))
    .unwrap();
    let operation = codex_hepta_memory::notes_operation_intent(
        &target,
        &payload_json,
        codex_hepta_types::StableId::new("fixture-owner").unwrap(),
        codex_hepta_types::Generation::new(1).unwrap(),
    )
    .unwrap();
    let receipt = serde_json::to_string(&json!({
        "schema_version":1, "target":target, "operation_id":run_id,
        "payload_sha256":Sha256Digest::for_bytes(payload_json.as_bytes()).as_str(),
        "result":{"status":"applied","previous_revision":3,"revision":4,
            "text_sha256":Sha256Digest::for_bytes(proposal.text.as_bytes()).as_str()},
    }))
    .unwrap();
    let terminal = ProductionNotesTerminalObservation {
        operation,
        payload_json,
        state: LocalOutcomeState::Committed,
        application_receipt_sha256: Sha256Digest::for_bytes(receipt.as_bytes()),
        application_receipt_json: receipt,
        terminal_event_id: "event:fixture:1".into(),
        terminal_event_sha256: Sha256Digest::for_bytes(b"fixture terminal event"),
        terminal_generation: 1,
    };
    let old_reply = unresolved_response(&proposal, run_id, NotesModelResult::Unknown).unwrap();
    observe_owner_terminal(run_id, &mut proposal, &terminal).unwrap();
    let mut expected = proposal.clone();
    expected.phase = NotesModelPhase::ReplyObserved;
    expected.result = Some(NotesModelResult::Unknown);
    expected.application_receipt_sha256 = None;
    assert_eq!(proposal, expected);
    assert_eq!(
        unresolved_response(&proposal, run_id, NotesModelResult::Unknown).unwrap(),
        old_reply
    );
    assert_eq!(
        proposal.owner_terminal.as_ref().unwrap().result,
        NotesModelResult::Applied
    );
    assert!(proposal.can_release_tracking());
    observe_owner_terminal(run_id, &mut proposal, &terminal).unwrap();
    assert_eq!(proposal, expected);
    let mut changed = terminal;
    changed.terminal_event_sha256 = Sha256Digest::for_bytes(b"different event");
    assert!(observe_owner_terminal(run_id, &mut proposal, &changed).is_err());
    assert_eq!(proposal, expected);
    let mut uncertain = proposal_view("model-other".into(), &params, /*reviewed*/ None).unwrap();
    uncertain.phase = NotesModelPhase::Closed;
    assert!(!uncertain.can_release_tracking());
    uncertain.result = Some(NotesModelResult::Declined);
    assert!(uncertain.can_release_tracking());
}
