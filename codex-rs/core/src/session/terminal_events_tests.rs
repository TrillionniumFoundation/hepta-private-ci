use std::sync::Arc;
use std::time::Duration;

use codex_protocol::error::CodexErrorDetails;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnAbortedEvent;
use codex_protocol::protocol::WarningEvent;
use futures::FutureExt;
use pretty_assertions::assert_eq;

use super::PublicEventDelivery;
use super::TerminalPublications;
use crate::state::StartTransitionCompletion;

fn terminal(id: &str) -> Event {
    Event {
        id: id.to_owned(),
        msg: EventMsg::TurnAborted(TurnAbortedEvent {
            turn_id: Some(id.to_owned()),
            reason: TurnAbortReason::Interrupted,
            started_at: None,
            completed_at: None,
            duration_ms: None,
        }),
    }
}

#[tokio::test]
async fn cancelled_terminal_receive_retains_the_event_and_fifo_order() {
    let publications = TerminalPublications::default();
    let delivery = PublicEventDelivery::default();
    let owner = StartTransitionCompletion::new();
    let (tx, rx) = async_channel::unbounded();
    let first = terminal("first");
    let second = Event {
        id: "following".to_owned(),
        msg: EventMsg::Warning(WarningEvent {
            message: "after terminal".to_owned(),
        }),
    };
    publications
        .deliver(&tx, first.clone(), Some(Arc::clone(&owner)))
        .await
        .unwrap();
    tx.send(second.clone()).await.unwrap();
    let stopped = futures::future::pending::<()>().boxed().shared();
    assert!(
        tokio::time::timeout(
            Duration::from_millis(20),
            delivery.next(&rx, &publications, stopped.clone()),
        )
        .await
        .is_err()
    );
    assert_eq!(rx.len(), 1);
    assert!(!owner.is_complete());
    owner.complete();
    let received = delivery
        .next(&rx, &publications, stopped.clone())
        .await
        .unwrap();
    assert_eq!(
        serde_json::to_value(received).unwrap(),
        serde_json::to_value(first).unwrap(),
    );
    let received = delivery.next(&rx, &publications, stopped).await.unwrap();
    assert_eq!(
        serde_json::to_value(received).unwrap(),
        serde_json::to_value(second).unwrap(),
    );
    assert!(rx.try_recv().is_err());
}

#[tokio::test]
async fn a_reused_turn_id_keeps_each_exact_owner_and_never_waits_for_a_later_one() {
    let publications = TerminalPublications::default();
    let delivery = PublicEventDelivery::default();
    let first_owner = StartTransitionCompletion::new();
    let later_owner = StartTransitionCompletion::new();
    let (tx, rx) = async_channel::unbounded();
    let event = terminal("same-logical-id");
    for owner in [&first_owner, &later_owner] {
        publications
            .deliver(&tx, event.clone(), Some(Arc::clone(owner)))
            .await
            .unwrap();
    }
    let stopped = futures::future::pending::<()>().boxed().shared();
    first_owner.complete();
    assert!(
        tokio::time::timeout(
            Duration::from_secs(1),
            delivery.next(&rx, &publications, stopped.clone()),
        )
        .await
        .unwrap()
        .is_ok()
    );
    assert!(!later_owner.is_complete());
    assert!(
        tokio::time::timeout(
            Duration::from_millis(20),
            delivery.next(&rx, &publications, stopped.clone()),
        )
        .await
        .is_err()
    );
    later_owner.complete();
    assert!(delivery.next(&rx, &publications, stopped).await.is_ok());
}

#[tokio::test]
async fn loop_death_does_not_certify_or_retire_an_unfinished_owner() {
    let publications = TerminalPublications::default();
    let delivery = PublicEventDelivery::default();
    let owner = StartTransitionCompletion::new();
    let (tx, rx) = async_channel::unbounded();
    let event = terminal("failed-cleanup");
    publications
        .deliver(&tx, event.clone(), Some(Arc::clone(&owner)))
        .await
        .unwrap();
    let stopped = futures::future::ready(()).boxed().shared();
    let error = delivery
        .next(&rx, &publications, stopped.clone())
        .await
        .unwrap_err();
    assert!(matches!(
        error.details(),
        CodexErrorDetails::InternalAgentDied
    ));
    assert!(!owner.is_complete());
    assert!(rx.is_empty());
    owner.complete();
    let received = delivery.next(&rx, &publications, stopped).await.unwrap();
    assert_eq!(
        serde_json::to_value(received).unwrap(),
        serde_json::to_value(event).unwrap(),
    );
}

