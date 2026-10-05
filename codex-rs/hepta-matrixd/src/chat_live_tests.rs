use super::super::wire::MAX_CHAT_TEXT_BYTES;
use super::*;
use codex_app_server_protocol::AgentMessageDeltaNotification;
fn delta(thread: &str, item: &str, text: &str) -> ServerNotification {
    ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
        thread_id: thread.into(),
        turn_id: "turn".into(),
        item_id: item.into(),
        delta: text.into(),
    })
}
fn window() -> ActiveItemWindow {
    ActiveItemWindow::Complete {
        turn_id: "turn".into(),
        ids: BTreeSet::new(),
    }
}

#[test]
fn streams_scoped_text_without_cross_room_projection() {
    let mut live = LiveTimeline::default();
    live.observe(delta("a", "m", "hello"));
    live.observe(delta("a", "m", " world"));
    live.observe(delta("b", "n", "private"));
    let mut rows = vec![];
    live.merge("a", &mut rows, 10, "turn", &window());
    assert_eq!(
        rows,
        vec![ChatMessage {
            id: "m".into(),
            turn_id: "turn".into(),
            sender: "assistant".into(),
            body: "hello world".into()
        }]
    );
}
#[test]
fn cache_and_unicode_delta_growth_remain_bounded() {
    let mut live = LiveTimeline::default();
    for i in 0..100 {
        live.observe(delta("a", &format!("m{i}"), "你"));
    }
    assert_eq!(live.messages.len(), MAX_CHAT_PAGE as usize);
    live.observe(delta("a", "m99", &"你".repeat(MAX_CHAT_TEXT_BYTES)));
    let mut rows = vec![];
    live.merge("a", &mut rows, 1, "turn", &window());
    assert_eq!(rows.len(), 1);
    assert!(rows[0].body.len() <= MAX_CHAT_TEXT_BYTES);
    assert!(rows[0].body.ends_with(super::super::TRUNCATION_MARKER));
    assert!(
        rows[0]
            .body
            .trim_end_matches(super::super::TRUNCATION_MARKER)
            .chars()
            .all(|c| c == '你')
    );
}
#[test]
fn persisted_rows_and_new_active_turn_cannot_regress_to_stale_cache() {
    let mut live = LiveTimeline::default();
    live.observe(delta("a", "m", "old partial"));
    live.observe(delta("a", "old-extra", "old turn"));
    let authoritative = ChatMessage {
        id: "m".into(),
        turn_id: "turn".into(),
        sender: "assistant".into(),
        body: "new authoritative completed text".into(),
    };
    let mut rows = vec![authoritative.clone()];
    live.merge("a", &mut rows, 10, "new-turn", &window());
    assert_eq!(rows, vec![authoritative]);
}

#[test]
fn completed_message_replaces_marked_streaming_prefix() {
    use codex_app_server_protocol::ItemCompletedNotification;
    use codex_app_server_protocol::ThreadItem;
    let mut live = LiveTimeline::default();
    live.observe(delta("a", "m", &"🙂".repeat(MAX_CHAT_TEXT_BYTES)));
    live.observe(delta("a", "m", "must not erase the truncation marker"));
    let mut rows = vec![];
    live.merge("a", &mut rows, 10, "turn", &window());
    assert!(rows[0].body.ends_with(super::super::TRUNCATION_MARKER));
    assert!(rows[0].body.len() <= MAX_CHAT_TEXT_BYTES);
    live.observe(ServerNotification::ItemCompleted(
        ItemCompletedNotification {
            thread_id: "a".into(),
            turn_id: "turn".into(),
            completed_at_ms: 1,
            item: ThreadItem::AgentMessage {
                id: "m".into(),
                text: "complete authoritative text".into(),
                phase: None,
                memory_citation: None,
                delivery: None,
            },
        },
    ));
    rows.clear(); // A new RPC page, not the previous UI projection.
    live.merge("a", &mut rows, 10, "turn", &window());
    assert_eq!(rows[0].body, "complete authoritative text");
}

#[test]
fn cached_older_same_turn_never_displaces_a_full_authoritative_page() {
    let mut live = LiveTimeline::default();
    live.observe(delta("a", "older", "cached older text"));
    let authoritative: Vec<_> = (0..MAX_CHAT_PAGE)
        .map(|i| ChatMessage {
            id: format!("new-{i}"),
            turn_id: "turn".into(),
            sender: "assistant".into(),
            body: format!("new row {i}"),
        })
        .collect();
    let mut rows = authoritative.clone();
    live.merge("a", &mut rows, MAX_CHAT_PAGE, "turn", &window());
    assert_eq!(rows, authoritative);
}
#[test]
fn complete_raw_item_membership_and_partial_pages_block_old_cache_insertion() {
    use codex_app_server_protocol::ThreadItem;
    let mut live = LiveTimeline::default();
    live.observe(delta("a", "older", "cached older text"));
    let raw = ThreadItemEntry {
        turn_id: "turn".into(),
        item: ThreadItem::Plan {
            id: "older".into(),
            text: "not a displayed message".into(),
        },
    };
    let make = |cursor| ThreadItemsListResponse {
        data: vec![raw.clone()],
        next_cursor: cursor,
        backwards_cursor: None,
    };
    for proof in [
        ActiveItemWindow::from_response(make(None), "turn"),
        ActiveItemWindow::from_response(make(Some("older-page".into())), "turn"),
        ActiveItemWindow::from_response(make(None), "other-turn"),
    ] {
        let mut rows = vec![];
        live.merge("a", &mut rows, 10, "turn", &proof);
        assert!(rows.is_empty());
    }
    let oversized = ThreadItemsListResponse {
        data: vec![raw; MAX_CHAT_PAGE as usize + 1],
        next_cursor: None,
        backwards_cursor: None,
    };
    assert!(matches!(
        ActiveItemWindow::from_response(oversized, "turn"),
        ActiveItemWindow::Incomplete
    ));
}

#[test]
fn persisted_final_row_wins_even_when_matching_turn_proof_omits_its_id() {
    let mut live = LiveTimeline::default();
    live.observe(delta("a", "m", "stale partial"));
    let final_row = ChatMessage {
        id: "m".into(),
        turn_id: "turn".into(),
        sender: "assistant".into(),
        body: "authoritative final row".into(),
    };
    let mut rows = vec![final_row.clone()];
    live.merge("a", &mut rows, 10, "turn", &window());
    assert_eq!(rows, vec![final_row]);
}
