use super::*;
use makepad_widgets::makepad_draw::cx_draw::CxDraw;
use makepad_widgets::makepad_platform::event::CharOffset;
use makepad_widgets::makepad_platform::event::FullTextState;
use makepad_widgets::text_input::TextInputAction;
use makepad_widgets::text_input::UndoGroup;
use pretty_assertions::assert_eq;
use std::ops::Range;

fn draw_room(
    cx: &mut Cx,
    room: &mut RoomScreen,
    workspace: &mut ChatWorkspace,
    pass: &DrawPass,
    draw_list: &mut DrawList2d,
) {
    let event = DrawEvent::default();
    let mut draw = CxDraw::new(cx, &event);
    let mut cx2d = Cx2d::new(&mut draw);
    cx2d.begin_pass(pass, /*dpi_override*/ None);
    draw_list.begin_always(&mut cx2d);
    cx2d.begin_root_turtle(DVec2 { x: 640.0, y: 160.0 }, Layout::flow_down());
    room.draw_all(&mut cx2d, &mut Scope::with_data(workspace));
    cx2d.end_pass_sized_turtle();
    draw_list.end(&mut cx2d);
    cx2d.end_pass(pass);
}

// Use the production Room owner with a real SDK child and retained draw area.
// Only unrelated timeline/toolbar widgets are absent from this small surface.
fn editor(
    text: &str,
) -> (Cx, RoomScreen, TextInputRef, ChatWorkspace, DrawPass, DrawList2d) {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let view = cx.with_vm(|vm| {
        makepad_widgets::script_mod(vm);
        let value = vm.eval(makepad_widgets::makepad_script::script! {
            use mod.prelude.widgets.*
            View {
                width: Fill height: Fit flow: Down
                message_input := TextInput {}
            }
        });
        View::script_from_value(vm, value)
    });
    let mut room = RoomScreen {
        view,
        active_key: None,
        scroll_tracker: UserScrollTracker::default(),
        pending_tail_redraw: None,
        composer_transaction: ComposerTransaction::default(),
        chat_controls: RoomChatControls::default(),
    };
    let mut workspace = ChatWorkspace::default();
    workspace.edit(text.to_owned());
    cx.init_cx_os();
    let pass = DrawPass::new(&mut cx);
    pass.set_size(&mut cx, DVec2 { x: 640.0, y: 160.0 });
    let mut draw_list = DrawList2d::new(&mut cx);
    draw_room(&mut cx, &mut room, &mut workspace, &pass, &mut draw_list);
    let input = room.view.text_input(&mut cx, ids!(message_input));
    assert!(input.area().is_valid(&cx));
    cx.set_key_focus(input.area());
    cx.widget_action(input.widget_uid(), TextInputAction::KeyFocus);
    cx.handle_actions();
    assert_eq!(cx.key_focus(), input.area());
    assert_eq!(input.text(), text);
    assert_eq!(
        room.active_key,
        Some(RoomKey {
            epoch: workspace.presentation_epoch(),
            local_id: workspace.active_id(),
        })
    );
    (cx, room, input, workspace, pass, draw_list)
}

// These are the scalar offsets produced by the pinned web bridge's real
// ToWasmImeState conversion, not the incremental replace_last input path.
fn full_state(
    cx: &mut Cx,
    room: &mut RoomScreen,
    input: &TextInputRef,
    workspace: &mut ChatWorkspace,
    text: &str,
    composition: Option<Range<usize>>,
) -> Option<String> {
    let end = CharOffset(text.chars().count());
    let event = Event::TextInput(TextInputEvent {
        full_state_sync: Some(FullTextState {
            text: text.to_owned(),
            selection: end..end,
            composition: composition.map(|range| CharOffset(range.start)..CharOffset(range.end)),
        }),
        ..Default::default()
    });
    let actions = cx.capture_actions(|cx| {
        room.handle_event(cx, &event, &mut Scope::with_data(&mut *workspace));
    });
    let changed = input.changed(&actions);
    room.handle_event(
        cx,
        &Event::Actions(actions),
        &mut Scope::with_data(workspace),
    );
    changed
}

