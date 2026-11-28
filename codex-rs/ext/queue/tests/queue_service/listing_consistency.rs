use super::*;
use pretty_assertions::assert_eq;

#[derive(Default)]
pub(super) struct CompletionBarrier {
    pub(super) snapshot: Mutex<Option<Vec<codex_thread_store::QueuedUserSubmissionRecord>>>,
    pub(super) entered: tokio::sync::Notify,
    pub(super) release: tokio::sync::Notify,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_turn_listing_waits_for_durable_queue_completion() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    responses::mount_sse_once(&server, responses::sse_completed("completed-queue-turn")).await;
    let test = test_codex()
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let runtime = test.codex.state_db().context("state runtime unavailable")?;
    let barrier = Arc::new(CompletionBarrier::default());
    let mut store =
        FailDeleteOnceQueueStore::with_short_dispatch_lease(LocalQueueStore::new(runtime));
    store.short_dispatch_lease = false;
    store.completion_barrier = Some(Arc::clone(&barrier));
    let queue = Arc::new(QueuedItemService::new(
        Arc::new(store),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    ));
    let item = queue
        .enqueue(thread_id, user_input("complete before listing"))
        .await?;
    let dispatch_queue = Arc::clone(&queue);
    let thread = Arc::clone(&test.codex);
    let dispatch = tokio::spawn(async move {
        dispatch_queue
            .start(thread.as_ref(), Some(item.id), /*trace*/ None)
            .await
    });

    tokio::time::timeout(Duration::from_secs(/*secs*/ 25), async {
        barrier.entered.notified().await;
        wait_for_event_with_timeout(
            test.codex.as_ref(),
            |event| matches!(event, EventMsg::TurnComplete(_)),
            Duration::from_secs(/*secs*/ 25),
        )
        .await;

        let listing = queue.list(thread_id);
        tokio::pin!(listing);
        // Poll the public read while the real SQLite completion is held. An
        // unsynchronized read gets the still-durable row immediately; a read
        // serialized with dispatch waits until the same completion is released.
        let listed = tokio::select! {
            biased;
            listed = &mut listing => {
                barrier.release.notify_one();
                listed
            }
            () = std::future::ready(()) => {
                barrier.release.notify_one();
                listing.await
            }
        }?;
        assert!(matches!(
            dispatch.await??,
            StartIfIdleSubmission::Started { .. }
        ));
        assert_eq!(listed, Vec::new());
        anyhow::Ok(())
    })
    .await??;
    Ok(())
}
