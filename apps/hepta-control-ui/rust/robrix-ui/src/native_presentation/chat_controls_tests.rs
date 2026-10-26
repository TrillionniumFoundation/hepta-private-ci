use super::*;

#[test]
fn model_notes_decisions_use_the_visible_proposal_and_original_thread_without_a_draft() {
    use hepta_control_core::chat_timeline::History;
    use hepta_control_core::chat_timeline::ViewFence;
    let mut workspace = ChatWorkspace::default();
    let room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    let ticket = workspace
        .begin_history(
            room.local_id,
            "original-thread",
            ViewFence {
                owner_session: "owner".into(),
                generation: 1,
            },
        )
        .unwrap();
    workspace
        .receive_history(
            &ticket,
            History {
                thread_id: "original-thread".into(),
                title: "Original".into(),
                revision: 1,
                event_sequence: 0,
                messages: vec![],
            },
        )
        .unwrap();
    let controls = Controls {
        room: Some(room),
        notes: Some(NativeNotesView {
            model_proposal: Some(super::super::NativeNotesModelProposalView {
                proposal_id: "model-original".into(),
                proposal_sha256: "a".repeat(64),
                thread_id: "original-thread".into(),
                details: "完整拟写入文本；不是草稿".into(),
                can_confirm: true,
                can_decline: true,
            }),
            ..NativeNotesView::default()
        }),
        ..Controls::default()
    };
    assert!(workspace.draft().text.is_empty());
    for decision in [
        NativeNotesModelDecision::Confirm,
        NativeNotesModelDecision::Decline,
    ] {
        assert!(controls.permits_notes_model_decision(
            room,
            "model-original",
            &"a".repeat(64),
            decision,
            &workspace
        ));
        assert!(!controls.permits_notes_model_decision(
            room,
            "model-other",
            &"a".repeat(64),
            decision,
            &workspace
        ));
        assert!(!controls.permits_notes_model_decision(
            room,
            "model-original",
            &"b".repeat(64),
            decision,
            &workspace
        ));
    }
    workspace.composing = true;
    assert!(!controls.permits_notes_model_decision(
        room,
        "model-original",
        &"a".repeat(64),
        NativeNotesModelDecision::Confirm,
        &workspace
    ));
    workspace.composing = false;
    assert!(workspace.new_draft());
    assert!(!controls.permits_notes_model_decision(
        room,
        "model-original",
        &"a".repeat(64),
        NativeNotesModelDecision::Confirm,
        &workspace
    ));
}

#[test]
fn approval_actions_are_bound_to_the_visible_original_request_room_and_ime() {
    let mut workspace = ChatWorkspace::default();
    let room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    let controls = Controls {
        room: Some(room),
        availability: NativeChatAvailability::default(),
        approval: Some(NativeApprovalView {
            id: "17".into(),
            title: "Original command".into(),
            details: "visible original request".into(),
            can_accept: true,
            can_decline: true,
            busy: false,
        }),
        notes: None,
    };
    assert!(controls.permits_approval(room, "17", NativeApprovalDecision::AcceptOnce, &workspace));
    assert!(!controls.permits_approval(room, "18", NativeApprovalDecision::AcceptOnce, &workspace));
    workspace.composing = true;
    assert!(!controls.permits_approval(room, "17", NativeApprovalDecision::Decline, &workspace));
    workspace.composing = false;
    assert!(workspace.new_draft());
    assert!(!controls.permits_approval(room, "17", NativeApprovalDecision::AcceptOnce, &workspace));
}

#[test]
fn host_capability_never_overrides_composition_input_limit_or_stale_room() {
    let mut workspace = ChatWorkspace::default();
    workspace.edit("中文 input".into());
    let room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    let controls = Controls {
        room: Some(room),
        availability: NativeChatAvailability {
            can_submit: true,
            can_interrupt: true,
            can_load_earlier: true,
            can_load_latest: true,
        },
        approval: None,
        notes: None,
    };
    assert!(controls.permits_submit(room, &workspace));
    assert!(controls.permits_earlier_history(room, &workspace));
    assert!(controls.permits_latest_history(room, &workspace));
    workspace.composing = true;
    assert!(!controls.permits_submit(room, &workspace));
    assert!(!controls.permits_interrupt(room, &workspace));
    assert!(!controls.permits_earlier_history(room, &workspace));
    assert!(!controls.permits_latest_history(room, &workspace));
    workspace.composing = false;
    workspace.edit("x".repeat(hepta_control_core::chat_owner::MAX_SIGNED_TEXT_BYTES + 1));
    assert!(!controls.permits_submit(room, &workspace));
    workspace.edit("valid again".into());
    workspace.edit("x".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES + 1));
    assert!(!controls.permits_submit(room, &workspace));
    workspace.edit("retained".into());
    assert!(workspace.new_draft());
    assert!(!controls.permits_submit(room, &workspace));
    assert!(!controls.permits_interrupt(room, &workspace));
    assert!(!controls.permits_earlier_history(room, &workspace));
    assert!(!controls.permits_latest_history(room, &workspace));
}

