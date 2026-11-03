//! Real SSE UI observations and recovery of the same provider operation.

use super::*;
use pretty_assertions::assert_eq;

#[derive(Default)]
struct Events {
    events: Mutex<Vec<NativeTextDelta>>,
    fail: bool,
    stall: bool,
}

impl NativeEventSink for Events {
    async fn emit(&self, _: &TurnBinding, event: NativeEvent) -> Result<()> {
        if self.fail {
            bail!("host UI delivery unavailable");
        }
        if self.stall {
            return std::future::pending().await;
        }
        let NativeEvent::TextDelta(delta) = event;
        self.events.lock().unwrap().push(delta);
        Ok(())
    }
}

fn streamed_answer() -> (String, Value) {
    let mut events = vec![json!({"type":"response.created","response":{"id":"resp-ui"}})];
    let mut output = Vec::new();
    for (index, (id, fragments)) in [("msg-a", vec!["细", "胞"]), ("msg-b", vec!["学习", "完成"])]
        .into_iter()
        .enumerate()
    {
        events.push(json!({"type":"response.output_item.added","output_index":index,
            "item":{"type":"message","role":"assistant","id":id,"phase":"final_answer","content":[]}}));
        for fragment in &fragments {
            events.push(
                json!({"type":"response.output_text.delta","item_id":id,"output_index":index,
                "content_index":0,"delta":fragment}),
            );
        }
        let item = json!({"type":"message","role":"assistant","id":id,"phase":"final_answer",
            "content":[{"type":"output_text","text":fragments.concat()}]});
        events.push(json!({"type":"response.output_item.done","output_index":index,"item":item}));
        output.push(item);
    }
    let terminal =
        json!({"id":"resp-ui","status":"completed","output":output,"usage":{"output_tokens":4}});
    events.push(json!({"type":"response.completed","response":terminal}));
    (
        events
            .into_iter()
            .map(|event| format!("data: {event}\n\n"))
            .collect(),
        terminal,
    )
}

