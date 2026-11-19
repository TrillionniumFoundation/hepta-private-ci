//! Queue/view cancellation regressions. The controlled query futures contain
//! no production owner, authorization or simulated Hepta execution.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn notes_ui_readback_failure_and_cancellation_cannot_renew_an_old_snapshot() {
    let state = codex_hepta_memory::NotesDocumentState {
        target: codex_hepta_memory::NotesTargetIdentity {
            session_instance: "0f".repeat(16),
            task_id: 3,
            incarnation: "ab".repeat(16),
        },
        revision: 5,
        text_sha256: codex_hepta_contracts::Sha256Digest::for_bytes("saved".as_bytes()),
        receipt_pending: true,
    };
    let mut view = ObjectiveObservation::new(
        Some("unknown-operation".into()),
        ObjectiveStage::SubmitUnknown,
    );
    for cancelled in [false, true] {
        publish_document_readback(&mut view, async { Ok(state.clone()) })
            .await
            .unwrap();
        assert_eq!(view.notes_document.as_ref().unwrap().revision, 5);
        assert_eq!(view.stage, ObjectiveStage::SubmitUnknown);
        assert_eq!(view.run, None);
        if cancelled {
            assert!(
                tokio::time::timeout(
                    Duration::from_millis(1),
                    publish_document_readback(&mut view, std::future::pending(),)
                )
                .await
                .is_err()
            );
        } else {
            assert!(
                publish_document_readback(&mut view, async {
                    Err(invalid("readback unavailable"))
                })
                .await
                .is_err()
            );
        }
        assert_eq!(view.notes_document, None);
        assert_eq!(view.stage, ObjectiveStage::SubmitUnknown);
        assert_eq!(view.run, None);
    }
}

#[tokio::test]
async fn notes_ui_failed_or_cancelled_refresh_cannot_renew_cached_ready() {
    let queue = NotesUiQueue::new();
    let command = ObjectiveCommand::Availability {};
    queue.request(command.clone());
    let mut view = queue.current(&command).unwrap();
    for cancel_navigation in [false, true] {
        refresh_availability(&mut view, async {
            Ok(ObjectiveRetainedIntents {
                client_intent_ids: vec!["original-navigation".into()],
                complete: true,
            })
        })
        .await
        .unwrap();
        queue.update(view.clone()).unwrap();
        assert_eq!(queue.request(command.clone()).stage, ObjectiveStage::Ready);
        // The outer worker already stamped the attempted refresh as fresh.
        // Neither an owner refusal nor cancellation may keep the old Ready.
        view.observed_unix_ms = view.observed_unix_ms.saturating_add(1);
        if cancel_navigation {
            assert!(
                tokio::time::timeout(
                    Duration::from_millis(1),
                    refresh_availability(&mut view, std::future::pending(),)
                )
                .await
                .is_err()
            );
        } else {
            assert!(
                refresh_availability(&mut view, async {
                    Err(invalid("explicit read-only readiness failure fixture"))
                })
                .await
                .is_err()
            );
        }
        queue.update(view.clone()).unwrap();
        let cached = queue.request(command.clone());
        assert_eq!(
            (cached.stage, cached.retained_intents),
            (ObjectiveStage::Unavailable, None)
        );
    }
}

#[tokio::test]
async fn notes_ui_invalid_navigation_cannot_publish_partial_readiness() {
    let mut view = ObjectiveObservation::new(None, ObjectiveStage::Ready);
    view.retained_intents = Some(ObjectiveRetainedIntents {
        client_intent_ids: vec!["old".into()],
        complete: true,
    });
    assert!(
        refresh_availability(&mut view, async {
            Ok(ObjectiveRetainedIntents {
                client_intent_ids: vec!["one".into(), "one".into()],
                complete: true,
            })
        })
        .await
        .is_err()
    );
    assert_eq!(
        (view.stage, view.retained_intents),
        (ObjectiveStage::Unavailable, None)
    );
}