#[test]
fn full_state_same_text_commit_publishes_only_after_composition_ends() {
    let (mut cx, mut room, input, mut workspace, pass, mut draw_list) = editor("base kept ");
    let committed = workspace.draft().clone();
    for preview in ["base kept 中", "base kept 中文🚀"] {
        assert_eq!(
            full_state(
                &mut cx,
                &mut room,
                &input,
                &mut workspace,
                preview,
                Some(10..preview.chars().count()),
            ),
            Some(preview.to_owned())
        );
        assert!(input.is_composing());
        assert_eq!(workspace.draft(), &committed);
    }
    let preview_state = format!("{:?}", input.save_state());
    // The pinned SDK intentionally emits no Changed when only composition ends.
    assert_eq!(
        full_state(
            &mut cx,
            &mut room,
            &input,
            &mut workspace,
            "base kept 中文🚀",
            /*composition*/ None,
        ),
        None
    );
    assert!(!input.is_composing());
    assert_eq!(workspace.draft().text, "base kept 中文🚀");
    assert_eq!(workspace.draft().title, "base kept 中文🚀");
    assert_eq!(format!("{:?}", input.save_state()), preview_state);
    room.view.redraw(&mut cx);
    draw_room(&mut cx, &mut room, &mut workspace, &pass, &mut draw_list);
    assert_eq!(input.text(), workspace.draft().text);
    assert_eq!(format!("{:?}", input.save_state()), preview_state);
}

#[test]
fn full_state_cancel_keeps_the_committed_draft() {
    let (mut cx, mut room, input, mut workspace, _pass, _draw_list) = editor("retained draft");
    let committed = workspace.draft().clone();
    full_state(&mut cx, &mut room, &input, &mut workspace, "retained draft中文", Some(14..16));
    assert!(input.is_composing());
    assert_eq!(workspace.draft(), &committed);
    assert_eq!(
        full_state(
            &mut cx,
            &mut room,
            &input,
            &mut workspace,
            &committed.text,
            /*composition*/ None,
        ),
        Some(committed.text.clone())
    );
    assert!(!input.is_composing());
    assert_eq!(workspace.draft(), &committed);
    assert_eq!(input.text(), committed.text);
}

#[test]
fn full_state_changed_commit_uses_the_original_changed_action() {
    let (mut cx, mut room, input, mut workspace, _pass, _draw_list) = editor("base ");
    let committed = workspace.draft().clone();
    full_state(&mut cx, &mut room, &input, &mut workspace, "base 中", Some(5..6));
    assert!(input.is_composing());
    assert_eq!(workspace.draft(), &committed);
    assert_eq!(
        full_state(&mut cx, &mut room, &input, &mut workspace, "base 中文", /*composition*/ None),
        Some("base 中文".to_owned())
    );
    assert!(!input.is_composing());
    assert_eq!(workspace.draft().text, "base 中文");
}

#[test]
fn full_state_same_text_rejected_commit_restores_the_exact_editor_checkpoint() {
    let (mut cx, mut room, input, mut workspace, _pass, _draw_list) = editor("retained ");
    input
        .replace_range(&mut cx, /*range*/ 9..9, "undo history", UndoGroup::New)
        .unwrap();
    workspace.edit(input.text());
    let checkpoint = format!("{:?}", input.save_state());
    let committed_text = workspace.draft().text.clone();
    let oversized = "界".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES);
    full_state(
        &mut cx,
        &mut room,
        &input,
        &mut workspace,
        &oversized,
        Some(0..oversized.chars().count()),
    );
    assert!(input.is_composing());
    assert_eq!(workspace.draft().text, committed_text);
    assert_eq!(
        full_state(&mut cx, &mut room, &input, &mut workspace, &oversized, /*composition*/ None),
        None
    );
    assert!(!input.is_composing());
    assert_eq!(workspace.draft().text, committed_text);
    assert_eq!(workspace.draft().status, ComposeStatus::InputLimit);
    assert_eq!(format!("{:?}", input.save_state()), checkpoint);
}

#[test]
fn full_state_late_same_text_commit_cannot_edit_the_new_room() {
    let (mut cx, mut room, input, mut workspace, _pass, _draw_list) = editor("old room ");
    full_state(&mut cx, &mut room, &input, &mut workspace, "old room private", Some(9..16));
    assert!(input.is_composing());
    let rendered = room.active_key;
    assert!(workspace.new_draft());
    let next_draft = workspace.draft().clone();
    let previous_editor = format!("{:?}", input.save_state());
    assert_ne!(rendered.unwrap().local_id, workspace.active_id());
    full_state(
        &mut cx,
        &mut room,
        &input,
        &mut workspace,
        "old room private",
        /*composition*/ None,
    );
    assert!(!input.is_composing());
    assert_eq!(workspace.draft(), &next_draft);
    assert_eq!(format!("{:?}", input.save_state()), previous_editor);
}
