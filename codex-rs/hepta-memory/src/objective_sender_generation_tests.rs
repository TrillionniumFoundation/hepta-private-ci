//! Process binding and whole-owner ACK do not manufacture Objective records.
use super::test_support::*;
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn owner_cut_acknowledgement_creates_no_request_or_permission() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let before = fixture.store.recovery_anchor().await.unwrap();
    sender.acknowledge_owner_cut().await.unwrap();
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), before);
    assert_eq!(fixture.checkpoint.seen.lock().unwrap()[0].0, before);
    assert!(
        sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await
            .unwrap()
            .requests
            .is_empty()
    );
    assert!(matches!(
        sender.recover_pending(request()).await,
        Err(ObjectiveSenderError::Missing)
    ));
}

#[tokio::test]
async fn writer_accessor_cannot_choose_a_different_sender_process_generation() {
    let fixture = Fixture::new().await;
    assert!(matches!(
        fixture.writer.objective_sender_for_spawn_generation(
            fixture.checkpoint.clone(),
            Duration::from_secs(2),
            3
        ),
        Err(ObjectiveSenderError::Writer(
            ProductionWriterError::AuthorityRejected(_)
        ))
    ));
    assert!(fixture.checkpoint.seen.lock().unwrap().is_empty());
}

#[tokio::test]
async fn owner_cut_unknown_fences_original_writer_without_retaining_a_request() {
    let fixture = Fixture::new().await;
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    let sender = fixture.sender();
    assert!(matches!(
        sender.acknowledge_owner_cut().await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    assert!(fixture.writer.checkpoint_fenced());
    assert!(matches!(
        fixture.writer.admit("after-unknown", "test", "{}").await,
        Err(ProductionWriterError::CheckpointFenced)
    ));
    assert!(
        sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await
            .unwrap()
            .requests
            .is_empty()
    );
}
