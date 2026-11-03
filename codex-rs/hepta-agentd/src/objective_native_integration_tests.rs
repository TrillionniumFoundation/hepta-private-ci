//! Signed ObjectiveStart through the actual canonical owner, original Core
//! queue, builtin resolver and native writer. Only independent issuers/model
//! HTTP and the UDS transport are fixtures; no queue/terminal result is mocked.

use super::*;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_hepta_authbus::SignedMessageClaims;
use core_test_support::test_codex::TestCodex;
use core_test_support::wait_for_event_match;
use pretty_assertions::assert_eq;

use crate::{AuthBusObjectiveBody, AuthBusObjectiveIngress, NativeHostedRuntimeConfig, ObjectiveQueuedInputV1, ObjectiveRunAdmission};
use crate::intelligence_product::tests::objective_queued_fixtures::CanonicalObjectiveTestOwners;
use crate::objective_runtime::{ObjectiveRuntimeHost, ObjectiveStartResult};
use crate::authbus_ingress::now_ms;

#[path = "objective_native_queue_fixture.rs"]
mod queue_fixture;
use queue_fixture::{OriginalQueueTransport, ReplyFault, original_core};

#[path = "objective_native_owner_fixture.rs"]
mod owner_fixture;
use owner_fixture::ObjectiveFixture;

#[path = "objective_native_control_tests.rs"]
mod control_tests;

#[path = "objective_native_auth_gate_tests.rs"]
mod auth_gate_tests;

#[path = "objective_native_replay_tests.rs"]
mod replay_tests;

#[path = "objective_native_checkpoint_continuation_tests.rs"]
mod checkpoint_continuation_tests;

#[path = "objective_native_prepared_revision_tests.rs"]
mod prepared_revision_tests;

#[cfg(target_os = "linux")]
#[path = "objective_native_process_gate_tests.rs"]
mod process_gate_tests;

