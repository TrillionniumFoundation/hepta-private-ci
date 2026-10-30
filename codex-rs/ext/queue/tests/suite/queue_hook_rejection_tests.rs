use super::*;

#[derive(Clone, Copy)]
enum Binding {
    Exact,
    Unbound,
}

async fn rejected_head_allows_explicit_retry_and_changed_work(
    binding: Binding,
) -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response = responses::mount_sse_once(&server, responses::sse_completed("allowed")).await;
    let (installed, extensions) = registered_queue_extensions();
    let test = test_codex()
        .with_extensions(extensions)
        .with_pre_build_hook(write_rejecting_prompt_hook)
        .with_config(trust_discovered_hooks)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let staging = QueuedItemService::new(
        loaded_thread_queue(&test)?,
        Weak::new(),
        Arc::new(NoopExtensionEventSink),
    );
    let rejected = match binding {
        Binding::Unbound => staging.enqueue(thread_id, user_input("blocked")).await?,
        Binding::Exact => {
            let input = structured_user_input("blocked");
            let TurnInput::UserInput { content, .. } = &input else {
                unreachable!("test input is a user message");
            };
            let digest = user_input_payload_sha256(content)?;
            let reconciled = staging
                .reconcile(
                    thread_id,
                    test.codex.rollout_path(),
                    input,
                    digest,
                    QueueReconcileMode::AllowIfAbsent,
                )
                .await?;
            let QueueReconcileOutcome::Queued { item, .. } = reconciled.outcome else {
                anyhow::bail!("expected a durable exact queued item");
            };
            item
        }
    };
    let queue = install_registered_queue(&test, installed.as_ref())?;
    for _ in 0..2 {
        let rejection = tokio::time::timeout(
            Duration::from_secs(10),
            queue.start(
                test.codex.as_ref(),
                Some(rejected.id.clone()),
                /*trace*/ None,
            ),
        )
        .await?;
        let Err(error) = rejection else {
            anyhow::bail!("an explicit retry must reach the hook and remain rejected");
        };
        let QueueServiceError::CoreSubmissionError(error) = error else {
            anyhow::bail!("unexpected definitive rejection result: {error:?}");
        };
        assert!(
            matches!(error.details(), CodexErrorDetails::InvalidRequest(message)
            if message == "user message was rejected by a hook")
        );
        loop {
            let (event, completion) = test.codex.next_event_with_completion().await?;
            if matches!(event.msg, EventMsg::TurnComplete(_)) {
                completion.await;
                break;
            }
        }
        std::assert_eq!(queue.list(thread_id).await?, vec![rejected.clone()]);
    }
    let log = fs::read_to_string(test.codex_home_path().join("queue_prompt_hook.log"))?;
    std::assert_eq!(log.lines().collect::<Vec<_>>(), vec!["blocked", "blocked"]);
    match binding {
        Binding::Unbound => {
            queue
                .update(thread_id, rejected.id, user_input("allowed"))
                .await?;
        }
        Binding::Exact => {
            queue.enqueue(thread_id, user_input("allowed")).await?;
            assert!(queue.delete(thread_id, rejected.id).await?);
        }
    }
    emit_idle(queue.as_ref(), thread_id).await;
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            let (event, completion) = test.codex.next_event_with_completion().await?;
            if matches!(event.msg, EventMsg::TurnComplete(_)) {
                completion.await;
                break;
            }
        }
        anyhow::Ok(())
    })
    .await??;
    assert!(queue.list(thread_id).await?.is_empty());
    std::assert_eq!(
        response
            .single_request()
            .message_input_texts("user")
            .last()
            .map(String::as_str),
        Some("allowed")
    );
    let log = fs::read_to_string(test.codex_home_path().join("queue_prompt_hook.log"))?;
    std::assert_eq!(
        log.lines().collect::<Vec<_>>(),
        vec!["blocked", "blocked", "allowed"]
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exact_hook_rejection_releases_only_its_lease_and_allows_explicit_retry()
-> anyhow::Result<()> {
    rejected_head_allows_explicit_retry_and_changed_work(Binding::Exact).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unbound_hook_rejection_suppresses_auto_retry_until_payload_changes() -> anyhow::Result<()>
{
    rejected_head_allows_explicit_retry_and_changed_work(Binding::Unbound).await
}
