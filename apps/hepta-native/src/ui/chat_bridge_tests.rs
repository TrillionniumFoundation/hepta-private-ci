use super::*;
use crate::chat_runtime::wire::ChatMessage;
use crate::ui::input_event_tests::app_fixture;

fn room(id: &str) -> chat_model::Conversation {
    chat_model::Conversation {
        id: id.into(),
        title: id.into(),
        preview: String::new(),
        unread: 0,
    }
}

#[test]
fn stale_timeline_cannot_cross_room_or_selection_epoch() {
    let root = tempfile::TempDir::new().unwrap();
    let mut native = app_fixture(root.path());
    let app = &mut native.chat_shell;
    app.chat.conversations = vec![room("a"), room("b")];
    app.chat.select("a");
    let epoch = app.chat.selection_epoch;
    app.chat.select("b");
    let result = ChatResult::Timeline {
        thread_id: "a".into(),
        data: vec![ChatMessage {
            id: "m1".into(),
            turn_id: "t1".into(),
            sender: "fixture".into(),
            body: "private fixture".into(),
        }],
        next_cursor: None,
        active_turn_id: None,
    };
    app.apply_chat_result(
        result,
        ChatCommand::Timeline {
            thread_id: "a".into(),
            cursor: None,
            limit: 50,
        },
        epoch,
    );
    assert!(app.chat.messages.is_empty());
    assert_eq!(app.chat.selected.as_deref(), Some("b"));
}

#[test]
fn queued_send_retains_draft_until_server_persistence_and_never_fakes_message() {
    let root = tempfile::TempDir::new().unwrap();
    let mut native = app_fixture(root.path());
    let app = &mut native.chat_shell;
    app.chat.conversations = vec![room("a")];
    app.chat.select("a");
    app.chat.draft = "original".into();
    app.chat.sending = true;
    app.chat_bridge.submission = Some(("a".into(), "op".into(), "original".into()));
    let command = ChatCommand::Send {
        thread_id: "a".into(),
        operation_id: "op".into(),
        text: "original".into(),
    };
    app.apply_chat_result(
        ChatResult::Submission {
            operation_id: "op".into(),
            state: SubmissionState::Queued {
                queue_id: "queue".into(),
            },
        },
        command.clone(),
        app.chat.selection_epoch,
    );
    assert_eq!(app.chat.draft, "original");
    assert!(app.chat.sending);
    assert!(app.chat.messages.is_empty());
    app.apply_chat_result(
        ChatResult::Submission {
            operation_id: "op".into(),
            state: SubmissionState::Persisted {
                turn_id: "turn".into(),
            },
        },
        command,
        app.chat.selection_epoch,
    );
    assert!(app.chat.draft.is_empty());
    assert!(!app.chat.sending);
    assert!(app.chat.messages.is_empty());
}

#[test]
fn persistence_cannot_erase_new_draft_or_another_room() {
    let root = tempfile::TempDir::new().unwrap();
    let mut native = app_fixture(root.path());
    let app = &mut native.chat_shell;
    app.chat.conversations = vec![room("a"), room("b")];
    app.chat.select("a");
    app.chat.draft = "new thought".into();
    app.chat.select("b");
    app.chat.draft = "other room".into();
    app.chat_bridge.submission = Some(("a".into(), "op".into(), "original".into()));
    app.apply_chat_result(
        ChatResult::Submission {
            operation_id: "op".into(),
            state: SubmissionState::Persisted {
                turn_id: "turn".into(),
            },
        },
        ChatCommand::Reconcile {
            thread_id: "a".into(),
            operation_id: "op".into(),
            text: "original".into(),
        },
        app.chat.selection_epoch,
    );
    assert_eq!(app.chat.draft, "other room");
    app.chat.select("a");
    assert_eq!(app.chat.draft, "new thought");
}

#[test]
fn missing_reconciliation_is_visible_and_never_automatically_resends() {
    let root = tempfile::TempDir::new().unwrap();
    let mut native = app_fixture(root.path());
    let app = &mut native.chat_shell;
    app.chat.draft = "original".into();
    app.chat.sending = true;
    app.chat_bridge.submission = Some(("a".into(), "op".into(), "original".into()));
    app.apply_chat_result(
        ChatResult::Submission {
            operation_id: "op".into(),
            state: SubmissionState::Missing,
        },
        ChatCommand::Reconcile {
            thread_id: "a".into(),
            operation_id: "op".into(),
            text: "original".into(),
        },
        0,
    );
    assert_eq!(app.chat.draft, "original");
    assert!(!app.chat.sending);
    assert!(app.chat_bridge.submission.is_none());
    assert!(app.chat_bridge.pending.is_empty());
    assert!(app.chat_bridge.error.is_some());
}

#[test]
fn repeated_create_clicks_cannot_admit_duplicate_owner_requests() {
    let root = tempfile::TempDir::new().unwrap();
    let mut native = app_fixture(root.path());
    let app = &mut native.chat_shell;
    app.chat_bridge.pending.push_back((ChatCommand::Create, 0));
    assert!(app.request_chat(ChatCommand::Create).is_ok());
    assert_eq!(app.chat_bridge.pending.len(), 1);
    assert!(app.chat.conversations.is_empty());
}
