//! Observe native streaming and original-response recovery through Core's real
//! event channel, queue, writer and history. The HTTP provider alone is fixed.

use super::*;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

async fn collect_until(fixture: &HostedFixture, complete: bool) -> Result<Vec<EventMsg>> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let mut events = Vec::new();
        loop {
            let event =
                wait_for_event_match(&fixture.test.codex, |event| Some(event.clone())).await;
            let end = matches!(&event, EventMsg::TurnComplete(_) if complete)
                || matches!(&event, EventMsg::Error(_) if !complete);
            ensure!(
                !matches!(&event, EventMsg::TurnAborted(_)),
                "original hosted turn unexpectedly aborted"
            );
            ensure!(
                !complete || !matches!(&event, EventMsg::Error(_)),
                "original-response recovery failed: {event:?}"
            );
            ensure!(
                complete || !matches!(&event, EventMsg::TurnComplete(_)),
                "partial stream created a false successful terminal"
            );
            events.push(event);
            ensure!(events.len() <= 1024, "fixture event budget exhausted");
            if end {
                return Ok(events);
            }
        }
    })
    .await
    .context("actual Core stream observation deadline")?
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn long_native_stream_and_recovered_completion_share_original_ui_item_and_operation()
-> Result<()> {
    let server = MockServer::start().await;
    let fragments = [
        "细胞学习与工具反馈。".repeat(350),
        "保留原始响应并继续。".repeat(350),
    ];
    let text = fragments.concat();
    assert!(text.len() > 8 * 1024);
    let item = json!({"type":"message","id":"provider-long-item","role":"assistant","phase":"final_answer",
        "content":[{"type":"output_text","text":text,"annotations":[]}]});
    let mut events = vec![
        json!({"type":"response.created","response":{"id":"response-long-original"}}),
        json!({"type":"response.output_item.added","output_index":0,"item":{
            "type":"message","id":"provider-long-item","role":"assistant","phase":"final_answer","content":[]}}),
    ];
    events.extend(fragments.iter().map(|fragment| {
        json!({"type":"response.output_text.delta",
        "item_id":"provider-long-item","output_index":0,"content_index":0,"delta":fragment})
    }));
    let wire = events
        .into_iter()
        .map(|event| format!("data: {event}\n\n"))
        .collect::<String>();
    Mock::given(method("POST"))
        .and(path("/v1/responses"))
        .respond_with(ResponseTemplate::new(200).set_body_raw(wire, "text/event-stream"))
        .expect(1)
        .mount(&server)
        .await;
    let mut native_agent = agent();
    native_agent.limits.context_bytes = 64 * 1024;
    native_agent.limits.output_tokens = 8192;
    let fixture = HostedFixture::with_agent_and_delivery(
        &server,
        CompletionDelivery::Immediate,
        native_agent,
    )
    .await?;
    let turn_id = fixture.start().await?;
    let streamed = collect_until(&fixture, false).await?;
    let epoch = fixture.recovery_epoch(&turn_id).await?;
    let (original_anchor, pending) = fixture.checkpoint().await?;
    let original_request = pending
        .pending_model
        .as_ref()
        .context("original pending model operation")?
        .clone();
    assert_eq!(
        pending.provider_response_id.as_deref(),
        Some("response-long-original")
    );
    assert!(pending.final_answer.is_none());
    let started: Vec<_> = streamed
        .iter()
        .filter_map(|event| match event {
            EventMsg::ItemStarted(event) if event.turn_id == turn_id => match &event.item {
                TurnItem::AgentMessage(message) => Some(message.id.clone()),
                _ => None,
            },
            _ => None,
        })
        .collect();
    assert_eq!(started.len(), 1);
    let canonical_id = started[0].clone();
    assert_ne!(canonical_id, "provider-long-item");
    let deltas: Vec<_> = streamed
        .iter()
        .filter_map(|event| match event {
            EventMsg::AgentMessageContentDelta(delta) => Some(delta),
            _ => None,
        })
        .collect();
    assert_eq!(deltas.len(), fragments.len());
    for delta in &deltas {
        assert_eq!(
            (&delta.thread_id, &delta.turn_id, &delta.item_id),
            (
                &fixture.test.session_configured.thread_id.to_string(),
                &turn_id,
                &canonical_id
            )
        );
    }
    assert_eq!(
        deltas
            .iter()
            .map(|delta| delta.delta.as_str())
            .collect::<String>(),
        text
    );
    assert!(streamed.iter().all(|event| !matches!(event,
        EventMsg::ItemCompleted(event) if matches!(&event.item, TurnItem::AgentMessage(_)))));
    let history_before = fixture.history().await?;
    assert!(
        history_before
            .items
            .iter()
            .all(|entry| !matches!(entry, RolloutItem::EventMsg(EventMsg::TurnComplete(_))))
    );

    Mock::given(method("GET"))
        .and(path("/v1/responses/response-long-original"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(json!({"id":"response-long-original",
            "status":"completed","output":[item],"usage":{"input_tokens":3,"output_tokens":7000}})),
        )
        .expect(1)
        .mount(&server)
        .await;
    assert_eq!(
        fixture
            .test
            .codex
            .recover_turn_if_idle(codex_core::RecoverTurnRequest {
                turn_id: turn_id.clone(),
                expected_epoch: epoch,
                thread_settings: Default::default(),
                trace: None,
            })
            .await?,
        codex_core::StartIfIdleSubmission::Started {
            turn_id: turn_id.clone()
        }
    );
    let recovered = collect_until(&fixture, true).await?;
    let completed_ids: Vec<_> = recovered
        .iter()
        .filter_map(|event| match event {
            EventMsg::ItemCompleted(event) if event.turn_id == turn_id => match &event.item {
                TurnItem::AgentMessage(message) => Some(message.id.clone()),
                _ => None,
            },
            _ => None,
        })
        .collect();
    assert_eq!(completed_ids, vec![canonical_id.clone()]);
    assert!(
        recovered
            .iter()
            .all(|event| !matches!(event, EventMsg::AgentMessageContentDelta(_))),
        "GET observation must not replay provisional deltas"
    );
    let (after_anchor, completed) = fixture.checkpoint().await?;
    assert_eq!(after_anchor, original_anchor);
    assert_eq!(completed.final_answer.as_deref(), Some(text.as_str()));
    assert_eq!((completed.model_calls, completed.tool_calls), (1, 0));
    assert!(completed.context.starts_with(&pending.context));
    assert_eq!(completed.context.len(), pending.context.len() + 1);
    assert_eq!(completed.context.last(), Some(&item));
    assert!(completed.pending_model.is_none());
    let durable = crate::native_turn_checkpoint::encode(&after_anchor, &completed)?;
    let (decoded_anchor, decoded) =
        crate::native_turn_checkpoint::decode(&durable, &after_anchor.checkpoint)?;
    assert_eq!(decoded_anchor, after_anchor);
    assert_eq!(decoded.context, completed.context);
    let request = fixture
        .base
        .writer
        .resolve_operation_request(
            &original_request.operation_id,
            fixture.native.model.destination_id(),
        )
        .await?;
    assert_eq!(
        request.payload_json.as_bytes(),
        original_request.body.as_slice()
    );
    assert_eq!(
        fixture
            .base
            .writer
            .status(&original_request.operation_id)
            .await?,
        LocalOutcomeState::Committed
    );

    let history = fixture.history().await?;
    let original_inputs = history.items.iter().filter(|entry| matches!(entry,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if matches!(&event.item,
            TurnItem::UserMessage(message) if message.client_id.as_deref() == Some("client:hosted-queue")))).count();
    assert_eq!(original_inputs, 1);
    let response_ids = history
        .items
        .iter()
        .filter_map(|entry| match entry {
            RolloutItem::ResponseItem(envelope)
                if matches!(&envelope.item,
            codex_protocol::models::ResponseItem::Message { role, .. } if role == "assistant") =>
            {
                Some(
                    envelope
                        .item
                        .id()
                        .context("persisted canonical assistant id")
                        .map(ToString::to_string),
                )
            }
            _ => None,
        })
        .collect::<Result<Vec<_>>>()?;
    assert_eq!(response_ids, vec![canonical_id]);
    let requests = server
        .received_requests()
        .await
        .context("actual HTTP capture")?;
    assert_eq!(
        (
            requests
                .iter()
                .filter(|r| r.method.as_str() == "POST")
                .count(),
            requests
                .iter()
                .filter(|r| r.method.as_str() == "GET")
                .count(),
            fixture.resolver.calls.load(Ordering::SeqCst),
            fixture.base.issuer.grants.load(Ordering::SeqCst)
        ),
        (1, 1, 1, 1)
    );
    let duplicate = fixture
        .service
        .reconcile(
            fixture.test.session_configured.thread_id,
            None,
            fixture.input.clone(),
            fixture.payload_sha256.clone(),
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    assert_eq!(
        duplicate.outcome,
        QueueReconcileOutcome::Persisted { turn_id }
    );
    assert!(
        fixture
            .service
            .list(fixture.test.session_configured.thread_id)
            .await?
            .is_empty()
    );
    fixture.shutdown().await
}
