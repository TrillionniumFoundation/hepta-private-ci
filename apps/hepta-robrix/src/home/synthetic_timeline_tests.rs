use super::*;
use crate::app::App;

fn room() -> RoomNameId {
    RoomNameId::new(matrix_sdk::RoomDisplayName::Named("Synthetic owner test".into()),
        "!hepta-owner-test:example.invalid".try_into().unwrap())
}

fn screen(cx: &mut Cx) -> RoomScreen {
    cx.with_vm(|vm| {
        let _ = <App as AppMain>::script_mod(vm);
        let value = script_eval!(vm, {mod.widgets.RoomScreen {}});
        RoomScreen::script_from_value(vm, value)
    })
}

#[test]
fn real_composer_state_transfers_once_between_synthetic_owners() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    timeline_state_store::clear_all(&mut cx);
    let mut first = screen(&mut cx);
    first.show_synthetic_timeline(&mut cx, &room(), None);
    let input = first.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input));
    input.set_text(&mut cx, "theme-draft-fixture");
    let original_uid = input.widget_uid();
    let original_selection = {
        let mut input = input.borrow_mut().unwrap();
        input.move_cursor_left(&mut cx, true);
        (input.cursor(), input.selection().anchor)
    };
    first.save_state();
    let mut second = screen(&mut cx);
    second.show_synthetic_timeline(&mut cx, &room(), None);
    let restored = second.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input));
    assert_ne!(restored.widget_uid(), original_uid);
    assert_eq!(restored.text(), "theme-draft-fixture");
    { let input = restored.borrow().unwrap();
      assert_eq!((input.cursor(), input.selection().anchor), original_selection); }
    assert!(second.view.room_input_bar(&mut cx, ids!(room_input_bar)).synthetic_send_context_unset());
    assert_eq!(second.tl_state.as_ref().unwrap().request_sender.receiver_count(), 0);
    second.save_state();
    timeline_state_store::clear_all(&mut cx);
}

#[test]
fn cleared_state_cannot_be_reintroduced_by_delayed_old_owner() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    timeline_state_store::clear_all(&mut cx);
    let mut old = screen(&mut cx);
    old.show_synthetic_timeline(&mut cx, &room(), None);
    old.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input)).set_text(&mut cx, "retired-draft");
    timeline_state_store::clear_all(&mut cx);
    old.save_state();
    let mut fresh = screen(&mut cx);
    fresh.show_synthetic_timeline(&mut cx, &room(), None);
    assert_eq!(fresh.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input)).text(), "");
    fresh.save_state();
    timeline_state_store::clear_all(&mut cx);
}

#[test]
fn delayed_old_return_cannot_replace_a_new_owner_marker() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    timeline_state_store::clear_all(&mut cx);
    let mut old = screen(&mut cx);
    old.show_synthetic_timeline(&mut cx, &room(), None);
    timeline_state_store::clear_all(&mut cx);
    let mut current = screen(&mut cx);
    current.show_synthetic_timeline(&mut cx, &room(), None);
    let kind = current.timeline_kind.clone().unwrap();
    old.save_state();
    assert!(matches!(timeline_state_store::take(&mut cx, &kind, old.widget_uid()),
        timeline_state_store::TakeResult::AlreadyTaken {owner} if owner == current.widget_uid()));
    current.save_state();
    timeline_state_store::clear_all(&mut cx);
}

#[test]
fn delayed_old_return_cannot_replace_newer_parked_draft() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    timeline_state_store::clear_all(&mut cx);
    let mut old = screen(&mut cx);
    old.show_synthetic_timeline(&mut cx, &room(), None);
    old.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input)).set_text(&mut cx, "old");
    timeline_state_store::clear_all(&mut cx);
    let mut current = screen(&mut cx);
    current.show_synthetic_timeline(&mut cx, &room(), None);
    current.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input)).set_text(&mut cx, "new");
    current.save_state();
    old.save_state();
    let mut next = screen(&mut cx);
    next.show_synthetic_timeline(&mut cx, &room(), None);
    assert_eq!(next.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input)).text(), "new");
    next.save_state();
    timeline_state_store::clear_all(&mut cx);
}

#[test]
fn repeated_thread_owner_transfer_keeps_identity_without_request_consumer() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    timeline_state_store::clear_all(&mut cx);
    let thread: OwnedEventId = "$synthetic-thread:example.invalid".try_into().unwrap();
    let mut first = screen(&mut cx);
    first.show_synthetic_timeline(&mut cx, &room(), Some(thread.clone()));
    first.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input)).set_text(&mut cx, "thread-draft");
    let kind = first.timeline_kind.clone().unwrap();
    first.save_state();
    for _ in 0..3 {
        let mut next = screen(&mut cx);
        next.show_synthetic_timeline(&mut cx, &room(), Some(thread.clone()));
        assert_eq!(next.timeline_kind.as_ref(), Some(&kind));
        assert_eq!(next.view.text_input(&mut cx, ids!(room_input_bar.mentionable_text_input.text_input)).text(), "thread-draft");
        assert_eq!(next.tl_state.as_ref().unwrap().request_sender.receiver_count(), 0);
        assert!(next.view.room_input_bar(&mut cx, ids!(room_input_bar)).synthetic_send_context_unset());
        next.save_state();
    }
    timeline_state_store::clear_all(&mut cx);
}
