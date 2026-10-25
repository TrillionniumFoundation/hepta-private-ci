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

#[cfg(feature = "native-ime-sdk")]
mod scoped_ime {
    use super::*;
    use makepad_widgets::text_input::{TextEditOutcome, TextInputAction, TextEditPhase};
    use std::{cell::RefCell, rc::Rc};

    type Pending = Rc<RefCell<Vec<TextEditOutcome>>>;

    fn fixture(text: &str) -> (Cx, TextInputRef, ChatWorkspace, RoomKey, Pending, ComposerTransaction) {
        let pending: Pending = Default::default();
        let sink = pending.clone();
        let mut cx = Cx::new(Box::new(move |_, event| {
            if let Event::Actions(actions) = event {
                for action in actions.iter() {
                    if let TextInputAction::EditOutcome(value) = action.as_widget_action().cast() {
                        sink.borrow_mut().push(value);
                    }
                }
            }
        }));
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
        workspace.edit(text.into());
        let room = RoomKey { epoch: workspace.presentation_epoch(), local_id: workspace.active_id() };
        let mut transaction = ComposerTransaction::default();
        transaction.checkpoint(&input, &workspace, Some(room));
        (cx, input, workspace, room, pending, transaction)
    }

    // Calls the very same SDK implementation used by Hit::TextInput, without
    // pretending that this is a platform/XIM or live-window qualification.
    fn event(cx: &mut Cx, input: &TextInputRef, text: &str, preview: bool) {
        assert!(input.apply_scoped_text_input(cx, &TextInputEvent {
            input: text.into(), replace_last: preview, ..Default::default()
        }));
    }

    fn deliver(cx: &mut Cx, input: &TextInputRef, workspace: &mut ChatWorkspace,
        pending: &Pending, transaction: &mut ComposerTransaction) -> Vec<ActionResult>
    {
        cx.handle_actions();
        let outcomes = std::mem::take(&mut *pending.borrow_mut());
        outcomes.into_iter().map(|value| transaction.outcome(cx, input, workspace, value)).collect()
    }

    #[test]
    fn selected_text_cancel_restores_original_sdk_state_without_model_edit() {
        let (mut cx, input, mut workspace, room, pending, mut tx) = fixture("中文 selected");
        input.set_selection(&mut cx, Selection {
            anchor: Cursor { index: 0, prefer_next_row: false },
            cursor: Cursor { index: 6, prefer_next_row: false },
        });
        tx.checkpoint(&input, &workspace, Some(room));
        let original = format!("{:?}", input.save_state());
        let original_title = workspace.draft().title.clone();
        event(&mut cx, &input, "zhong", true);
        event(&mut cx, &input, "中", true);
        assert_ne!(input.text(), workspace.draft().text);
        assert_eq!(workspace.draft().title, original_title);
        assert_eq!(workspace.draft().text, "中文 selected");
        event(&mut cx, &input, "", true);
        assert_eq!(format!("{:?}", input.save_state()), original);
        assert_eq!(deliver(&mut cx, &input, &mut workspace, &pending, &mut tx),
            vec![ActionResult::Ignored, ActionResult::Ignored, ActionResult::Ignored]);
        assert_eq!(workspace.draft().text, "中文 selected");
    }

    #[test]
    fn preview_commit_in_one_batch_uses_only_production_commit_once() {
        let (mut cx, input, mut workspace, _, pending, mut tx) = fixture("");
        event(&mut cx, &input, "zhong", true);
        event(&mut cx, &input, "中文", false);
        assert_eq!(workspace.draft().text, "");
        cx.handle_actions();
        let outcomes = std::mem::take(&mut *pending.borrow_mut());
        assert_eq!(outcomes.iter().map(|o| o.phase).collect::<Vec<_>>(),
            vec![TextEditPhase::Preview, TextEditPhase::Committed]);
        let duplicate = outcomes[1].clone();
        for outcome in outcomes { tx.outcome(&mut cx, &input, &mut workspace, outcome); }
        assert_eq!(workspace.draft().text, "中文");
        assert_eq!(tx.outcome(&mut cx, &input, &mut workspace, duplicate), ActionResult::Rejected);
        assert_eq!(workspace.draft().text, "中文");
    }

    #[test]
    fn rejected_commit_invalidates_already_produced_batch_successor() {
        let (mut cx, input, mut workspace, _, pending, mut tx) = fixture("");
        event(&mut cx, &input, "accepted", false);
        let accepted_state = format!("{:?}", input.save_state());
        event(&mut cx, &input, "preview", true);
        event(&mut cx, &input, &"界".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES), false);
        event(&mut cx, &input, "tainted successor", false);
        assert_eq!(deliver(&mut cx, &input, &mut workspace, &pending, &mut tx),
            vec![ActionResult::Applied, ActionResult::Ignored, ActionResult::Rejected, ActionResult::Stale]);
        assert_eq!(workspace.draft().text, "accepted");
        assert_eq!(format!("{:?}", input.save_state()), accepted_state);
    }

    #[test]
    fn old_widget_outcome_cannot_be_relabeled_after_new_owner() {
        let (mut cx, input, mut workspace, _, pending, mut tx) = fixture("");
        event(&mut cx, &input, "private old commit", false);
        cx.handle_actions();
        let old = pending.borrow_mut().remove(0);
        assert!(workspace.new_draft());
        input.restore_checkpoint(&mut cx, TextInputState::default());
        tx.reset();
        let current = RoomKey { epoch: workspace.presentation_epoch(), local_id: workspace.active_id() };
        tx.checkpoint(&input, &workspace, Some(current));
        let before = format!("{:?}", input.save_state());
        assert_eq!(tx.outcome(&mut cx, &input, &mut workspace, old), ActionResult::Stale);
        assert_eq!(workspace.draft().text, "");
        assert_eq!(format!("{:?}", input.save_state()), before);
    }

    #[test]
    fn cancel_new_selection_then_reject_in_one_batch_restores_new_selection() {
        let (mut cx, input, mut workspace, _, pending, mut tx) = fixture("中文 original");
        event(&mut cx, &input, "preview", true);
        input.set_selection(&mut cx, Selection {
            anchor: Cursor { index: 0, prefer_next_row: false },
            cursor: Cursor { index: 6, prefer_next_row: false },
        });
        let selected = format!("{:?}", input.save_state());
        event(&mut cx, &input, &"界".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES), false);
        assert_eq!(deliver(&mut cx, &input, &mut workspace, &pending, &mut tx),
            vec![ActionResult::Ignored, ActionResult::Ignored, ActionResult::Rejected]);
        assert_eq!(format!("{:?}", input.save_state()), selected);
        assert_eq!(workspace.draft().text, "中文 original");
    }

    #[test]
    fn scoped_external_replacement_during_composition_is_explicitly_refused() {
        let (mut cx, input, _, _, _, _) = fixture("outside");
        event(&mut cx, &input, "preedit", true);
        let before = input.text();
        assert_eq!(input.replace_range(&mut cx, before.len()..before.len(), "x", UndoGroup::New),
            Err(makepad_widgets::text_input::ReplaceRangeError::Composing));
        assert_eq!(input.text(), before);
        assert!(input.cancel_composition(&mut cx));
        assert_eq!(input.text(), "outside");
    }
}
