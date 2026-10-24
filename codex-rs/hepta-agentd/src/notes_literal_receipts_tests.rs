//! Explicit metadata fixtures over the real retained owner. These test parser
//! and immutable recovery invariants; they are not production admission proofs.
use super::*;
use crate::notes_literal_receipts as receipts;
use crate::notes_ui_wire::ObjectiveStage;
use codex_hepta_agent_protocol::ObjectiveAdmissionPublication;
use codex_hepta_agent_protocol::ObjectivePublicationOutcome;
use codex_hepta_memory::ObjectiveSenderObservation;
use codex_hepta_memory::ObjectiveSenderObservationKind;

fn publication(request: &ObjectiveSenderRequest) -> ObjectiveAdmissionPublication {
    let source = request.identity();
    ObjectiveAdmissionPublication {
        run_id: source.run_id.clone(), original_spawn_generation: source.body_spawn_generation,
        issuer_id: source.issuer_id.clone(), key_epoch: source.key_epoch,
        message_id: source.message_id.clone(), message_sequence: source.sequence,
        expires_at_ms: source.expires_at_ms, signed_body_digest: source.signed_body_sha256.to_string(),
        profile_digest: "22".repeat(32), publication_sequence: 1, publication_digest: "33".repeat(32),
        chain_digest: "44".repeat(32), outcome: ObjectivePublicationOutcome::Compiled {
            objective_digest: "55".repeat(32), hard_constraint_digest: "66".repeat(32),
        },
    }
}

#[tokio::test]
async fn notes_literal_recovery_checks_identity_and_never_erases_first_publication()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, _probes, _issuer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let sender = config.original_objective_sender(Arc::new(CheckpointProbe::default()), Duration::from_secs(2))?;
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("control.sock");
    let _listener = UnixListener::bind(&path)?;
    let (ticket, _) = retained(&config, &sender, &path, std::process::id()).await?;
    let request = ticket.request().clone();
    sender.mark_send_started(&ticket).await?;
    let unknown = crate::notes_literal_observation::retained_observation(&request,
        &AgentdNotesSubmissionState::SubmitUnknown { issue: "objective_read_failed" }, 100, 100).unwrap();
    sender.retain_observation(&ticket, &unknown).await?;
    let record = receipts::History {
        schema: 1, original_sha256: request.identity().original_sha256.to_string(),
        query: receipts::identity(&request, request.origin()), requested_anchor: None,
        bytes_written: 100, request_frame_bytes: Some(100), status: receipts::HistoryStatus::HistoricalPublication {
            publication: Box::new(publication(&request)), response_generation: request.origin().spawn_generation,
        },
    };
    let known = ObjectiveSenderObservation::from_original(ObjectiveSenderObservationKind::History, serde_json::to_string(&record)?)?;
    sender.retain_observation(&ticket, &known).await?;
    let recovered = sender.recover_pending(request.clone()).await?;
    let mut snapshot = sender.snapshot_acknowledged(&recovered).await?;
    assert_eq!(receipts::project(&request, &snapshot).unwrap().stage, ObjectiveStage::Admitted);
    let later_unknown = receipts::History { status: receipts::HistoryStatus::Unknown { issue: "owner_unavailable".into() }, ..record };
    snapshot.observations.push(ObjectiveSenderObservation::from_original(ObjectiveSenderObservationKind::History,
        serde_json::to_string(&later_unknown)?)?);
    assert_eq!(receipts::project(&request, &snapshot).unwrap().stage, ObjectiveStage::Admitted);
    let mut replaced = publication(&request);
    replaced.publication_sequence = 2;
    let conflicting = receipts::History { status: receipts::HistoryStatus::HistoricalPublication {
        publication: Box::new(replaced), response_generation: request.origin().spawn_generation,
    }, ..later_unknown };
    snapshot.observations.push(ObjectiveSenderObservation::from_original(ObjectiveSenderObservationKind::History,
        serde_json::to_string(&conflicting)?)?);
    assert!(receipts::project(&request, &snapshot).is_err());
    let mut changed_body = publication(&request);
    changed_body.signed_body_digest = "77".repeat(32);
    assert!(receipts::publication(&request, &changed_body).is_err());
    assert!(matches!(sender.mark_send_started(&recovered).await, Err(ObjectiveSenderError::SendPermissionUnavailable)));
    Ok(())
}
