//! Request projection is exercised through real owner checkpoints and jobs.
//! The unchanged production fold source is included to test its private API
//! without widening production visibility or reproducing its verification logic.

use super::*;
use pretty_assertions::assert_eq;

#[path = "native_checkpoint_fold.rs"]
mod original_fold;

pub(super) async fn exercise(root: &Path) -> Result<Value> {
    let server = MockServer::start().await;
    let messages = [
        "第一轮完整历史证据。".repeat(200),
        "第二轮完整工具交换。".repeat(200),
    ];
    let mut replies = Vec::new();
    for (index, call_id) in ["context-first", "context-second"].into_iter().enumerate() {
        let items = vec![
            json!({"type":"message","role":"assistant","phase":"commentary",
                "content":[{"type":"output_text","text":messages[index]}]}),
            json!({"type":"function_call","call_id":call_id,"name":"owned_process","arguments":"{}"}),
        ];
        replies.push((format!("response-{call_id}"), items));
        tokio::fs::write(
            root.join("work").join(format!("{call_id}.release")),
            b"allow the original owned child to finish",
        )
        .await?;
    }
    let final_text = "完整历史与原始操作验证通过。";
    replies.push((
        "response-context-final".to_owned(),
        vec![json!({"type":"message","role":"assistant",
        "phase":"final_answer","content":[{"type":"output_text","text":final_text}]})],
    ));
    let wire: Vec<_> = replies
        .iter()
        .map(|(id, items)| {
            let mut events = vec![json!({"type":"response.created","response":{"id":id}})];
            events.extend(items.iter().enumerate().map(|(index, item)|
            json!({"type":"response.output_item.done","output_index":index,"item":item})));
            events.push(
                json!({"type":"response.completed","response":{"id":id,"status":"completed",
            "output":items,"usage":{"input_tokens":20,"output_tokens":30}}}),
            );
            events
                .into_iter()
                .map(|event| format!("data: {event}\n\n"))
                .collect::<String>()
        })
        .collect();
    assert!(wire.iter().all(|body| body.len() <= 16384));
    let posts = Arc::new(AtomicUsize::new(0));
    let posted = posts.clone();
    Mock::given(method("POST"))
        .and(path("/v1/responses"))
        .respond_with(move |_request: &wiremock::Request| {
            let index = posted.fetch_add(1, Ordering::SeqCst);
            match wire.get(index) {
                Some(body) => {
                    ResponseTemplate::new(200).set_body_raw(body.clone(), "text/event-stream")
                }
                None => {
                    ResponseTemplate::new(500).set_body_string("no replacement operation permitted")
                }
            }
        })
        .expect(3)
        .mount(&server)
        .await;
    let mut fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    fixture.native.compiler = Arc::new(OwnedCompiler {
        work: root.join("work"),
    });
    let mut native = agent();
    native.tools = vec![
        json!({"type":"function","name":"owned_process","description":"Run the owned fixture process",
        "parameters":{"type":"object","properties":{},"additionalProperties":false}}),
    ];
    native.limits.model_calls = 3;
    native.limits.tool_calls = 2;
    native.limits.tool_timeout = Duration::from_secs(15);
    let result = tokio::time::timeout(
        Duration::from_secs(35),
        fixture
            .native
            .run_turn(&native, fixture.handoff().await?, &CancellationToken::new()),
    )
    .await
    .context("long-context owner turn deadline")??;
    assert_eq!(result.outcome, RunOutcome::Completed(final_text.to_owned()));
    assert_eq!((result.state.model_calls, result.state.tool_calls), (3, 2));
    let retained_bytes = serde_json::to_vec(&result.state.context)?.len();
    assert!(retained_bytes > native.limits.context_bytes);
    assert_eq!(
        result.state.context[fixture.initial.context.len()]["content"][0]["text"],
        messages[0]
    );
    assert_eq!(
        result.state.context[fixture.initial.context.len() + 3]["content"][0]["text"],
        messages[1]
    );
    assert!(result.state.context.starts_with(&fixture.initial.context));
    let captured = server
        .received_requests()
        .await
        .context("original HTTP requests")?;
    assert_eq!(captured.len(), 3);
    let mut operations = BTreeSet::new();
    for request in &captured {
        assert!(request.body.len() <= native.limits.context_bytes);
        let key = request
            .headers
            .get("idempotency-key")
            .context("original model identity")?
            .to_str()?;
        assert!(operations.insert(key.to_owned()));
        let original = fixture
            .writer
            .resolve_operation_request(key, fixture.native.model.destination_id())
            .await?;
        assert_eq!(original.payload_json.as_bytes(), request.body.as_slice());
        assert_eq!(
            fixture.writer.status(key).await?,
            LocalOutcomeState::Committed
        );
    }
    let projected: Value = serde_json::from_slice(&captured[2].body)?;
    let original_len = fixture.initial.context.len();
    assert_eq!(
        projected["input"]
            .as_array()
            .context("projected input")?
            .len(),
        original_len + 6
    );
    let excerpt = projected["input"][original_len]["content"][0]["text"]
        .as_str()
        .context("old text excerpt")?;
    assert!(excerpt.contains("Historical request excerpt") && excerpt.contains("item_sha256="));
    assert!(excerpt.len() < messages[0].len());
    assert_eq!(
        projected["input"][original_len + 3]["content"][0]["text"],
        messages[1]
    );
    for index in [
        original_len + 1,
        original_len + 2,
        original_len + 4,
        original_len + 5,
    ] {
        assert_eq!(
            projected["input"][index], result.state.context[index],
            "original call/output pairing changed"
        );
    }

    let (chain, anchor) = fixture
        .native
        .read_hosted_checkpoint_chain(&fixture.live, &fixture.anchor.checkpoint)
        .await?;
    let latest = chain.last().context("durable checkpoint head")?;
    let (decoded_anchor, decoded) =
        crate::native_turn_checkpoint::decode(&latest.state.payload, &anchor.checkpoint)?;
    assert_eq!(decoded_anchor, anchor);
    assert_eq!(decoded.context, result.state.context);
    assert_eq!(
        crate::native_turn_checkpoint::encode(&anchor, &decoded)?,
        latest.state.payload
    );
    assert!(latest.state.payload.len() < 4 * 1024 * 1024);
    let admission = fixture.native.admission(
        anchor.checkpoint.clone(),
        fixture.scope.clone(),
        &result.run,
    )?;
    let fold = original_fold::NativeCheckpointFold {
        agent: &native,
        anchor: &anchor,
        admission: &admission,
        model: &fixture.native.model,
        runtime: &fixture.native.runtime,
    };
    let states = fold.decode_chain(&chain, &fixture.initial)?;
    assert!(
        states.iter().any(
            |state| state
                .pending_model
                .as_ref()
                .is_some_and(|pending| pending.body.len() <= native.limits.context_bytes
                    && serde_json::to_vec(&state.context)
                        .is_ok_and(|bytes| bytes.len() > native.limits.context_bytes))
        )
    );
    let raw_tools = fold.observe_tools(&states).await?;
    assert_eq!(raw_tools.len(), 2);
    let policy = Generation::new(
        anchor
            .execution
            .as_ref()
            .context("original execution binding")?
            .policy_generation,
    )?;
    let digest = crate::native_admission::execution_scope_digest(
        &anchor.checkpoint,
        &result.run,
        fixture.writer.owner_agent_id(),
        &fixture.scope,
        policy,
    )?;
    let digest = Sha256Digest::parse(digest.to_string()).map_err(anyhow::Error::msg)?;
    let frontier = fixture.writer.observe_scope_frontier(&digest).await?;
    fold.verify(&chain, &states, &frontier, &raw_tools)?;
    assert_eq!(frontier.records().len(), 5);
    for operation in frontier.records() {
        operations.insert(operation.request().occurrence_key.clone());
    }
    assert_eq!(operations.len(), 5);
    drop(frontier); // Release the exclusive owner fence before further awaits.

    let mut jobs = tokio::fs::read_dir(root.join("state/jobs")).await?;
    let mut job_ids = BTreeSet::new();
    while let Some(entry) = jobs.next_entry().await? {
        if entry.path().extension().and_then(|ext| ext.to_str()) != Some("json") {
            continue;
        }
        let record: Value = serde_json::from_slice(&tokio::fs::read(entry.path()).await?)?;
        let call_id = record["args"]
            .as_array()
            .and_then(|args| args.last())
            .and_then(Value::as_str);
        if !matches!(call_id, Some("context-first" | "context-second")) {
            continue;
        }
        let key = record["idempotency_key"]
            .as_str()
            .context("original runtime operation")?;
        assert!(operations.contains(key));
        assert!(
            job_ids.insert(
                record["id"]
                    .as_str()
                    .context("original runtime job")?
                    .to_owned()
            )
        );
        let attempts = tokio::fs::read_to_string(
            root.join("work")
                .join(format!("{}.attempts", call_id.context("owned child")?)),
        )
        .await?;
        assert_eq!(
            attempts.lines().count(),
            1,
            "full-fold observation must not rerun a child"
        );
    }
    assert_eq!(job_ids.len(), 2);
    let trace = tokio::fs::read_to_string(root.join("transport.jsonl")).await?;
    let trace: Vec<Value> = trace
        .lines()
        .map(serde_json::from_str)
        .collect::<serde_json::Result<_>>()?;
    for job in &job_ids {
        assert_eq!(
            trace
                .iter()
                .filter(|event| event["launch"] == true && event["job_id"] == *job)
                .count(),
            1
        );
    }
    fixture.assert_queue_persisted_once().await?;
    assert_eq!(posts.load(Ordering::SeqCst), 3);
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 5);
    fixture.live.shutdown().await?;
    Ok(
        json!({"case":"long-context-full-owner-fold","retained_context_bytes":retained_bytes,
        "request_cap_bytes":native.limits.context_bytes,"largest_request_bytes":captured.iter().map(|request| request.body.len()).max(),
        "checkpoint_revisions":chain.len(),"checkpoint_bytes":latest.state.payload.len(),
        "full_original_chain_verified":true,"original_operations":operations,"model_posts":3,
        "tool_calls":2,"final_use_grants":5,"job_ids":job_ids,"real_child_attempts":2,"transport_launches":2,
        "original_queue_completed_once":true,"history_was_not_truncated":true}),
    )
}
