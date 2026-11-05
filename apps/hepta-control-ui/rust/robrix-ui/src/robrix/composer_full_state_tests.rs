use super::*;
use makepad_widgets::makepad_platform::event::CharOffset;
use makepad_widgets::makepad_platform::event::FullTextState;
use std::ops::Range;

fn full_state_event(text: &str, composition: Option<Range<usize>>) -> Event {
    let end = CharOffset(text.chars().count());
    Event::TextInput(TextInputEvent {
        full_state_sync: Some(FullTextState {
            text: text.to_owned(),
            selection: end..end,
            composition: composition.map(|range| CharOffset(range.start)..CharOffset(range.end)),
        }),
        ..Default::default()
    })
}

// Exercise the same before-widget / actual SDK / after-widget boundary as
// RoomScreen. The original Changed action remains a separate, later path.
fn dispatch(
    cx: &mut Cx,
    input: &TextInputRef,
    workspace: &mut ChatWorkspace,
    source: RoomKey,
    transaction: &mut ComposerTransaction,
    event: &Event,
) -> (Option<String>, Option<ActionResult>) {
    let pending = ComposerTransaction::capture_full_state_commit(cx, input, event);
    let actions = cx.capture_actions(|cx| {
        input
            .borrow_mut()
            .unwrap()
            .handle_event(cx, event, &mut Scope::empty());
    });
    let changed = input.changed(&actions);
    let committed = pending
        .map(|commit| transaction.finish_full_state_commit(cx, input, workspace, source, commit));
    (changed, committed)
}

fn preview(
    cx: &mut Cx,
    input: &TextInputRef,
    workspace: &mut ChatWorkspace,
    source: RoomKey,
    transaction: &mut ComposerTransaction,
    text: &str,
) {
    let event = full_state_event(text, Some(0..text.chars().count()));
    let (changed, committed) = dispatch(cx, input, workspace, source, transaction, &event);
    assert_eq!(committed, None);
    assert!(input.is_composing());
    assert_eq!(
        transaction.edit(cx, input, workspace, source, changed.unwrap()),
        ActionResult::Ignored
    );
}

#[test]
fn unchanged_full_state_commit_publishes_actual_sdk_preedit_once() {
    let (mut cx, input, mut workspace, room) = editor("");
    let _surface = focused_surface(&mut cx, &input);
    let mut transaction = ComposerTransaction::default();
    transaction.checkpoint(&input, &workspace, Some(room));
    let original = workspace.draft().clone();
    let text = "Theme round trip draft 中文🚀";
    preview(
        &mut cx,
        &input,
        &mut workspace,
        room,
        &mut transaction,
        text,
    );
    assert_eq!(workspace.draft(), &original);
    let sdk_state = format!("{:?}", input.save_state());
    let event = full_state_event(text, None);
    let (changed, committed) = dispatch(
        &mut cx,
        &input,
        &mut workspace,
        room,
        &mut transaction,
        &event,
    );
    assert_eq!(changed, None, "pinned SDK emits no text-only Changed");
    assert_eq!(committed, Some(ActionResult::Applied));
    assert!(!input.is_composing());
    assert_eq!(workspace.draft().text, text);
    assert_eq!(workspace.draft().title, text);
    assert_eq!(format!("{:?}", input.save_state()), sdk_state);
    assert_eq!(
        format!("{:?}", transaction.saved.as_ref().unwrap().1),
        sdk_state
    );
    let saved = format!("{:?}", transaction.saved);
    assert_eq!(
        dispatch(
            &mut cx,
            &input,
            &mut workspace,
            room,
            &mut transaction,
            &event
        ),
        (None, None),
        "a duplicate commit is not another edit"
    );
    assert_eq!(format!("{:?}", transaction.saved), saved);

    // The next ordinary full-state input still follows the original Changed
    // path, with the entire earlier committed draft present.
    let next = format!("{text} kept");
    let (changed, committed) = dispatch(
        &mut cx,
        &input,
        &mut workspace,
        room,
        &mut transaction,
        &full_state_event(&next, None),
    );
    assert_eq!(committed, None);
    assert_eq!(
        transaction.edit(&mut cx, &input, &mut workspace, room, changed.unwrap()),
        ActionResult::Applied
    );
    assert_eq!(workspace.draft().text, next);
}