#[test]
fn notes_controls_refuse_missing_owner_each_unavailable_action_and_uncommitted_input() {
    let mut workspace = ChatWorkspace::default();
    workspace.edit("write this original draft into Notes".into());
    let room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    let mut controls = Controls {
        room: Some(room),
        ..Controls::default()
    };
    assert!(!controls.permits_write_note(room, &workspace));
    assert!(!controls.permits_notes_refresh(room, &workspace));
    assert!(!controls.permits_notes_cancel(room, &workspace));
    controls.notes = Some(NativeNotesView {
        status: "Original owner result is unknown".into(),
        can_write: true,
        can_refresh: true,
        can_cancel: true,
        model_proposal: None,
    });
    // Notes availability is independent of authenticated model-chat Send.
    assert!(!controls.permits_submit(room, &workspace));
    assert!(controls.permits_write_note(room, &workspace));
    assert!(controls.permits_notes_refresh(room, &workspace));
    assert!(controls.permits_notes_cancel(room, &workspace));
    workspace.composing = true;
    assert!(!controls.permits_write_note(room, &workspace));
    assert!(!controls.permits_notes_refresh(room, &workspace));
    assert!(!controls.permits_notes_cancel(room, &workspace));
    workspace.composing = false;
    controls.notes = Some(NativeNotesView {
        status: "Disconnected; original outcome remains unknown".into(),
        ..NativeNotesView::default()
    });
    assert!(!controls.permits_write_note(room, &workspace));
    assert!(!controls.permits_notes_refresh(room, &workspace));
    assert!(!controls.permits_notes_cancel(room, &workspace));
    assert_eq!(
        workspace.draft().text,
        "write this original draft into Notes"
    );
}

#[test]
fn notes_callbacks_cannot_reuse_an_old_room_epoch_or_hidden_conversation() {
    let mut workspace = ChatWorkspace::default();
    workspace.edit("retained Notes input".into());
    let room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    let mut controls = Controls {
        room: Some(room),
        notes: Some(NativeNotesView {
            status: "Awaiting original owner".into(),
            can_write: true,
            can_refresh: true,
            can_cancel: true,
            model_proposal: None,
        }),
        ..Controls::default()
    };
    workspace.navigation_open = true;
    assert!(!controls.permits_write_note(room, &workspace));
    assert!(!controls.permits_notes_refresh(room, &workspace));
    assert!(!controls.permits_notes_cancel(room, &workspace));
    workspace.navigation_open = false;
    workspace.tab = hepta_control_core::chat::WorkspaceTab::Console;
    assert!(!controls.permits_write_note(room, &workspace));
    assert!(!controls.permits_notes_refresh(room, &workspace));
    assert!(!controls.permits_notes_cancel(room, &workspace));
    workspace.tab = hepta_control_core::chat::WorkspaceTab::Conversations;
    let stale = RoomKey {
        epoch: room.epoch + 1,
        ..room
    };
    controls.room = Some(stale);
    assert!(!controls.permits_write_note(stale, &workspace));
    assert!(!controls.permits_notes_refresh(stale, &workspace));
    assert!(!controls.permits_notes_cancel(stale, &workspace));
    controls.room = Some(room);
    assert!(workspace.new_draft());
    assert!(!controls.permits_write_note(room, &workspace));
    assert!(!controls.permits_notes_refresh(room, &workspace));
    assert!(!controls.permits_notes_cancel(room, &workspace));
}

#[test]
fn notes_write_uses_the_sole_bounded_draft_while_readback_needs_no_new_text() {
    let mut workspace = ChatWorkspace::default();
    let room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    let controls = Controls {
        room: Some(room),
        notes: Some(NativeNotesView {
            status: "Retained original identity".into(),
            can_write: true,
            can_refresh: true,
            can_cancel: false,
            model_proposal: None,
        }),
        ..Controls::default()
    };
    assert!(!controls.permits_write_note(room, &workspace));
    assert!(controls.permits_notes_refresh(room, &workspace));
    assert!(!controls.permits_notes_cancel(room, &workspace));
    workspace.edit("界".repeat(3000));
    assert!(!controls.permits_write_note(room, &workspace));
    workspace.edit("new valid original draft".into());
    assert!(controls.permits_write_note(room, &workspace));
    workspace.edit("x".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES + 1));
    assert!(!controls.permits_write_note(room, &workspace));
    assert!(controls.permits_notes_refresh(room, &workspace));
}

#[test]
fn a_new_proposal_cannot_reuse_a_confirm_button_before_its_details_are_drawn() {
    let room = RoomKey {
        epoch: 1,
        local_id: 0,
    };
    let mut proposal = super::super::NativeNotesModelProposalView {
        proposal_id: "model-old".into(),
        proposal_sha256: "a".repeat(64),
        thread_id: "thread".into(),
        details: "the text actually shown".into(),
        can_confirm: true,
        can_decline: true,
    };
    let rendered = RenderedControls {
        model_review: Some((room, proposal.clone())),
        ..RenderedControls::default()
    };
    assert!(rendered.visible_model_matches(room, &proposal));
    proposal.proposal_id = "model-new".into();
    assert!(!rendered.visible_model_matches(room, &proposal));
    proposal.proposal_id = "model-old".into();
    proposal.details = "not yet drawn text".into();
    assert!(!rendered.visible_model_matches(room, &proposal));
}