#[tokio::test]
async fn chinese_multi_item_deltas_keep_original_operation_and_absolute_context_index() -> Result<()>
{
    let (agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    let original = state.context.clone();
    let (body, _) = streamed_answer();
    let (model, requests) = model_server(vec![body]).await?;
    let events = Events::default();
    assert_eq!(
        agent
            .run_with_events(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new(),
                &events
            )
            .await?,
        RunOutcome::Completed("细胞学习完成".to_owned())
    );
    assert_eq!(&state.context[..original.len()], original.as_slice());
    let events = events.events.lock().unwrap();
    assert_eq!(events.len(), 4);
    for (index, event) in events.iter().enumerate() {
        assert_eq!(event.operation_id, "operation:original:model:0");
        assert_eq!(event.response_id, "resp-ui");
        assert_eq!(event.context_index, original.len() + index / 2);
        assert_eq!(event.output_index, index / 2);
        assert_eq!(event.content_index, 0);
        assert_eq!(event.phase.as_deref(), Some("final_answer"));
    }
    assert_eq!(
        events
            .iter()
            .map(|event| event.text.as_str())
            .collect::<String>(),
        "细胞学习完成"
    );
    assert_eq!(requests.lock().unwrap().len(), 1);
    Ok(())
}

#[tokio::test]
async fn recorded_late_phase_stream_settles_original_context_and_ui_without_repost() -> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    let original = state.context.clone();
    let (model, requests) = model_server(vec![
        crate::responses::tests::RECORDED_LATE_PHASE_SSE.to_owned(),
    ])
    .await?;
    let events = Events::default();
    assert_eq!(
        agent
            .run_with_events(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new(),
                &events,
            )
            .await?,
        RunOutcome::Completed("HEPTA_REPRESENTATIVE_OK".to_owned())
    );
    assert_eq!(&state.context[..original.len()], original.as_slice());
    assert_eq!(state.context.len(), original.len() + 2);
    assert_eq!(state.context[original.len()]["type"], "reasoning");
    let message_index = original.len() + 1;
    let message = &state.context[message_index];
    assert_eq!(message["id"], "msg_DbgCXlRsjTEBWuoQkxZ6GDFIGp4fwJM2");
    assert_eq!(message["phase"], "final_answer");
    let observed = events.events.lock().unwrap().clone();
    assert_eq!(observed.len(), 7);
    for delta in &observed {
        assert_eq!(delta.operation_id, "operation:original:model:0");
        assert_eq!(delta.response_id, "resp_6kLkrbv85JxhIrO4fVxDk88es1OzOc0W");
        assert_eq!(delta.provider_item_id, message["id"].as_str().unwrap());
        assert_eq!(delta.context_index, message_index);
        assert_eq!((delta.output_index, delta.content_index), (1, 0));
        assert_eq!(delta.phase, None);
    }
    let streamed = observed
        .iter()
        .map(|delta| delta.text.as_str())
        .collect::<String>();
    assert_eq!(message["content"][0]["text"], streamed);
    assert_eq!(state.final_answer.as_deref(), Some(streamed.as_str()));
    assert!(state.pending_model.is_none());
    assert!(state.last_error.is_none());
    assert_eq!(state.model_usage[0]["output_tokens"], 46);

    // Reopening the owner's settled snapshot must neither POST nor replay UI.
    let mut restored = owner.snapshots.lock().unwrap().last().unwrap().clone();
    assert!(restored.pending_model.is_none());
    assert_eq!(restored.context, state.context);
    let resumed_events = Events::default();
    assert_eq!(
        agent
            .run_with_events(
                owner.as_ref(),
                &tools,
                &model,
                &mut restored,
                &CancellationToken::new(),
                &resumed_events,
            )
            .await?,
        RunOutcome::Completed(streamed)
    );
    assert!(resumed_events.events.lock().unwrap().is_empty());
    assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 1);
    assert_eq!(requests.lock().unwrap().len(), 1);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn failed_or_timed_out_ui_delivery_recovers_with_get_without_another_post() -> Result<()> {
    for stall in [false, true] {
        let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
        if stall {
            agent.limits.model_timeout = Duration::from_millis(50);
        }
        let (body, terminal) = streamed_answer();
        let (model, requests) = model_server(vec![body, terminal.to_string()]).await?;
        let events = Events {
            fail: !stall,
            stall,
            ..Events::default()
        };
        assert_eq!(
            agent
                .run_with_events(
                    owner.as_ref(),
                    &tools,
                    &model,
                    &mut state,
                    &CancellationToken::new(),
                    &events
                )
                .await?,
            RunOutcome::PendingModel
        );
        let original = state.pending_model.as_ref().unwrap().clone();
        assert_eq!(state.context.len(), 1);
        assert_eq!(state.provider_response_id.as_deref(), Some("resp-ui"));
        state = owner.snapshots.lock().unwrap().last().unwrap().clone();
        assert_eq!(state.pending_model.as_ref().unwrap().body, original.body);
        let resumed_events = Events::default();
        assert_eq!(
            agent
                .run_with_events(
                    owner.as_ref(),
                    &tools,
                    &model,
                    &mut state,
                    &CancellationToken::new(),
                    &resumed_events
                )
                .await?,
            RunOutcome::Completed("细胞学习完成".to_owned())
        );
        assert!(resumed_events.events.lock().unwrap().is_empty());
        assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 1);
        let requests = requests.lock().unwrap();
        assert_eq!(requests.len(), 2);
        assert_eq!(
            requests[1]["request_line"],
            "GET /v1/responses/resp-ui HTTP/1.1"
        );
        assert!(state.pending_model.is_none());
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    }
    Ok(())
}

