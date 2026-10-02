use hepta_control_core::chat::{AppTab, ChatAvailability, ChatState, Conversation, Message};

fn rooms() -> ChatState {
    ChatState {
        availability: ChatAvailability::Ready,
        conversations: ["one", "two"]
            .into_iter()
            .map(|id| Conversation {
                id: id.into(),
                title: id.into(),
                preview: String::new(),
                unread: 0,
            })
            .collect(),
        ..ChatState::default()
    }
}

#[test]
fn navigation_preserves_each_room_draft_without_accepting_a_late_timeline() {
    let mut state = rooms();
    assert!(state.select("one"));
    let epoch = state.selection_epoch;
    state.draft = "Draft one".into();
    assert!(state.select("two"));
    state.draft = "Draft two".into();
    assert!(!state.observe_messages(
        "one",
        epoch,
        vec![Message {
            id: "m".into(),
            sender: "sender".into(),
            body: "late".into(),
            timestamp: "now".into()
        }]
    ));
    assert!(state.messages.is_empty());
    assert!(state.select("one"));
    assert_eq!(state.draft, "Draft one");
    assert!(state.select("two"));
    assert_eq!(state.draft, "Draft two");
    assert!(!state.select("not-a-room"));
    assert_eq!(state.selected.as_deref(), Some("two"));
}

#[test]
fn send_requires_observed_ready_room_and_bounded_nonblank_draft() {
    let mut state = rooms();
    state.draft = "Message".into();
    assert!(!state.can_send());
    state.select("one");
    state.draft = "Message".into();
    assert!(state.can_send());
    state.availability = ChatAvailability::Offline;
    assert!(!state.can_send());
    state.availability = ChatAvailability::Ready;
    state.sending = true;
    assert!(!state.can_send());
    state.sending = false;
    state.draft = " ".into();
    assert!(!state.can_send());
    state.draft = "a".repeat(4097);
    assert!(!state.can_send());
}

#[test]
fn session_reset_removes_all_private_content_but_preserves_navigation() {
    let mut state = rooms();
    state.select("one");
    state.draft = "private".into();
    state.select("two");
    state.tab = AppTab::Console;
    state.reset_session();
    assert_eq!(
        state,
        ChatState {
            tab: AppTab::Console,
            ..ChatState::default()
        }
    );
}

#[test]
fn page_epochs_reject_late_latest_and_room_changes_reset_history() {
    let mut state = rooms();
    state.select("one");
    let latest = state.page.begin();
    let older = state.page.begin();
    assert!(!state.page.observe(latest, None, Some("late".into())));
    assert!(
        state
            .page
            .observe(older, Some("older".into()), Some("next".into()))
    );
    state.page.failed(latest);
    assert_eq!(state.page.cursor.as_deref(), Some("older"));
    state.select("two");
    assert_eq!(state.page, Default::default());
}

#[test]
fn rejected_duplicate_page_changes_neither_cursor_nor_messages() {
    let mut state = rooms();
    state.select("one");
    let page = state.page.begin();
    let message = Message {
        id: "duplicate".into(),
        sender: "assistant".into(),
        body: "text".into(),
        timestamp: String::new(),
    };
    let before = state.clone();
    assert!(!state.observe_timeline_page(
        "one",
        state.selection_epoch,
        page,
        Some("older".into()),
        None,
        vec![message.clone(), message]
    ));
    assert_eq!(state, before);
}

#[test]
fn observed_untitled_room_is_searchable_by_its_display_label_without_mutating_data() {
    let mut state = rooms();
    state.conversations[0].title.clear();
    state.filter = "new conversation".into();
    assert_eq!(
        state
            .visible_conversations()
            .map(|r| r.id.as_str())
            .collect::<Vec<_>>(),
        vec!["one"]
    );
    assert!(state.conversations[0].title.is_empty());
}
