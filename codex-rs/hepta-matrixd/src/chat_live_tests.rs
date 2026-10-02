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
#[test]
fn streams_scoped_text_without_cross_room_projection() {
    let mut live = LiveTimeline::default();
    live.observe(delta("a", "m", "hello"));
    live.observe(delta("a", "m", " world"));
    live.observe(delta("b", "n", "private"));
    let mut rows = vec![];
    let mut active = Some("turn".into());
    live.merge("a", &mut rows, 10, &mut active);
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
    let mut active = Some("turn".into());
    live.merge("a", &mut rows, 1, &mut active);
    assert_eq!(rows.len(), 1);
    assert!(rows[0].body.len() <= MAX_CHAT_TEXT_BYTES);
    assert!(rows[0].body.chars().all(|c| c == '你'));
}
#[test]
fn completion_observation_overrides_stale_active_snapshot() {
    let mut live = LiveTimeline::default();
    live.turn("a".into(), None);
    let mut active = Some("stale".into());
    live.merge("a", &mut vec![], 1, &mut active);
    assert_eq!(active, None);
}