#[tokio::test]
async fn large_chinese_delta_uses_bounded_utf8_fragments_without_inventing_completion() -> Result<()>
{
    let (agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    let text = "细胞".repeat(6000);
    let body: String = [
        json!({"type":"response.created","response":{"id":"resp-large"}}),
        json!({"type":"response.output_text.delta","item_id":"msg-large","output_index":0,
            "content_index":0,"delta":text}),
    ]
    .into_iter()
    .map(|event| format!("data: {event}\n\n"))
    .collect();
    let (model, _) = model_server(vec![body]).await?;
    let events = Events::default();
    assert_eq!(
        agent
            .run_with_events(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new(),
                &events
            )
            .await?,
        RunOutcome::PendingModel
    );
    let events = events.events.lock().unwrap();
    assert_eq!(events.len(), 2);
    assert!(events.iter().all(|event| event.text.len() <= 32 * 1024));
    assert_eq!(
        events
            .iter()
            .map(|event| event.text.as_str())
            .collect::<String>(),
        text
    );
    assert!(state.final_answer.is_none());
    assert!(state.pending_model.is_some());
    assert_eq!(state.context.len(), 1);
    Ok(())
}

#[tokio::test]
async fn long_chinese_message_settles_and_recovers_original_response_without_repost() -> Result<()>
{
    for complete_stream in [true, false] {
        let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
        agent.limits.context_bytes = 64 * 1024;
        agent.limits.output_tokens = 8192;
        let text = "细胞学习与工具反馈。".repeat(700);
        assert!(text.len() > 8 * 1024);
        let item = json!({"type":"message","role":"assistant","id":"msg-long-chat","phase":"final_answer",
            "content":[{"type":"output_text","text":text,"annotations":[]}]});
        let terminal = json!({"id":"resp-long-chat","status":"completed","output":[item],
            "usage":{"input_tokens":10,"output_tokens":7000}});
        let mut wire = vec![
            json!({"type":"response.created","response":{"id":"resp-long-chat"}}),
            json!({"type":"response.output_item.added","output_index":0,
                "item":{"type":"message","role":"assistant","id":"msg-long-chat","phase":"final_answer","content":[]}}),
            json!({"type":"response.output_text.delta","item_id":"msg-long-chat","output_index":0,
                "content_index":0,"delta":text}),
        ];
        if complete_stream {
            wire.push(json!({"type":"response.output_item.done","output_index":0,"item":item}));
            wire.push(json!({"type":"response.completed","response":terminal}));
        }
        let body = wire
            .into_iter()
            .map(|event| format!("data: {event}\n\n"))
            .collect();
        let (model, requests) = model_server_with_limit(
            if complete_stream {
                vec![body]
            } else {
                vec![body, terminal.to_string()]
            },
            128 * 1024,
        )
        .await?;
        let original_context = state.context.clone();
        let events = Events::default();
        let first = agent
            .run_with_events(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new(),
                &events,
            )
            .await?;
        assert_eq!(
            events
                .events
                .lock()
                .unwrap()
                .iter()
                .map(|event| event.text.as_str())
                .collect::<String>(),
            text
        );
        if !complete_stream {
            assert_eq!(first, RunOutcome::PendingModel);
            assert_eq!(state.context, original_context);
            let pending = state.pending_model.as_ref().unwrap().clone();
            state = owner.snapshots.lock().unwrap().last().unwrap().clone();
            assert_eq!(state.pending_model.as_ref().unwrap().body, pending.body);
            assert_eq!(
                state.pending_model.as_ref().unwrap().operation_id,
                pending.operation_id
            );
            let resumed_events = Events::default();
            assert_eq!(
                agent
                    .run_with_events(
                        owner.as_ref(),
                        &tools,
                        &model,
                        &mut state,
                        &CancellationToken::new(),
                        &resumed_events
                    )
                    .await?,
                RunOutcome::Completed(text.clone())
            );
            assert!(resumed_events.events.lock().unwrap().is_empty());
            assert_eq!(
                requests.lock().unwrap()[1]["request_line"],
                "GET /v1/responses/resp-long-chat HTTP/1.1"
            );
        } else {
            assert_eq!(first, RunOutcome::Completed(text.clone()));
        }
        assert_eq!(
            &state.context[..original_context.len()],
            original_context.as_slice()
        );
        assert_eq!(state.context.last(), Some(&item));
        assert_eq!(state.final_answer.as_deref(), Some(text.as_str()));
        assert!(state.pending_model.is_none());
        assert_eq!(
            owner.snapshots.lock().unwrap().last().unwrap().context,
            state.context
        );
        assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 1);
        assert_eq!(
            requests.lock().unwrap().len(),
            if complete_stream { 1 } else { 2 }
        );
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    }
    Ok(())
}
