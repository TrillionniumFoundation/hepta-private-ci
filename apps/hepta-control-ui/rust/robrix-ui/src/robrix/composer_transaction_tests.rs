use super::*;
use makepad_widgets::makepad_draw::text::selection::Cursor;
use makepad_widgets::makepad_draw::text::selection::Selection;
use makepad_widgets::text_input::TextInputAction;
use makepad_widgets::text_input::UndoGroup;

fn editor(text: &str) -> (Cx, TextInputRef, ChatWorkspace, RoomKey) {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let input = cx.with_vm(|vm| {
        makepad_widgets::script_mod(vm);
        let value = vm.eval(makepad_widgets::makepad_script::script! {
            use mod.prelude.widgets.*
            TextInput {}
        });
        WidgetRef::script_from_value(vm, value).as_text_input()
    });
    input.set_text(&mut cx, text);
    let mut workspace = ChatWorkspace::default();
    workspace.edit(text.to_owned());
    let room = RoomKey {
        epoch: workspace.presentation_epoch(),
        local_id: workspace.active_id(),
    };
    (cx, input, workspace, room)
}

#[test]
fn rejected_selection_replacement_restores_the_exact_sdk_editor_state() {
    let (mut cx, input, mut workspace, room) = editor("保留 selected");
    input
        .replace_range(&mut cx, 6..6, "中文", UndoGroup::New)
        .unwrap();
    workspace.edit(input.text());
    input.set_selection(
        &mut cx,
        Selection {
            anchor: Cursor {
                index: 0,
                prefer_next_row: false,
            },
            cursor: Cursor {
                index: 6,
                prefer_next_row: false,
            },
        },
    );
    let expected = format!("{:?}", input.save_state());
    let mut transaction = ComposerTransaction::default();
    transaction.checkpoint(&input, &workspace, Some(room));
    let paste = "界".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES);
    input
        .replace_range(&mut cx, 0..6, &paste, UndoGroup::New)
        .unwrap();
    let candidate = input.text();
    assert_eq!(
        transaction.edit(&mut cx, &input, &mut workspace, room, candidate),
        ActionResult::Rejected
    );
    assert_eq!(format!("{:?}", input.save_state()), expected);
    assert_eq!(input.text(), workspace.draft().text);
}

#[test]
fn stale_room_cannot_restore_another_rooms_selection_or_undo() {
    let (mut cx, input, mut workspace, room) = editor("private previous room");
    let mut transaction = ComposerTransaction::default();
    transaction.checkpoint(&input, &workspace, Some(room));
    assert!(workspace.new_draft());
    input.set_text(&mut cx, "new room editor");
    let expected = format!("{:?}", input.save_state());
    assert_eq!(
        transaction.edit(&mut cx, &input, &mut workspace, room, "late".into()),
        ActionResult::Stale
    );
    assert_eq!(format!("{:?}", input.save_state()), expected);
    assert_eq!(workspace.draft().text, "");
}

// Retain the actual SDK surface so TextInputEvent traverses a live draw area,
// the keyboard focus check and the SDK's own composition/undo implementation.
fn focused_surface(cx: &mut Cx, input: &TextInputRef) -> (DrawPass, DrawList2d) {
    use makepad_widgets::makepad_draw::cx_draw::CxDraw;
    cx.init_cx_os();
    let size = dvec2(640.0, 160.0);
    let pass = DrawPass::new(cx);
    pass.set_size(cx, size);
    let mut draw_list = DrawList2d::new(cx);
    {
        let event = DrawEvent::default();
        let mut draw = CxDraw::new(cx, &event);
        let mut cx2d = Cx2d::new(&mut draw);
        cx2d.begin_pass(&pass, None);
        draw_list.begin_always(&mut cx2d);
        cx2d.begin_root_turtle(size, Layout::flow_down());
        input
            .borrow_mut()
            .unwrap()
            .draw_all(&mut cx2d, &mut Scope::empty());
        cx2d.end_pass_sized_turtle();
        draw_list.end(&mut cx2d);
        cx2d.end_pass(&pass);
    }
    assert!(input.area().is_valid(cx));
    cx.set_key_focus(input.area());
    // The public action pump advances the SDK's pending key-focus transition.
    cx.widget_action(input.widget_uid(), TextInputAction::KeyFocus);
    cx.handle_actions();
    assert_eq!(cx.key_focus(), input.area());
    (pass, draw_list)
}

