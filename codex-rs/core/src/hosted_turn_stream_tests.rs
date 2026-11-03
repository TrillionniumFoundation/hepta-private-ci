use super::*;
use crate::hosted_turn::HostedTextDelta;
use crate::session::tests::make_session_and_context_with_rx;
use codex_protocol::protocol::EventMsg;
use pretty_assertions::assert_eq;
use serde_json::json;

#[tokio::test]
async fn hosted_text_stream_reaches_original_events_before_completion() -> Result<()> {
    let (session, context, events) = make_session_and_context_with_rx().await;
    let entry = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    for text in ["正在", "处理原任务"] {
        entry
            .emit_text_delta(HostedTextDelta {
                item_id: "msg_original".to_owned(),
                text: text.to_owned(),
                phase: None,
            })
            .await?;
    }
    let mut projected = Vec::new();
    while let Ok(event) = events.try_recv() {
        match event.msg {
            EventMsg::ItemStarted(item) => {
                projected.push(json!({"event":"started","id":item.item.id()}))
            }
            EventMsg::AgentMessageContentDelta(item) => {
                assert_eq!(
                    (item.thread_id, item.turn_id),
                    (session.thread_id.to_string(), context.sub_id.clone())
                );
                projected.push(json!({"event":"delta","id":item.item_id,"text":item.delta}));
            }
            EventMsg::ItemCompleted(_) => {
                anyhow::bail!("a provisional text delta completed the item")
            }
            _ => {}
        }
    }
    insta::assert_snapshot!(serde_json::to_string_pretty(&projected).expect("stream JSON"), @r#"
    [
      {
        "event": "started",
        "id": "msg_original"
      },
      {
        "event": "delta",
        "id": "msg_original",
        "text": "正在"
      },
      {
        "event": "delta",
        "id": "msg_original",
        "text": "处理原任务"
      }
    ]
    "#);
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    Ok(())
}

#[tokio::test]
async fn replaced_hosted_task_cannot_stream_into_successor() -> Result<()> {
    let (session, context, events) = make_session_and_context_with_rx().await;
    let old = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    let _current = attach(&session, &context, Arc::new(AtomicBool::new(true))).await?;
    while events.try_recv().is_ok() {}
    assert!(
        old.emit_text_delta(HostedTextDelta {
            item_id: "msg_stale".to_owned(),
            text: "stale output".to_owned(),
            phase: None,
        })
        .await
        .is_err()
    );
    while let Ok(event) = events.try_recv() {
        assert!(!matches!(
            event.msg,
            EventMsg::AgentMessageContentDelta(_) | EventMsg::ItemStarted(_)
        ));
    }
    session.abort_all_tasks(TurnAbortReason::Interrupted).await;
    Ok(())
}