#[tokio::test]
async fn cancelled_bounded_send_removes_only_its_unsent_receipt() {
    let publications = TerminalPublications::default();
    let delivery = PublicEventDelivery::default();
    let cancelled_owner = StartTransitionCompletion::new();
    let replacement_owner = StartTransitionCompletion::new();
    let (tx, rx) = async_channel::bounded(1);
    let filler = Event {
        id: "capacity".to_owned(),
        msg: EventMsg::Warning(WarningEvent {
            message: "fill the real bounded channel".to_owned(),
        }),
    };
    tx.send(filler).await.unwrap();
    let event = terminal("reused-after-cancel");
    assert!(
        tokio::time::timeout(
            Duration::from_millis(20),
            publications.deliver(&tx, event.clone(), Some(Arc::clone(&cancelled_owner))),
        )
        .await
        .is_err()
    );
    assert_eq!(rx.recv().await.unwrap().id, "capacity");
    assert!(rx.is_empty());
    publications
        .deliver(&tx, event.clone(), Some(Arc::clone(&replacement_owner)))
        .await
        .unwrap();
    replacement_owner.complete();
    let received = tokio::time::timeout(
        Duration::from_secs(1),
        delivery.next(
            &rx,
            &publications,
            futures::future::pending::<()>().boxed().shared(),
        ),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(received.id, event.id);
    assert!(!cancelled_owner.is_complete());
}

#[tokio::test]
async fn ownerless_terminal_cannot_consume_a_later_owned_receipt_with_the_same_id() {
    let publications = TerminalPublications::default();
    let delivery = PublicEventDelivery::default();
    let owner = StartTransitionCompletion::new();
    let (tx, rx) = async_channel::unbounded();
    let event = terminal("ownerless-then-owned");
    publications
        .deliver(&tx, event.clone(), /*completion*/ None)
        .await
        .unwrap();
    publications
        .deliver(&tx, event, Some(Arc::clone(&owner)))
        .await
        .unwrap();
    let stopped = futures::future::pending::<()>().boxed().shared();
    assert!(
        tokio::time::timeout(
            Duration::from_secs(1),
            delivery.next(&rx, &publications, stopped.clone()),
        )
        .await
        .unwrap()
        .is_ok()
    );
    assert!(
        tokio::time::timeout(
            Duration::from_millis(20),
            delivery.next(&rx, &publications, stopped.clone()),
        )
        .await
        .is_err()
    );
    assert!(!owner.is_complete());
    owner.complete();
    assert!(delivery.next(&rx, &publications, stopped).await.is_ok());
}

#[tokio::test]
async fn delayed_producer_pairs_in_actual_publication_order() {
    let publications = TerminalPublications::default();
    let delivery = PublicEventDelivery::default();
    let delayed_owner = StartTransitionCompletion::new();
    let earlier_owner = StartTransitionCompletion::new();
    let (tx, rx) = async_channel::unbounded();
    let (release, gate) = tokio::sync::oneshot::channel::<()>();
    let event = terminal("reordered-producers");
    let mut delayed = Box::pin(async {
        gate.await.unwrap();
        publications
            .deliver(&tx, event.clone(), Some(Arc::clone(&delayed_owner)))
            .await
    });
    assert!(
        tokio::time::timeout(Duration::from_millis(20), delayed.as_mut())
            .await
            .is_err()
    );
    publications
        .deliver(&tx, event.clone(), Some(Arc::clone(&earlier_owner)))
        .await
        .unwrap();
    release.send(()).unwrap();
    delayed.await.unwrap();
    earlier_owner.complete();
    let stopped = futures::future::pending::<()>().boxed().shared();
    assert!(
        tokio::time::timeout(
            Duration::from_secs(1),
            delivery.next(&rx, &publications, stopped.clone()),
        )
        .await
        .unwrap()
        .is_ok()
    );
    assert!(
        tokio::time::timeout(
            Duration::from_millis(20),
            delivery.next(&rx, &publications, stopped.clone()),
        )
        .await
        .is_err()
    );
    delayed_owner.complete();
    assert!(delivery.next(&rx, &publications, stopped).await.is_ok());
}