async fn completed_turn(test: &TestCodex) -> Result<String> {
    let terminal = wait_for_event_match(&test.codex, |event| match event {
        EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_) => Some(event.clone()),
        _ => None,
    }).await;
    let EventMsg::TurnComplete(completed) = terminal else {
        anyhow::bail!("original Core did not complete the native Objective turn: {terminal:?}");
    };
    ensure!(completed.error.is_none(), "native Objective failed: {:?}", completed.error);
    ensure!(completed.last_agent_message.as_deref() == Some("native owner complete"), "native answer was not delivered to original Core");
    Ok(completed.turn_id)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_objective_uses_original_queue_and_reconciles_a_lost_reply_once() -> Result<()> {
    for fault in [ReplyFault::None, ReplyFault::AfterQueue, ReplyFault::AfterCompletion] {
        let lose_reply = matches!(&fault, ReplyFault::AfterQueue);
        let server = provider().await;
        let fixture = ObjectiveFixture::new(&server, fault).await?;
        let first = fixture.submit(fixture.request.clone()).await;
        if lose_reply {
            assert!(first.is_err(), "lost original queue reply must remain unknown");
        } else {
            assert!(!first?.idempotent);
        }
        let turn_id = completed_turn(&fixture.core).await?;
        let record = fixture.host.original_record(&fixture.request.body.run_id)?;
        let input = fixture.base.state.canonical_queued_input(&record)?;
        assert_eq!(record.authenticated_payload.as_deref(), Some(serde_json::to_vec(&fixture.request.body)?.as_slice()));
        let original = NativeCheckpointBinding {
            thread_id: fixture.core.session_configured.thread_id, turn_id: turn_id.clone(),
            operation_id: record.snapshot.run_id.to_string(), generation: record.snapshot.generation,
            lease_id: fixture.base.writer.lease_id().to_owned(),
        };
        let session = fixture.core.thread_store.open_native_checkpoint(original.clone(),
            NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
        let NativeCheckpointLoad::Present(stored) = fixture.core.thread_store.load_native_checkpoint(&session).await? else {
            anyhow::bail!("native Objective omitted its original checkpoint");
        };
        let (anchor, turn) = crate::native_turn_checkpoint::decode(&stored.state.payload, &original)?;
        assert_eq!((anchor.queue.as_ref().context("original queue binding")?.client_id.as_str(),
            turn.final_answer.as_deref(), turn.model_calls, turn.pending_model.is_none(), turn.pending_tool.is_none()),
            (input.client_user_message_id.as_str(), Some("native owner complete"), 1, true, true));
        let replay = fixture.submit(fixture.request.clone()).await?;
        assert!(replay.idempotent);
        assert_eq!(replay.disposition, "canonical_queue_accepted");
        assert_eq!(fixture.host.original_record(&record.snapshot.run_id.to_string())?, record);
        assert_eq!(fixture.core.thread_store.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Present(stored));
        assert_eq!(*fixture.queue.modes.lock().expect("modes"), vec![ThreadQueueReconcileMode::AllowIfAbsent, ThreadQueueReconcileMode::ReconcileOnly]);
        assert!(!fixture.base.state.native_continuation_allowed(&input.run_id)?);
        assert!(fixture.base.state.load_canonical_prepared(&input.run_id).is_err(),
            "completed replay must not restore fresh canonical permission");
        assert_eq!(fixture.owners.calls.load(Ordering::SeqCst), 1, "replay must not repeat the seven-owner handoff");
        assert_eq!(fixture.base.state.native_run_receipt(&input.run_id)?.phase, RunPhase::Succeeded);
        assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
        let history = fixture.core.thread_store.load_latest_model_context(LoadThreadHistoryParams {
            thread_id: fixture.core.session_configured.thread_id, include_archived: false,
        }).await?;
        let inputs = history.items.iter().filter(|item| matches!(item,
            RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if matches!(&event.item,
                TurnItem::UserMessage(message) if message.client_id.as_deref() == Some(input.client_user_message_id.as_str())))).count();
        let outputs = history.items.iter().filter(|item| matches!(item,
            RolloutItem::ResponseItem(envelope) if matches!(&envelope.item,
                codex_protocol::models::ResponseItem::Message { role, .. } if role == "assistant"))).count();
        let typed_outputs = history.items.iter().filter(|item| matches!(item,
            RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if event.turn_id == anchor.checkpoint.turn_id
                && matches!(&event.item, TurnItem::AgentMessage(_)))).count();
        let requests = server.received_requests().await.context("model HTTP capture")?;
        assert_eq!((inputs, outputs, typed_outputs, requests.len(), fixture.base.issuer.grants.load(Ordering::SeqCst)), (1, 1, 1, 1, 1));
        let operation = requests[0].headers.get("idempotency-key").context("original operation header")?.to_str()?;
        assert_eq!(fixture.base.writer.status(operation).await?, LocalOutcomeState::Committed);
        fixture.shutdown().await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_objective_prepared_before_queue_recovers_original_input_once() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::BeforeQueue).await?;
    assert!(fixture.submit(fixture.request.clone()).await.is_err());
    let original = fixture.host.original_record(&fixture.request.body.run_id)?;
    let prepared = fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?.context("durable preparation before relay")?;
    assert_eq!(fixture.base.state.native_run_receipt(&fixture.request.body.run_id)?.phase, RunPhase::ContextAttached);
    assert_eq!(fixture.queue.reconciles.load(Ordering::SeqCst), 0);
    assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
    let replay = fixture.submit(fixture.request.clone()).await?;
    assert!(replay.idempotent);
    assert_eq!(replay.disposition, "canonical_queue_accepted");
    completed_turn(&fixture.core).await?;
    assert_eq!(fixture.host.original_record(&fixture.request.body.run_id)?, original);
    assert_eq!(fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?, Some(prepared));
    assert_eq!(*fixture.queue.modes.lock().expect("modes"), vec![ThreadQueueReconcileMode::AllowIfAbsent, ThreadQueueReconcileMode::AllowIfAbsent]);
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.base.issuer.grants.load(Ordering::SeqCst),
        fixture.queue.reconciles.load(Ordering::SeqCst)), (1, 1, 1));
    assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
    assert_eq!(server.received_requests().await.context("model HTTP capture")?.len(), 1);
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_objective_changed_input_and_unpermitted_thread_never_publish_or_dispatch() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::None).await?;
    let mut changed = fixture.request.clone();
    changed.body.queued_input.as_mut().context("signed text")?.text.push_str(" unsigned replacement");
    assert!(fixture.submit(changed).await.is_err());
    let mut forbidden = fixture.request.clone();
    forbidden.body.queued_input.as_mut().context("signed route")?.thread_id = ThreadId::new().to_string();
    fixture.sign(&mut forbidden)?;
    assert!(fixture.submit(forbidden).await.is_err());
    let mut oversized = fixture.request.clone();
    oversized.body.queued_input.as_mut().context("signed text")?.text = "a".repeat(8 * 1024 + 1);
    fixture.sign(&mut oversized)?;
    assert!(fixture.submit(oversized).await.is_err());
    assert!(fixture.host.original_record(&fixture.request.body.run_id).is_err());
    assert!(fixture.base.state.native_run_receipt(&fixture.request.body.run_id).is_err());
    assert!(fixture.queue.modes.lock().expect("modes").is_empty());
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.base.issuer.grants.load(Ordering::SeqCst)), (0, 0));
    assert!(server.received_requests().await.context("model HTTP capture")?.is_empty());
    fixture.shutdown().await
}
