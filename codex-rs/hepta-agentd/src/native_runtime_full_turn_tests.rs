//! Full owner composition inside the existing isolated real-process fixture.
//! The provider is localhost HTTP/SSE; tool execution and all durable owners
//! are real. This does not qualify a live model, SSH, or daemon startup.

use codex_protocol::models::ResponseItem;
use pretty_assertions::assert_eq;

use super::*;

pub(super) async fn exercise(root: &Path) -> Result<Value> {
    let server = MockServer::start().await;
    ensure!(server.uri().starts_with("http://127.0.0.1:"), "provider fixture must remain on namespace loopback");
    let call = json!({"type":"function_call","call_id":"full-turn","name":"owned_process","arguments":"{}"});
    let answer = json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"full native tool turn complete"}]});
    let replies = [(&call, "response-full-tool"), (&answer, "response-full-final")]
        .into_iter().map(|(item, id)| {
            [json!({"type":"response.created","response":{"id":id}}),
                json!({"type":"response.output_item.done","item":item}),
                json!({"type":"response.completed","response":{"id":id,"status":"completed","output":[item],
                    "usage":{"input_tokens":3,"output_tokens":4}}})]
                .into_iter().map(|event| format!("data: {event}\n\n")).collect::<String>()
        }).collect::<Vec<_>>();
    let posts = Arc::new(AtomicUsize::new(0));
    let received = posts.clone();
    Mock::given(method("POST")).and(path("/v1/responses"))
        .respond_with(move |_request: &wiremock::Request| {
            let index = received.fetch_add(1, Ordering::SeqCst);
            match replies.get(index) {
                Some(events) => ResponseTemplate::new(200).set_body_raw(events.clone(), "text/event-stream"),
                None => ResponseTemplate::new(500).set_body_string("unexpected additional model operation"),
            }
        }).expect(2).mount(&server).await;
    let mut fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    fixture.native.compiler = Arc::new(OwnedCompiler { work: root.join("work") });
    assert!(Arc::ptr_eq(&fixture.writer, &fixture.native.host.writer()));
    // The unchanged worker still starts, publishes real output and exits. The
    // release file only prevents its deliberate test barrier from blocking.
    tokio::fs::write(root.join("work/full-turn.release"), b"allow original child to finish").await?;
    let mut native = agent();
    native.tools = vec![json!({"type":"function","name":"owned_process","description":"Run the owned fixture process",
        "parameters":{"type":"object","properties":{},"additionalProperties":false}})];
    native.limits.model_calls = 2;
    native.limits.tool_timeout = Duration::from_secs(15);
    let result = tokio::time::timeout(Duration::from_secs(30),
        fixture.native.run_turn(&native, fixture.handoff().await?, &CancellationToken::new()),
    ).await.context("full native tool turn exceeded its bounded deadline")??;
    assert_eq!((&result.outcome, result.run.phase, result.run.terminal_observed),
        (&RunOutcome::Completed("full native tool turn complete".to_owned()), RunPhase::Succeeded, true));
    assert_eq!(result.run.run_id, fixture.run.run_id);
    assert_eq!(fixture.state.native_run_receipt(&fixture.run.run_id)?, result.run);
    let tool_output = json!({"exit_code":0,"stdout":"BEGIN full-turn\nEND full-turn\n","stderr":"stderr full-turn\n"});
    let mut expected_context = fixture.initial.context.clone();
    expected_context.extend([call, json!({"type":"function_call_output","call_id":"full-turn","output":tool_output.to_string()}), answer]);
    assert_eq!(result.state.context, expected_context);

    let captured = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(captured.len(), 2);
    let mut operations = BTreeSet::new();
    for (index, sent) in captured.iter().enumerate() {
        let key = sent.headers.get("idempotency-key").context("original model operation header")?.to_str()?;
        assert!(operations.insert(key.to_owned()), "each admitted model call must have its own original key");
        let request = fixture.writer.resolve_operation_request(key, fixture.native.model.destination_id()).await?;
        assert_eq!((request.operation_subject_id.as_str(), request.payload_json.as_bytes()),
            (fixture.writer.owner_agent_id().as_str(), sent.body.as_slice()));
        assert_eq!(fixture.writer.status(key).await?, LocalOutcomeState::Committed);
        let body: Value = serde_json::from_slice(&sent.body)?;
        let prefix = if index == 0 { fixture.initial.context.len() } else { expected_context.len() - 1 };
        assert_eq!(body["input"], json!(&expected_context[..prefix]));
    }

    // Read the original jobs owner's durable record; do not recompute a key or
    // admit a second operation merely to discover the first one's identity.
    let mut jobs = tokio::fs::read_dir(root.join("state/jobs")).await?;
    let mut matching = Vec::new();
    while let Some(entry) = jobs.next_entry().await? {
        if entry.path().extension().and_then(|value| value.to_str()) != Some("json") { continue; }
        let record: Value = serde_json::from_slice(&tokio::fs::read(entry.path()).await?)?;
        if record["host"] == "controlled"
            && record["args"].as_array().and_then(|args| args.last()).and_then(Value::as_str) == Some("full-turn") {
            matching.push(record);
        }
    }
    assert_eq!(matching.len(), 1, "the full turn must create exactly one original runtime job");
    let key = matching[0]["idempotency_key"].as_str().context("original runtime operation key")?;
    let job_id = matching[0]["id"].as_str().context("original runtime job id")?;
    assert!(operations.insert(key.to_owned()));
    assert_eq!(operations.len(), 3);
    let destination = fixture.native.runtime.destination_id();
    let original = fixture.writer.resolve_operation_request(key, destination).await?;
    assert_eq!(original.operation_subject_id.as_str(), fixture.writer.owner_agent_id().as_str());
    let actual_params = fixture.native.runtime.original_params(&original)?;
    let mut expected_params = fixture.native.compiler.compile(&ToolCall {
        call_id: "full-turn".to_owned(), name: "owned_process".to_owned(), arguments: b"{}".to_vec(),
    })?;
    expected_params.idempotency_key = Some(key.to_owned());
    assert_eq!(serde_json::to_value(&actual_params)?, serde_json::to_value(expected_params)?);
    let terminal = fixture.native.runtime.observe_original(&original).await?.context("real original tool terminal")?;
    assert_eq!((terminal.job_id(), terminal.outcome(), terminal.exit_code()), (job_id, NativeJobOutcome::Succeeded, 0));
    assert_eq!(terminal.into_streams(), (b"BEGIN full-turn\nEND full-turn\n".to_vec(), b"stderr full-turn\n".to_vec()));
    assert_eq!(fixture.writer.status(key).await?, LocalOutcomeState::Committed);
    assert!(fixture.native.host.begin_native_effect(destination, key).await.is_err());
    let launch: Value = serde_json::from_slice(&tokio::fs::read(root.join("remote/jobs").join(job_id).join("launch.json")).await?)?;
    assert_eq!(launch["backend"], "detached");
    let attempts = tokio::fs::read_to_string(root.join("work/full-turn.attempts")).await?;
    assert_eq!(attempts.lines().count(), 1, "the full loop must execute one real child");
    let trace = tokio::fs::read_to_string(root.join("transport.jsonl")).await?;
    let events = trace.lines().map(serde_json::from_str::<Value>).collect::<serde_json::Result<Vec<_>>>()?;
    assert_eq!(events.iter().filter(|event| event["launch"] == true && event["job_id"] == job_id).count(), 1);

    fixture.assert_queue_persisted_once().await?;
    let admission = fixture.native.admission(fixture.anchor.checkpoint.clone(), fixture.scope.clone(), &result.run)?;
    let session = fixture.live.open_native_checkpoint(fixture.anchor.checkpoint.clone(), NativeCheckpointOpenMode::Recover, admission).await?;
    let NativeCheckpointLoad::Present(checkpoint) = fixture.live.load_native_checkpoint(&session).await? else {
        anyhow::bail!("full turn checkpoint missing");
    };
    let (anchor, stored) = crate::native_turn_checkpoint::decode(&checkpoint.state.payload, &fixture.anchor.checkpoint)?;
    assert_eq!(anchor.queue, fixture.anchor.queue);
    assert_eq!(stored.context, expected_context);
    assert_eq!((stored.final_answer.as_deref(), stored.provider_response_id.as_deref(), stored.model_calls, stored.tool_calls),
        (Some("full native tool turn complete"), Some("response-full-final"), 2, 1));
    assert!(stored.pending_model.is_none() && stored.pending_tool.is_none() && stored.queued_tools.is_empty());
    assert_eq!(stored.completed_call_ids, vec!["full-turn"]);
    let history = fixture.history().await?;
    let canonical: Vec<_> = history.items.iter().filter_map(|item| match item {
        RolloutItem::ResponseItem(envelope) => Some(&envelope.item), _ => None,
    }).collect();
    assert_eq!(canonical.len(), 3, "call, original output, and final assistant must each be present once");
    let mut item_ids = BTreeSet::new();
    for (actual, value) in canonical.iter().zip(&expected_context[fixture.initial.context.len()..]) {
        assert_eq!(actual.turn_id(), Some(fixture.anchor.checkpoint.turn_id.as_str()));
        assert!(item_ids.insert(actual.id().context("canonical native item id")?.to_string()));
        let mut expected: ResponseItem = serde_json::from_value(value.clone())?;
        expected.set_id(actual.id().cloned());
        expected.set_turn_id_if_missing(&fixture.anchor.checkpoint.turn_id);
        assert_eq!(*actual, &expected);
    }
    let duplicate = NativeTurnHandoff { live_thread: fixture.live.clone(), anchor: fixture.anchor.clone(),
        run: fixture.run.clone(), scope: fixture.scope.clone(), initial: fixture.initial.clone(), queue: None };
    assert!(fixture.native.run_turn(&native, duplicate, &CancellationToken::new()).await.is_err());
    assert!(fixture.handoff().await.is_err(), "completed original input must not be claimed again");
    fixture.assert_queue_persisted_once().await?;
    assert_eq!(posts.load(Ordering::SeqCst), 2);
    assert_eq!(server.received_requests().await.context("HTTP capture")?.len(), 2);
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 3);
    fixture.live.shutdown().await?;
    Ok(json!({"case":"full-turn","provider":"localhost HTTP/SSE fixture","model_posts":2,
        "tool_calls":1,"original_operations":operations,"writer_committed_effects":3,"final_use_grants":3,
        "original_queue_completed_once":true,"canonical_output_items":3,"checkpoint_pending_effects":0,
        "run":"succeeded","terminal_observed":true,"job_id":job_id,"real_child_attempts":1,"transport_launches":1}))
}
