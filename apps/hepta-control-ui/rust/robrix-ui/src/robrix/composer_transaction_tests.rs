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

#[cfg(not(feature = "native-ime-sdk"))]
fn sdk_text_event(cx: &mut Cx, input: &TextInputRef, event: TextInputEvent) -> String {
    let actions = cx.capture_actions(|cx| {
        input
            .borrow_mut()
            .unwrap()
            .handle_event(cx, &Event::TextInput(event), &mut Scope::empty());
    });
    input.changed(&actions).expect("actual SDK Changed action")
}

#[cfg(not(feature = "native-ime-sdk"))]
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

#[cfg(not(feature = "native-ime-sdk"))]
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

#[cfg(feature = "native-ime-sdk")]
mod scoped_ime {
    use super::*;
    use makepad_widgets::text_input::{TextEditOutcome, TextInputAction, TextEditPhase};
    use std::{cell::RefCell, rc::Rc};

    type Pending = Rc<RefCell<Vec<TextEditOutcome>>>;

    fn fixture(text: &str) -> (Cx, TextInputRef, ChatWorkspace, RoomKey, Pending, ComposerTransaction, (DrawPass, DrawList2d)) {
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
        let surface = focused_surface(&mut cx, &input);
        let mut transaction = ComposerTransaction::default();
        transaction.checkpoint(&input, &workspace, Some(room));
        (cx, input, workspace, room, pending, transaction, surface)
    }

    // Actual drawn SDK TextInput path, not a substitute editor or platform IME.
    fn event(cx: &mut Cx, input: &TextInputRef, text: &str, preview: bool) {
        input.borrow_mut().unwrap().handle_event(cx, &Event::TextInput(TextInputEvent {
            input: text.into(), replace_last: preview, ..Default::default()
        }), &mut Scope::empty());
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
        let (mut cx, input, mut workspace, room, pending, mut tx, _surface) = fixture("中文 selected");
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
        let (mut cx, input, mut workspace, _, pending, mut tx, _surface) = fixture("");
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
        let (mut cx, input, mut workspace, _, pending, mut tx, _surface) = fixture("");
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
        let (mut cx, input, mut workspace, _, pending, mut tx, _surface) = fixture("");
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
        let (mut cx, input, mut workspace, _, pending, mut tx, _surface) = fixture("中文 original");
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
    fn external_commit_during_preview_then_cancel_keeps_committed_coordinates() {
        let (mut cx, input, mut workspace, _, pending, mut tx, _surface) = fixture("α旧🙂z");
        input.set_selection(&mut cx, Selection {
            anchor: Cursor { index: 5, prefer_next_row: true },
            cursor: Cursor { index: 2, prefer_next_row: false },
        });
        event(&mut cx, &input, "ni", true);
        input.replace_range(&mut cx, 0..0, "界", UndoGroup::New).unwrap();
        assert!(input.is_composing());
        let accepted = format!("{:?}", input.save_state());
        event(&mut cx, &input, "", true);
        assert_eq!(deliver(&mut cx, &input, &mut workspace, &pending, &mut tx),
            vec![ActionResult::Ignored, ActionResult::Applied, ActionResult::Ignored]);
        assert_eq!(workspace.draft().text, "界α旧🙂z");
        assert_eq!(format!("{:?}", input.save_state()), accepted);
    }

    #[test]
    fn batch_external_commit_then_next_preview_accepts_production_snapshots_only() {
        let (mut cx, input, mut workspace, _, pending, mut tx, _surface) = fixture("ab");
        event(&mut cx, &input, "ni", true);
        input.replace_range(&mut cx, 0..0, "界", UndoGroup::New).unwrap();
        event(&mut cx, &input, "你", false);
        let committed = input.text();
        let checkpoint = format!("{:?}", input.save_state());
        event(&mut cx, &input, "hao", true);
        assert!(input.is_composing());
        assert_ne!(input.text(), committed);
        assert_eq!(deliver(&mut cx, &input, &mut workspace, &pending, &mut tx),
            vec![ActionResult::Ignored, ActionResult::Applied, ActionResult::Applied, ActionResult::Ignored]);
        assert_eq!(workspace.draft().text, committed);
        assert_eq!(format!("{:?}", tx.saved.as_ref().unwrap().1), checkpoint);
        event(&mut cx, &input, "", true);
        assert_eq!(deliver(&mut cx, &input, &mut workspace, &pending, &mut tx),
            vec![ActionResult::Ignored]);
        assert_eq!(workspace.draft().text, committed);
        assert_eq!(format!("{:?}", input.save_state()), checkpoint);
    }

    #[test]
    fn rejected_external_edit_fences_queued_preview_and_terminal_outcomes() {
        let (mut cx, input, mut workspace, _, pending, mut tx, _surface) = fixture("base");
        let accepted = format!("{:?}", input.save_state());
        event(&mut cx, &input, "ni", true);
        input.replace_range(&mut cx, 0..0, &"界".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES), UndoGroup::New).unwrap();
        event(&mut cx, &input, "你好", true);
        event(&mut cx, &input, "好", false);
        assert_eq!(deliver(&mut cx, &input, &mut workspace, &pending, &mut tx),
            vec![ActionResult::Ignored, ActionResult::Rejected, ActionResult::Stale, ActionResult::Stale]);
        assert_eq!(workspace.draft().text, "base");
        assert_eq!(format!("{:?}", input.save_state()), accepted);
        assert!(!input.is_composing());
    }
}
