use super::tests::mark_ready;
use super::tests::recovery_fixture;
use super::tests::recovery_markers;
use super::*;
use codex_protocol::models::ContentItem;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnRecoveryCandidateState;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::Ordering;

fn injected_item(label: &str) -> ResponseItem {
    ResponseItem::Message {
        id: None,
        role: "developer".to_string(),
        content: vec![ContentItem::InputText {
            text: label.to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    }
}

#[tokio::test]
async fn completion_fragment_preserves_active_recovery_admission() {
    for (enabled, poisoned) in [(true, false), (true, true), (false, false)] {
        let turn_id = format!("completion-fragment-{enabled}-{poisoned}");
        let (session, _context, authority, store) = recovery_fixture(enabled, &turn_id).await;
        if enabled {
            mark_ready(&session, &turn_id, &authority).await;
        }
        authority.state.lock().await.poisoned = poisoned;
        let appends_before = store.calls().await.append_items;
        let item = injected_item("exact completion fragment");
        let result = session
            .inject_fragment_after_finish(vec![item.clone()], std::future::pending())
            .await;
        let pending = session
            .input_queue
            .get_pending_input(&session.active_turn)
            .await
            .0;
        if poisoned {
            assert!(
                result
                    .expect_err("poisoned recovery must reject the fragment")
                    .to_string()
                    .contains("recovery provenance is poisoned")
            );
            assert!(pending.is_empty());
            assert_eq!(
                recovery_markers(&session, &turn_id).await,
                vec![TurnRecoveryCandidateState::Ready]
            );
        } else {
            result.expect("accepted fragment");
            assert_eq!(
                pending,
                vec![PendingTurnInput::ResponseItem(ResponseItemEnvelope::new(
                    item
                ))]
            );
            if enabled {
                assert_eq!(
                    recovery_markers(&session, &turn_id).await,
                    vec![
                        TurnRecoveryCandidateState::Ready,
                        TurnRecoveryCandidateState::Unready
                    ]
                );
                assert!(!authority.ready.load(Ordering::Acquire));
            } else {
                assert_eq!(store.calls().await.append_items, appends_before);
                assert!(recovery_markers(&session, &turn_id).await.is_empty());
            }
        }
        authority.state.lock().await.poisoned = false;
        session.abort_all_tasks(TurnAbortReason::Replaced).await;
    }
}

#[tokio::test]
async fn completion_fragment_enters_a_live_successor_before_prior_finish_retires() {
    for enabled in [false, true] {
        let turn_id = format!("completion-live-successor-{enabled}");
        let (session, _context, authority, _store) = recovery_fixture(enabled, &turn_id).await;
        if enabled {
            mark_ready(&session, &turn_id, &authority).await;
        }
        let completion = crate::state::StartTransitionCompletion::new();
        session
            .pending_task_terminalization_completions
            .lock()
            .expect("terminalization registry")
            .push((
                Arc::new(()),
                Arc::clone(&completion),
                crate::state::TaskTerminalizationKind::Finish,
                None,
                None,
                None,
            ));
        let item = injected_item("completion for the active successor");
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(2),
            session.inject_fragment_after_finish(vec![item.clone()], std::future::pending()),
        )
        .await;
        let still_owned = !completion.is_complete();
        let pending = session
            .input_queue
            .get_pending_input(&session.active_turn)
            .await
            .0;
        let markers = recovery_markers(&session, &turn_id).await;
        session
            .pending_task_terminalization_completions
            .lock()
            .expect("terminalization registry")
            .retain(|(_, current, _, _, _, _)| !Arc::ptr_eq(current, &completion));
        completion.complete();
        session.abort_all_tasks(TurnAbortReason::Replaced).await;

        result
            .expect("a live successor must not wait for the old owner")
            .expect("the original live injection admission still applies");
        assert!(
            still_owned,
            "recording must not retire another task's owner"
        );
        assert_eq!(
            pending,
            vec![PendingTurnInput::ResponseItem(ResponseItemEnvelope::new(
                item
            ))]
        );
        assert_eq!(
            markers,
            if enabled {
                vec![
                    TurnRecoveryCandidateState::Ready,
                    TurnRecoveryCandidateState::Unready,
                ]
            } else {
                Vec::new()
            }
        );
    }
}
