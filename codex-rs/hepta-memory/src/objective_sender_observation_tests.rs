use super::test_support::*;
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn equivalent_observation_reack_requires_evidence_and_current_authority() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    sender.mark_send_started(&ticket).await.unwrap();
    let original = ObjectiveSenderObservation::from_original(
        ObjectiveSenderObservationKind::History,
        "{\"state\":\"running\",\"request_id\":1}".to_string(),
    )
    .unwrap();
    assert!(matches!(
        sender
            .retain_distinct_observation(&ticket, &original, |_| {
                Ok(ObjectiveSenderObservationAction::Reacknowledge)
            })
            .await,
        Err(ObjectiveSenderError::ObservationConflict)
    ));
    sender
        .retain_distinct_observation(&ticket, &original, |_| {
            Ok(ObjectiveSenderObservationAction::Append)
        })
        .await
        .unwrap();
    let cut = fixture.store.recovery_anchor().await.unwrap();
    for request_id in 2..72 {
        let next = ObjectiveSenderObservation::from_original(
            ObjectiveSenderObservationKind::History,
            format!("{{\"state\":\"running\",\"request_id\":{request_id}}}"),
        )
        .unwrap();
        sender
            .retain_distinct_observation(&ticket, &next, |snapshot| {
                assert!(snapshot.observations == vec![original.clone()]);
                Ok(ObjectiveSenderObservationAction::Reacknowledge)
            })
            .await
            .unwrap();
    }
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), cut);
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    assert!(matches!(
        sender
            .retain_distinct_observation(&ticket, &original, |_| {
                Ok(ObjectiveSenderObservationAction::Reacknowledge)
            })
            .await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Accept;
    fixture.verifier.revoked.store(true, Ordering::SeqCst);
    assert!(matches!(
        sender
            .retain_distinct_observation(&ticket, &original, |_| {
                panic!("revoked owner cannot reach observation classification")
            })
            .await,
        Err(ObjectiveSenderError::Writer(_))
    ));
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), cut);
}
