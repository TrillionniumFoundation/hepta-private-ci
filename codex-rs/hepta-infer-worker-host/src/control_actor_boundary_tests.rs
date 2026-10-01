use super::*;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "boundary-owner".to_string(),
        worker_generation: 1,
        model: "boundary-model".to_string(),
        payload_digest: "1".repeat(64),
    }
}

fn pause(writer: &NativeJournalWriterHandle) -> std::sync::mpsc::SyncSender<()> {
    let (entered, entry) = std::sync::mpsc::sync_channel(1);
    let (release, blocked) = std::sync::mpsc::sync_channel(1);
    writer
        .send(Command::TestPause {
            entered,
            release: blocked,
        })
        .unwrap();
    entry.recv_timeout(Duration::from_secs(5)).unwrap();
    release
}

#[tokio::test]
async fn accepted_deadline_does_not_cancel_commit_or_license_duplicate_dispatch() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("control.journal");
    let limits = NativeWriterLimits {
        reply_timeout: Duration::from_millis(20),
        ..Default::default()
    };
    let actor = NativeJournalWriterActor::spawn_with_limits(journal.clone(), 8, limits).unwrap();
    let writer = actor.handle();
    let release = pause(&writer);
    assert_eq!(
        writer.reserve(request("deadline"), 1).await,
        Err(NativeControlActorError::AcceptedDeadlineExceeded)
    );
    // The only execution thread still owns its lock, including after timeout.
    assert!(DurableInferenceControl::open(&journal, 8).is_err());
    release.send(()).unwrap();
    // Allow a slower CI filesystem for observation, without resubmitting a mutation.
    let mut observer = writer.clone();
    observer.reply_timeout = Duration::from_secs(5);
    let first = observer
        .record("deadline".to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(first.state, NativeReservationState::Reserved);
    let same = observer.reserve(request("deadline"), 1).await.unwrap();
    assert_eq!(same, first);
    let mut drift = request("deadline");
    drift.payload_digest = "2".repeat(64);
    assert!(observer.reserve(drift, 1).await.is_err());
    assert_eq!(
        observer.record("deadline".to_string()).await.unwrap(),
        Some(first.clone())
    );
    assert_eq!(writer.queue_metrics().unwrap().successful_replies_lost, 1);
    actor.shutdown().await.unwrap();
    let reopened = DurableInferenceControl::open(&journal, 8).unwrap();
    assert_eq!(reopened.native_record("deadline"), Some(&first));
}

#[tokio::test]
async fn lost_terminal_reply_remains_durable_and_survives_restart() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("control.journal");
    let actor = NativeJournalWriterActor::spawn(journal.clone(), 8).unwrap();
    let writer = actor.handle();
    writer.reserve(request("lost-terminal"), 1).await.unwrap();
    let (reply, response) = oneshot::channel();
    drop(response); // Receiver gone before submission: deterministic reply loss.
    writer
        .send(Command::StopBeforeDispatch {
            request_id: "lost-terminal".to_string(),
            reason: "cancelled before dispatch".to_string(),
            reply,
        })
        .unwrap();
    let record = writer
        .record("lost-terminal".to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(record.state, NativeReservationState::Released);
    assert_eq!(writer.queue_metrics().unwrap().successful_replies_lost, 1);
    actor.shutdown().await.unwrap();
    let reopened = DurableInferenceControl::open(&journal, 8).unwrap();
    assert_eq!(reopened.native_record("lost-terminal"), Some(&record));
}

#[tokio::test]
async fn published_metrics_are_immutable_stale_and_do_not_queue_reads() {
    let paths = tempfile::tempdir().unwrap();
    let actor = NativeJournalWriterActor::spawn(paths.path().join("control.journal"), 8).unwrap();
    let writer = actor.handle();
    assert!(writer.published_metrics().is_none());
    let before = writer.metrics(1000).await.unwrap();
    let snapshot = writer.published_metrics().unwrap();
    writer.reserve(request("snapshot"), 1).await.unwrap();
    let release = pause(&writer);
    for _ in 0..1000 {
        let last = writer.published_metrics().unwrap();
        assert!(Arc::ptr_eq(&snapshot, &last));
        assert_eq!(last.metrics, before);
    }
    assert_eq!(writer.queue_metrics().unwrap().depth, 0);
    release.send(()).unwrap();
    let after = writer.metrics(1001).await.unwrap();
    assert_eq!(after.reserved, 1);
    assert_eq!(snapshot.metrics.reserved, 0);
    assert_eq!(snapshot.evaluated_at_unix_ms, 1000);
    assert_eq!(
        writer.published_metrics().unwrap().evaluated_at_unix_ms,
        1001
    );
    assert_eq!(writer.published_metrics().unwrap().metrics, after);
    actor.shutdown().await.unwrap();
}

