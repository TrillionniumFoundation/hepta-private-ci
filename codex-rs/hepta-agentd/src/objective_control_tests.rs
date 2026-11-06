use super::fixture::CheckpointMode;
use super::objective_control_fixture::ControlFixture;
use super::objective_control_fixture::ReplyDelivery;
use super::objective_control_fixture::TestResult;
use crate::AgentdObjectiveClientError;
use crate::ObjectiveAdmissionOutcome;
use crate::ObjectiveClientMode;
use codex_hepta_memory::ObjectiveSenderError;
use codex_hepta_memory::ObjectiveSenderRetainedPosition;
use pretty_assertions::assert_eq;
use std::sync::atomic::Ordering;

#[tokio::test]
async fn repeated_status_reads_preserve_capacity_and_terminal_bytes_across_client_recovery()
-> TestResult {
    let mut fixture = ControlFixture::new(
        "desktop.control.polling",
        "Observe one original request",
        ReplyDelivery::Complete,
    )
    .await?;
    let mut client = fixture.client(ObjectiveClientMode::Initial)?;
    client.submit_once().await?;
    let first = client.observe_current().await?.1.ok_or("run missing")?;
    let sender = fixture.take_attachment()?.original_sender;
    let ticket = sender.recover_pending(fixture.original.clone()).await?;
    let before = fixture.host.writer().recovery_anchor().await?;
    for _ in 0..70 {
        assert_eq!(client.observe_current().await?.1, Some(first.clone()));
    }
    assert_eq!(fixture.host.writer().recovery_anchor().await?, before);
    drop(client);
    let mut recovered = fixture.client(ObjectiveClientMode::Recovered)?;
    assert_eq!(recovered.observe_current().await?.1, Some(first));
    assert_eq!(fixture.host.writer().recovery_anchor().await?, before);
    recovered
        .cancel_current("Owner cancellation".to_string())
        .await?;
    let terminal = recovered
        .observe_current()
        .await?
        .1
        .ok_or("terminal missing")?;
    assert_eq!(terminal.phase, crate::AgentRunPhase::Cancelled);
    assert!(terminal.terminal_observed);
    let retained = sender.snapshot_acknowledged(&ticket).await?;
    let retained_replies: Vec<crate::AgentdResponse> = retained
        .observations
        .iter()
        .map(|value| serde_json::from_slice(value.exact_original()))
        .collect::<Result<_, _>>()?;
    assert_eq!(retained_replies.len(), 5);
    assert!(retained_replies.iter().any(|response| {
        response.payload
            == crate::AgentdPayload::RunStatus {
                run: Some(terminal.clone()),
            }
    }));
    let terminal_cut = fixture.host.writer().recovery_anchor().await?;
    drop(recovered);
    let mut reopened = fixture.client(ObjectiveClientMode::Recovered)?;
    assert_eq!(reopened.observe_current().await?.1, Some(terminal));
    assert_eq!(fixture.host.writer().recovery_anchor().await?, terminal_cut);
    assert!(matches!(
        reopened.submit_once().await,
        Err(AgentdObjectiveClientError::AlreadyAttempted)
    ));
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.cancellations.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.probes.target.effects.load(Ordering::SeqCst), 0);
    drop(reopened);
    drop(sender);
    fixture.finish().await
}

#[tokio::test]
async fn original_sender_reaches_real_control_admission_history_and_cancellation_once() -> TestResult
{
    let mut fixture = ControlFixture::new(
        "desktop.control.real",
        "Read the current task",
        ReplyDelivery::Complete,
    )
    .await?;
    assert!(fixture.state.automation_admission_ready()?);
    let lifecycle_generation = fixture.state.current_generation()?;
    assert_ne!(lifecycle_generation, fixture.identity.spawn_generation);
    let mut client = fixture.client(ObjectiveClientMode::Initial)?;
    let accepted = client.submit_once().await?;
    assert!(matches!(
        accepted,
        crate::ObjectiveStartOutcome::Admitted { .. }
    ));
    assert!(matches!(
        client.submit_once().await,
        Err(AgentdObjectiveClientError::AlreadyAttempted)
    ));
    let history = client.refresh().await?;
    assert_eq!(history.current_generation(), lifecycle_generation);
    let ObjectiveAdmissionOutcome::Published { publication } = history.latest else {
        panic!("real original journal must retain admission")
    };
    assert_eq!(publication.run_id, fixture.original.identity().run_id);
    assert_eq!(
        publication.signed_body_digest,
        fixture.original.identity().signed_body_sha256.as_str()
    );
    let current = client.current_run().await?;
    assert_eq!(current.phase, crate::AgentRunPhase::Admitted);
    assert_eq!(current.generation, lifecycle_generation);
    let cancelled = client
        .cancel_current("Owner cancellation".to_string())
        .await?;
    assert_eq!(
        cancelled.disposition,
        crate::AgentCancellationDisposition::CancelledBeforeDispatch
    );
    assert!(matches!(
        client
            .cancel_current("Owner cancellation".to_string())
            .await,
        Err(AgentdObjectiveClientError::AlreadyAttempted)
    ));
    let after = client.refresh().await?;
    assert_eq!(after.retained_publication, Some(*publication));
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.probes.target.effects.load(Ordering::SeqCst), 0);
    drop(client);
    fixture.finish().await
}

