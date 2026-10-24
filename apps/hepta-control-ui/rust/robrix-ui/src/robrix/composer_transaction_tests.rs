use super::*;
use makepad_widgets::makepad_draw::text::selection::Cursor;
use makepad_widgets::makepad_draw::text::selection::Selection;
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
