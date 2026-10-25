use super::*;

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