#[tokio::test]
async fn real_control_lost_ack_recovers_exact_admission_without_replaying_submission() -> TestResult
{
    let mut fixture = ControlFixture::new(
        "desktop.control.lost-ack",
        "Read one task",
        ReplyDelivery::DropFirstSubmissionAck,
    )
    .await?;
    let original = fixture.original.clone();
    let mut client = fixture.client(ObjectiveClientMode::Initial)?;
    assert!(client.submit_once().await.is_err());
    assert!(matches!(
        client.submit_once().await,
        Err(AgentdObjectiveClientError::AlreadyAttempted)
    ));
    drop(client);
    let mut recovered = fixture.client(ObjectiveClientMode::Recovered)?;
    assert_eq!(
        recovered.original().exact_original(),
        original.exact_original()
    );
    assert!(matches!(
        recovered.submit_once().await,
        Err(AgentdObjectiveClientError::AlreadyAttempted)
    ));
    let history = recovered.refresh().await?;
    assert!(matches!(
        history.latest,
        ObjectiveAdmissionOutcome::Published { .. }
    ));
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.probes.target.effects.load(Ordering::SeqCst), 0);
    drop(recovered);
    fixture.finish().await
}

#[tokio::test]
async fn original_checkpoint_refusal_prevents_transport_and_recovery_keeps_unknown() -> TestResult {
    let mut fixture = ControlFixture::new(
        "desktop.control.no-checkpoint",
        "Read safely",
        ReplyDelivery::Complete,
    )
    .await?;
    *fixture.probes.checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    let mut client = fixture.client(ObjectiveClientMode::Initial)?;
    assert!(client.submit_once().await.is_err());
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    drop(client);
    *fixture.probes.checkpoint.mode.lock().unwrap() = CheckpointMode::Accept;
    let mut recovered = fixture.client(ObjectiveClientMode::Recovered)?;
    assert!(matches!(
        recovered.refresh().await?.latest,
        ObjectiveAdmissionOutcome::Unknown { .. }
    ));
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    let mut competing = fixture.client(ObjectiveClientMode::Initial)?;
    assert!(matches!(
        competing.submit_once().await,
        Err(AgentdObjectiveClientError::Owner(
            ObjectiveSenderError::AlreadyRetained
        ))
    ));
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    drop(competing);
    drop(recovered);
    fixture.finish().await
}

#[tokio::test]
async fn local_cancel_recovers_permanent_fence_without_a_network_request() -> TestResult {
    let mut fixture = ControlFixture::new(
        "desktop.control.local-cancel",
        "Do not dispatch",
        ReplyDelivery::Complete,
    )
    .await?;
    let mut client = fixture.client(ObjectiveClientMode::Initial)?;
    client.cancel_local().await?;
    assert!(client.acknowledged_local_cancellation().await?);
    assert!(matches!(
        client.submit_once().await,
        Err(AgentdObjectiveClientError::AlreadyAttempted)
    ));
    drop(client);
    let mut recovered = fixture.client(ObjectiveClientMode::Recovered)?;
    assert!(recovered.acknowledged_local_cancellation().await?);
    assert!(recovered.cancel_local().await.is_err());
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    drop(recovered);
    fixture.finish().await
}

#[tokio::test]
async fn closing_original_window_retires_callbacks_before_retention_or_transport() -> TestResult {
    let mut fixture = ControlFixture::new(
        "desktop.control.closed",
        "Closed window",
        ReplyDelivery::Complete,
    )
    .await?;
    let mut client = fixture.client(ObjectiveClientMode::Initial)?;
    client.window().close();
    assert!(matches!(
        client.submit_once().await,
        Err(AgentdObjectiveClientError::Retired)
    ));
    assert!(matches!(
        client.refresh().await,
        Err(AgentdObjectiveClientError::Retired)
    ));
    let sender = fixture.take_attachment()?.original_sender;
    assert!(
        sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await?
            .requests
            .is_empty()
    );
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    drop(sender);
    drop(client);
    fixture.finish().await
}

#[tokio::test]
async fn actual_kernel_peer_mismatch_cannot_write_a_control_frame() -> TestResult {
    let mut fixture = ControlFixture::new(
        "desktop.control.wrong-peer",
        "Authenticate the owner",
        ReplyDelivery::Complete,
    )
    .await?;
    let mut origin = fixture.original.origin().clone();
    origin.expected_peer_pid += 1;
    let original = codex_hepta_memory::ObjectiveSenderRequest::from_original(
        String::from_utf8(fixture.original.exact_original().to_vec())?,
        origin,
    )?;
    let mut peer = fixture.peer();
    peer.pid += 1;
    let mut client = fixture.transport()?.bind_original_objective(
        fixture.take_attachment()?.original_sender,
        original,
        peer,
        ObjectiveClientMode::Initial,
    )?;
    assert!(matches!(
        client.submit_once().await,
        Err(AgentdObjectiveClientError::Binding)
    ));
    assert!(matches!(
        client.submit_once().await,
        Err(AgentdObjectiveClientError::AlreadyAttempted)
    ));
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    drop(client);
    fixture.finish().await
}

#[tokio::test]
async fn a_multiline_original_is_rejected_before_retention_in_the_line_framed_profile() -> TestResult
{
    let mut fixture = ControlFixture::new(
        "desktop.control.multiline",
        "Keep exact bytes",
        ReplyDelivery::Complete,
    )
    .await?;
    let ingress: crate::AuthBusObjectiveIngress =
        serde_json::from_slice(fixture.original.exact_original())?;
    let original = codex_hepta_memory::ObjectiveSenderRequest::from_original(
        serde_json::to_string_pretty(&ingress)?,
        fixture.original.origin().clone(),
    );
    // The original production input boundary already rejects line breaks.
    // Keep that earlier refusal; never normalize or relax it to reach transport.
    assert!(matches!(
        original,
        Err(codex_hepta_memory::ObjectiveSenderInputError::Malformed)
    ));
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    let sender = fixture.take_attachment()?.original_sender;
    assert!(
        sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await?
            .requests
            .is_empty()
    );
    drop(sender);
    fixture.finish().await
}
