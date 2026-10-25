//! Queue/view cancellation regressions. The controlled query futures contain
//! no production owner, authorization or simulated Hepta execution.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn notes_ui_failed_or_cancelled_refresh_cannot_renew_cached_ready() {
    let queue = NotesUiQueue::new();
    let command = ObjectiveCommand::Availability {};
    queue.request(command.clone());
    let mut view = queue.current(&command).unwrap();
    for cancel_navigation in [false, true] {
        refresh_availability(&mut view, async { Ok(ObjectiveRetainedIntents {
            client_intent_ids: vec!["original-navigation".into()], complete: true,
        }) }).await.unwrap();
        queue.update(view.clone()).unwrap();
        assert_eq!(queue.request(command.clone()).stage, ObjectiveStage::Ready);
        // The outer worker already stamped the attempted refresh as fresh.
        // Neither an owner refusal nor cancellation may keep the old Ready.
        view.observed_unix_ms = view.observed_unix_ms.saturating_add(1);
        if cancel_navigation {
            assert!(tokio::time::timeout(Duration::from_millis(1), refresh_availability(
                &mut view, std::future::pending(),
            )).await.is_err());
        } else {
            assert!(refresh_availability(&mut view, async {
                Err(invalid("explicit read-only readiness failure fixture"))
            }).await.is_err());
        }
        queue.update(view.clone()).unwrap();
        let cached = queue.request(command.clone());
        assert_eq!((cached.stage, cached.retained_intents), (ObjectiveStage::Unavailable, None));
    }
}

#[tokio::test]
async fn notes_ui_invalid_navigation_cannot_publish_partial_readiness() {
    let mut view = ObjectiveObservation::new(None, ObjectiveStage::Ready);
    view.retained_intents = Some(ObjectiveRetainedIntents {
        client_intent_ids: vec!["old".into()], complete: true,
    });
    assert!(refresh_availability(&mut view, async { Ok(ObjectiveRetainedIntents {
        client_intent_ids: vec!["one".into(), "one".into()], complete: true,
    }) }).await.is_err());
    assert_eq!((view.stage, view.retained_intents), (ObjectiveStage::Unavailable, None));
}