#[test]
fn changed_full_state_commit_and_cancel_keep_the_original_action_path() {
    for final_text in ["different committed 中文🚀", "kept"] {
        let (mut cx, input, mut workspace, room) = editor("kept");
        let _surface = focused_surface(&mut cx, &input);
        let mut transaction = ComposerTransaction::default();
        transaction.checkpoint(&input, &workspace, Some(room));
        let original = workspace.draft().clone();
        preview(
            &mut cx,
            &input,
            &mut workspace,
            room,
            &mut transaction,
            "preview 中文🚀",
        );
        let (changed, committed) = dispatch(
            &mut cx,
            &input,
            &mut workspace,
            room,
            &mut transaction,
            &full_state_event(final_text, None),
        );
        assert_eq!(committed, Some(ActionResult::Ignored));
        assert_eq!(changed.as_deref(), Some(final_text));
        assert_eq!(workspace.draft(), &original);
        assert_eq!(
            transaction.edit(&mut cx, &input, &mut workspace, room, changed.unwrap()),
            ActionResult::Applied
        );
        assert_eq!(workspace.draft().text, final_text);
    }
}

#[test]
fn full_state_commit_rejects_oversized_draft_with_original_sdk_checkpoint() {
    let (mut cx, input, mut workspace, room) = editor("kept selection");
    let _surface = focused_surface(&mut cx, &input);
    let mut transaction = ComposerTransaction::default();
    transaction.checkpoint(&input, &workspace, Some(room));
    let original = workspace.draft().text.clone();
    let sdk_state = format!("{:?}", input.save_state());
    let oversized = "x".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES + 1);
    preview(
        &mut cx,
        &input,
        &mut workspace,
        room,
        &mut transaction,
        &oversized,
    );
    let (changed, committed) = dispatch(
        &mut cx,
        &input,
        &mut workspace,
        room,
        &mut transaction,
        &full_state_event(&oversized, None),
    );
    assert_eq!(changed, None);
    assert_eq!(committed, Some(ActionResult::Rejected));
    assert_eq!(workspace.draft().text, original);
    assert_eq!(input.text(), original);
    assert_eq!(format!("{:?}", input.save_state()), sdk_state);
    assert!(!input.is_composing());
}

#[test]
fn full_state_commit_cannot_publish_into_a_new_room() {
    let (mut cx, input, mut workspace, room) = editor("original room");
    let _surface = focused_surface(&mut cx, &input);
    let mut transaction = ComposerTransaction::default();
    transaction.checkpoint(&input, &workspace, Some(room));
    preview(
        &mut cx,
        &input,
        &mut workspace,
        room,
        &mut transaction,
        "old room preview",
    );
    assert!(workspace.new_draft());
    let new_draft = workspace.draft().clone();
    let (changed, committed) = dispatch(
        &mut cx,
        &input,
        &mut workspace,
        room,
        &mut transaction,
        &full_state_event("old room preview", None),
    );
    assert_eq!(changed, None);
    assert_eq!(committed, Some(ActionResult::Stale));
    assert_eq!(workspace.draft(), &new_draft);
    assert_eq!(input.text(), "old room preview");
}

#[test]
fn full_state_commit_requires_the_same_focused_editor() {
    let (mut cx, input, mut workspace, room) = editor("kept");
    let _surface = focused_surface(&mut cx, &input);
    let mut transaction = ComposerTransaction::default();
    transaction.checkpoint(&input, &workspace, Some(room));
    preview(
        &mut cx,
        &input,
        &mut workspace,
        room,
        &mut transaction,
        "preview",
    );
    assert!(
        ComposerTransaction::capture_full_state_commit(
            &cx,
            &input,
            &Event::Draw(DrawEvent::default())
        )
        .is_none()
    );
    let event = full_state_event("preview", None);
    let commit = ComposerTransaction::capture_full_state_commit(&cx, &input, &event).unwrap();
    let original = workspace.draft().clone();
    cx.set_key_focus(Area::Empty);
    cx.widget_action(input.widget_uid(), TextInputAction::KeyFocusLost);
    cx.handle_actions();
    assert_eq!(cx.key_focus(), Area::Empty);
    assert!(ComposerTransaction::capture_full_state_commit(&cx, &input, &event).is_none());
    assert_eq!(
        transaction.finish_full_state_commit(&mut cx, &input, &mut workspace, room, commit),
        ActionResult::Ignored
    );
    assert_eq!(workspace.draft(), &original);
}