fn sdk_text_event(cx: &mut Cx, input: &TextInputRef, event: TextInputEvent) -> String {
    let actions = cx.capture_actions(|cx| {
        input
            .borrow_mut()
            .unwrap()
            .handle_event(cx, &Event::TextInput(event), &mut Scope::empty());
    });
    input.changed(&actions).expect("actual SDK Changed action")
}

#[test]
fn actual_sdk_preedit_preserves_committed_draft_title_and_checkpoint_until_commit() {
    let (mut cx, input, mut workspace, room) = editor("base ");
    input
        .replace_range(&mut cx, 5..5, "kept ", UndoGroup::New)
        .unwrap();
    workspace.edit(input.text());
    let _surface = focused_surface(&mut cx, &input);
    let end = input.text().len();
    input.set_selection(
        &mut cx,
        Selection {
            anchor: Cursor {
                index: end,
                prefer_next_row: false,
            },
            cursor: Cursor {
                index: end,
                prefer_next_row: false,
            },
        },
    );
    let mut transaction = ComposerTransaction::default();
    transaction.checkpoint(&input, &workspace, Some(room));
    let committed = workspace.draft().clone();
    let checkpoint = format!("{:?}", transaction.saved);
    for preview in ["年", "你好"] {
        let text = sdk_text_event(
            &mut cx,
            &input,
            TextInputEvent {
                input: preview.into(),
                replace_last: true,
                ..Default::default()
            },
        );
        assert!(input.is_composing());
        assert_eq!(text, format!("base kept {preview}"));
        let preview_state = format!("{:?}", input.save_state());
        assert_eq!(
            transaction.edit(&mut cx, &input, &mut workspace, room, text),
            ActionResult::Ignored
        );
        assert_eq!(workspace.draft(), &committed);
        assert_eq!(format!("{:?}", transaction.saved), checkpoint);
        assert_eq!(format!("{:?}", input.save_state()), preview_state);
        assert!(input.is_composing());
    }
    let text = sdk_text_event(
        &mut cx,
        &input,
        TextInputEvent {
            input: "你好".into(),
            ..Default::default()
        },
    );
    assert!(!input.is_composing());
    assert_eq!(text, "base kept 你好");
    assert_eq!(
        transaction.edit(&mut cx, &input, &mut workspace, room, text),
        ActionResult::Applied
    );
    assert_eq!(
        (&workspace.draft().text, &workspace.draft().title),
        (&"base kept 你好".to_owned(), &"base kept 你好".to_owned())
    );
    assert_eq!(
        format!("{:?}", transaction.saved.as_ref().unwrap().1),
        format!("{:?}", input.save_state())
    );
    assert_ne!(format!("{:?}", transaction.saved), checkpoint);
}

#[test]
fn actual_sdk_cancel_preserves_committed_draft_after_ignored_previews() {
    let (mut cx, input, mut workspace, room) = editor("retained draft");
    let _surface = focused_surface(&mut cx, &input);
    let mut transaction = ComposerTransaction::default();
    transaction.checkpoint(&input, &workspace, Some(room));
    let committed = workspace.draft().clone();
    let checkpoint = format!("{:?}", transaction.saved);
    let text = sdk_text_event(
        &mut cx,
        &input,
        TextInputEvent {
            input: "你好".into(),
            replace_last: true,
            ..Default::default()
        },
    );
    assert!(input.is_composing());
    assert_eq!(
        transaction.edit(&mut cx, &input, &mut workspace, room, text),
        ActionResult::Ignored
    );
    assert_eq!(workspace.draft(), &committed);
    assert_eq!(format!("{:?}", transaction.saved), checkpoint);
    let cancelled = sdk_text_event(
        &mut cx,
        &input,
        TextInputEvent {
            replace_last: true,
            ..Default::default()
        },
    );
    assert!(!input.is_composing());
    assert_eq!(cancelled, committed.text);
    assert_eq!(workspace.draft(), &committed);
    assert_eq!(format!("{:?}", transaction.saved), checkpoint);
    assert_eq!(
        transaction.edit(&mut cx, &input, &mut workspace, room, cancelled),
        ActionResult::Applied
    );
    assert_eq!(workspace.draft(), &committed);
}
