use super::run;
use crate::realtime_conversation::RealtimeHandoffOutputGate;
use crate::realtime_conversation::RealtimeHandoffState;
use crate::realtime_conversation::RealtimeSessionKind;
use crate::realtime_conversation::RealtimeStartOutput;
use crate::session::tests::make_session_and_context_with_rx;
use codex_api::RealtimeEvent;
use codex_api::RealtimeEventParser;
use codex_protocol::protocol::CodexResponseHandoffMode;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::RealtimeHandoffRequested;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use test_case::test_case;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

#[test_case(false; "natural_transport_close")]
#[test_case(true; "explicit_stop")]
#[tokio::test]
async fn joined_fanout_preserves_parsed_events_and_tail_after_transport_end(explicit_stop: bool) {
    let (session, _turn, events) = make_session_and_context_with_rx().await;
    // Keep normal admission's original rejection deterministic. The route must
    // still attempt both the parsed handoff and tail; neither can start a turn.
    session.begin_shutdown();
    let (output_tx, output_rx) = async_channel::bounded(/*cap*/ 1);
    let (events_tx, events_rx) = async_channel::bounded(/*cap*/ 2);
    let (tail_tx, transcript_tail_rx) = async_channel::bounded(/*cap*/ 1);
    let stop_token = CancellationToken::new();
    let realtime_active = Arc::new(AtomicBool::new(!explicit_stop));
    if explicit_stop {
        stop_token.cancel();
    }
    let handoff = RealtimeEvent::HandoffRequested(RealtimeHandoffRequested {
        handoff_id: "parsed-before-close".to_string(),
        item_id: "parsed-item".to_string(),
        input_transcript: "original parsed handoff".to_string(),
        active_transcript: Vec::new(),
    });
    let following = RealtimeEvent::ConversationItemDone {
        item_id: "following-event".to_string(),
    };
    events_tx
        .send(handoff.clone())
        .await
        .expect("parsed handoff");
    events_tx
        .send(following.clone())
        .await
        .expect("following event");
    tail_tx
        .send("original transcript tail".to_string())
        .await
        .expect("tail");
    drop(events_tx);
    drop(tail_tx);
    drop(output_rx);
    run(
        Arc::clone(&session),
        "original-conversation".to_string(),
        RealtimeStartOutput {
            realtime_active: Arc::clone(&realtime_active),
            handoff: RealtimeHandoffState {
                identity: Arc::new(()),
                output_gate: Arc::new(RealtimeHandoffOutputGate::default()),
                output_tx,
                last_output: Arc::new(Mutex::new(/*t*/ None)),
                stream: Arc::new(Mutex::new(Default::default())),
                client_managed_handoffs: false,
                codex_responses_as_items: false,
                codex_response_item_prefix: None,
                codex_response_handoff_mode: CodexResponseHandoffMode::Thinking,
                codex_response_handoff_channel_prefixes: Arc::new(BTreeMap::new()),
                session_kind: RealtimeSessionKind::V1,
                event_parser: RealtimeEventParser::V1,
            },
            stop_token,
            events_rx,
            transcript_tail_rx,
            sdp: None,
        },
    )
    .await;
    let mut order = Vec::new();
    let mut forwarded = Vec::new();
    while let Ok(event) = events.try_recv() {
        match event.msg {
            EventMsg::Error(error) => {
                assert_eq!(error.message, "failed to submit turn input: NotIdle");
                order.push("refused");
            }
            EventMsg::RealtimeConversationRealtime(event) => {
                order.push("forwarded");
                forwarded.push(event.payload);
            }
            EventMsg::RealtimeConversationClosed(_) => order.push("closed"),
            _ => {}
        }
    }
    assert_eq!(forwarded, vec![handoff, following]);
    let mut expected = vec!["refused", "forwarded", "forwarded", "refused"];
    if !explicit_stop {
        expected.push("closed");
    }
    assert_eq!(order, expected);
    assert!(!realtime_active.load(Ordering::Relaxed));
    assert!(session.active_turn.lock().await.is_none());
}