#[tokio::test]
async fn full_ordinary_queue_cannot_reject_terminal_transition_or_shutdown() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("control.journal");
    let limits = NativeWriterLimits {
        ordinary_queue_capacity: 1,
        terminal_queue_capacity: 1,
        ..Default::default()
    };
    let actor = NativeJournalWriterActor::spawn_with_limits(journal.clone(), 8, limits).unwrap();
    let writer = actor.handle();
    writer.reserve(request("full"), 1).await.unwrap();
    let release = pause(&writer);
    let (read_reply, read_response) = oneshot::channel();
    writer
        .send(Command::Record {
            request_id: "full".to_string(),
            reply: read_reply,
        })
        .unwrap();
    let (extra_reply, _) = oneshot::channel();
    assert_eq!(
        writer.send(Command::Record {
            request_id: "full".to_string(),
            reply: extra_reply
        }),
        Err(NativeControlActorError::Overloaded)
    );
    let (reply, response) = oneshot::channel();
    writer
        .send(Command::StopBeforeDispatch {
            request_id: "full".to_string(),
            reason: "before effect".to_string(),
            reply,
        })
        .unwrap();
    // Drop seals the real full actor and queues its reserved shutdown barrier.
    // Explicit shutdown is separately verified by the normal actor tests.
    let shutdown = tokio::spawn(actor.shutdown());
    tokio::time::timeout(Duration::from_secs(5), async {
        while writer.queue_metrics().unwrap().accepting {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    release.send(()).unwrap();
    assert_eq!(
        read_response.await.unwrap().unwrap().state,
        NativeReservationState::Reserved
    );
    assert_eq!(
        response.await.unwrap().unwrap().state,
        NativeReservationState::Released
    );
    shutdown.await.unwrap().unwrap();
    let reopened = DurableInferenceControl::open(&journal, 8).unwrap();
    assert_eq!(
        reopened.native_record("full").unwrap().state,
        NativeReservationState::Released
    );
}

#[tokio::test]
async fn dropped_accepted_sender_is_not_pre_admission_closed() {
    let (reply, response) = oneshot::channel::<()>();
    drop(reply);
    assert_eq!(
        receive_value(response, Duration::from_secs(1)).await,
        Err(NativeControlActorError::AcceptedReplyLost)
    );
}

use crate::signed_fixture as signed;

#[tokio::test]
async fn signed_post_effect_terminal_reply_loss_keeps_exact_durable_result() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("signed.journal");
    let now = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis(),
    )
    .unwrap();
    let plan = Arc::new(signed::plan("signed-loss", now));
    let actor = NativeJournalWriterActor::spawn(journal.clone(), 8).unwrap();
    let writer = actor.handle();
    writer
        .reserve(signed::request("signed-loss"), 1)
        .await
        .unwrap();
    writer
        .bind_execution("signed-loss".to_string(), Arc::clone(&plan), now)
        .await
        .unwrap();
    let prepared = writer
        .prepare_authorized_dispatch(
            "signed-loss".to_string(),
            signed::dispatch("thread-1"),
            Arc::clone(&plan),
            now,
        )
        .await
        .unwrap();
    let dispatched = prepared.cross_effect_boundary();
    dispatched.started("turn-1".to_string()).await.unwrap();
    let output = signed::terminal_output("thread-1", "turn-1", "private output");
    let expected_protection =
        ProtectedOutput::digest_only(now, plan.output_policy(), output.output.as_bytes()).unwrap();
    let mut expected_observation = output.clone();
    expected_observation.output = expected_protection.journal_marker().unwrap();
    let (reply, response) = oneshot::channel();
    drop(response);
    writer
        .send(Command::SettleAuthorized {
            request_id: "signed-loss".to_string(),
            plan: Arc::clone(&plan),
            now_unix_ms: now,
            output,
            protected_output: None,
            reply,
        })
        .unwrap();
    let settled = writer
        .record("signed-loss".to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    // Losing delivery retains the exact terminal facts and their protected
    // marker, while the durable journal never retains the live plaintext.
    assert_eq!(settled.observation.as_ref(), Some(&expected_observation));
    assert_eq!(
        settled.protected_output.as_ref(),
        Some(&expected_protection)
    );
    assert!(
        !std::fs::read_to_string(&journal)
            .unwrap()
            .contains("private output")
    );
    assert_eq!(
        writer
            .reserve(signed::request("signed-loss"), 1)
            .await
            .unwrap(),
        settled
    );
    assert!(
        writer
            .prepare_authorized_dispatch(
                "signed-loss".to_string(),
                signed::dispatch("thread-2"),
                Arc::clone(&plan),
                now
            )
            .await
            .is_err()
    );
    assert_eq!(writer.queue_metrics().unwrap().successful_replies_lost, 1);
    actor.shutdown().await.unwrap();
    let reopened = DurableInferenceControl::open(&journal, 8).unwrap();
    assert_eq!(reopened.native_record("signed-loss"), Some(&settled));
}

#[tokio::test]
async fn caller_cancellation_after_admission_cannot_erase_the_owner_command() {
    let paths = tempfile::tempdir().unwrap();
    let actor = NativeJournalWriterActor::spawn(paths.path().join("cancel.journal"), 8).unwrap();
    let writer = actor.handle();
    let release = pause(&writer);
    let submitting = writer.clone();
    let caller = tokio::spawn(async move { submitting.reserve(request("cancelled"), 1).await });
    tokio::time::timeout(Duration::from_secs(5), async {
        while writer.queue_metrics().unwrap().ordinary_depth != 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    caller.abort();
    assert!(caller.await.unwrap_err().is_cancelled());
    release.send(()).unwrap();
    assert_eq!(
        writer
            .record("cancelled".to_string())
            .await
            .unwrap()
            .unwrap()
            .state,
        NativeReservationState::Reserved
    );
    assert_eq!(writer.queue_metrics().unwrap().successful_replies_lost, 1);
    actor.shutdown().await.unwrap();
}

#[tokio::test]
async fn shutdown_deadline_retains_lock_until_the_real_owner_exits() {
    let paths = tempfile::tempdir().unwrap();
    let journal = paths.path().join("shutdown.journal");
    let limits = NativeWriterLimits {
        shutdown_timeout: Duration::from_millis(20),
        ..Default::default()
    };
    let actor = NativeJournalWriterActor::spawn_with_limits(journal.clone(), 8, limits).unwrap();
    let writer = actor.handle();
    let release = pause(&writer);
    assert_eq!(
        actor.shutdown().await,
        Err(NativeControlActorError::ShutdownDeadlineExceeded)
    );
    assert!(!writer.queue_metrics().unwrap().accepting);
    assert!(DurableInferenceControl::open(&journal, 8).is_err());
    release.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if let Ok(reopened) = DurableInferenceControl::open(&journal, 8) {
                drop(reopened);
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
#[ignore = "real-journal pilot; not selected target-host/provider qualification"]
async fn real_writer_mixed_query_terminal_contention_curve() {
    for ordinary_capacity in [8, 64, 256] {
        let paths = tempfile::tempdir().unwrap();
        let limits = NativeWriterLimits {
            ordinary_queue_capacity: ordinary_capacity,
            terminal_queue_capacity: 32,
            ..Default::default()
        };
        let actor = NativeJournalWriterActor::spawn_with_limits(
            paths.path().join("mixed.journal"),
            512,
            limits,
        )
        .unwrap();
        let writer = actor.handle();
        for batch in 0..4 {
            for id in 0..32 {
                writer
                    .reserve(request(&format!("mixed-{batch}-{id}")), 32)
                    .await
                    .unwrap();
            }
            let release = pause(&writer);
            for _ in 0..ordinary_capacity {
                let (reply, _) = oneshot::channel();
                writer
                    .send(Command::Record {
                        request_id: format!("mixed-{batch}-0"),
                        reply,
                    })
                    .unwrap();
            }
            let mut responses = Vec::new();
            for id in 0..32 {
                let (reply, response) = oneshot::channel();
                writer
                    .send(Command::StopBeforeDispatch {
                        request_id: format!("mixed-{batch}-{id}"),
                        reason: "pilot terminal before effect".to_string(),
                        reply,
                    })
                    .unwrap();
                responses.push(response);
            }
            release.send(()).unwrap();
            for response in responses {
                assert_eq!(
                    response.await.unwrap().unwrap().state,
                    NativeReservationState::Released
                );
            }
        }
        // An owner barrier follows all terminal operations and their timings.
        let metrics = writer.metrics(1_000).await.unwrap();
        assert_eq!(metrics.released, 128);
        let queues = writer.queue_metrics().unwrap();
        assert_eq!(queues.terminal_apply.observed, 128);
        println!(
            "{}",
            serde_json::json!({"scope": "real_journal_mixed_query_pre_effect_terminal_pilot",
            "metrics": queues, "target_host_qualified": false})
        );
        actor.shutdown().await.unwrap();
    }
}
