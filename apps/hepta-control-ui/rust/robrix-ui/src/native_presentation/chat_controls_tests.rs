use super::*;

#[test]
fn host_capability_never_overrides_composition_input_limit_or_stale_room() {
    let mut workspace = ChatWorkspace::default();
    workspace.edit("中文 input".into());
    let room = RoomKey { epoch: workspace.presentation_epoch(), local_id: workspace.active_id() };
    let controls = Controls { room: Some(room), availability: NativeChatAvailability { can_submit: true, can_interrupt: true } };
    assert!(controls.permits_submit(room, &workspace));
    workspace.composing = true;
    assert!(!controls.permits_submit(room, &workspace));
    assert!(!controls.permits_interrupt(room, &workspace));
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
}
