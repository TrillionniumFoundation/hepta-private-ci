use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_messages_continue_after_each_completion_owner_retires() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let responses = responses::mount_sse_sequence(
        &server,
        (0..6)
            .map(|index| responses::sse_completed(&format!("queue-generation-{index}")))
            .collect(),
    )
    .await;
    let (installed, extensions) = registered_queue_extensions();
    let test = test_codex()
        .with_extensions(extensions)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let staging = QueuedItemService::new(
        loaded_thread_queue(&test)?,
        Weak::new(),
        Arc::new(NoopExtensionEventSink),
    );
    for index in 1..6 {
        staging
            .enqueue(thread_id, user_input(&format!("queued {index}")))
            .await?;
    }
    let queue = install_registered_queue(&test, installed.as_ref())?;
    test.codex
        .start_or_steer_turn(TurnInputRequest::new(user_input("queued 0")))
        .await?;
    let completed_ids = tokio::time::timeout(Duration::from_secs(20), async {
        let mut ids = Vec::new();
        while ids.len() < 6 {
            let (event, completion) = test.codex.next_event_with_completion().await?;
            if let EventMsg::TurnComplete(complete) = event.msg {
                completion.await;
                ids.push(complete.turn_id);
            }
        }
        anyhow::Ok(ids)
    })
    .await??;
    assert_eq!(completed_ids.iter().collect::<HashSet<_>>().len(), 6);
    let prompts = responses
        .requests()
        .into_iter()
        .map(|request| request.message_input_texts("user").pop().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(
        prompts,
        (0..6).map(|index| format!("queued {index}")).collect::<Vec<_>>()
    );
    assert!(queue.list(thread_id).await?.is_empty());
    Ok(())
}
