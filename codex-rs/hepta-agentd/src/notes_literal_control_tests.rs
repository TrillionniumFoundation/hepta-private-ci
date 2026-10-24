//! Original SQLite sender and real Unix socket I/O. The checkpoint and reply
//! below are explicit protocol fixtures, not a production Root qualification.

use super::*;
use crate::AgentdNotesObservationRetention;
use crate::AgentdNotesPreparedObjective;
use crate::AgentdNotesSubmissionState;
use crate::notes_literal_control::submit_original;
use codex_hepta_memory::ObjectiveSenderTicket;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;

#[path = "notes_literal_receipts_tests.rs"]
mod receipt_tests;

async fn retained(
    config: &AgentdConfig,
    sender: &ProductionObjectiveSender<CheckpointProbe>,
    path: &std::path::Path,
    expected_pid: u32,
) -> Result<(ObjectiveSenderTicket, AuthBusObjectiveIngress), Box<dyn Error>> {
    let digest = "11".repeat(32);
    let ingress = AuthBusObjectiveIngress {
        issuer_id: "explicit-notes-control-fixture".into(), key_epoch: 1,
        message_id: "explicit-control-message".into(), sequence: 1,
        expires_at_ms: EXPIRES * 1_000, signature_hex: "ab".repeat(64),
        body: AuthBusObjectiveBody {
            spawn_generation: config.identity().spawn_generation, run_id: "explicit-notes-control-run".into(),
            objective_revision: 1, source_envelope_json: "{\"fixture\":\"not an authenticated Objective\"}".into(),
            runtime_body_digest: digest.clone(), preference_state_digest: digest.clone(),
            model_tuple_digest: digest.clone(), prompt_registry_digest: digest.clone(),
            artifact_set_digest: digest, authority_epoch: 13,
        },
    };
    let request = ObjectiveSenderRequest::from_original(serde_json::to_string(&ingress)?, ObjectiveSenderOrigin {
        agent_id: config.identity().agent_id.clone(), spawn_generation: config.identity().spawn_generation,
        request_id: 7, expected_peer_uid: std::fs::metadata(path)?.uid(),
        expected_peer_pid: expected_pid, endpoint_identity: path.to_string_lossy().into_owned(),
    })?;
    Ok((sender.retain_before_send(request).await?, ingress))
}

#[tokio::test]
async fn notes_literal_control_wrong_peer_sends_zero_bytes_and_never_rearms_original_ticket()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, _probes, _issuer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let sender = Arc::new(config.original_objective_sender(Arc::new(CheckpointProbe::default()), Duration::from_secs(2))?);
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("control.sock");
    let listener = UnixListener::bind(&path)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let (ticket, ingress) = retained(&config, &sender, &path, std::process::id() + 1).await?;
    let original = ticket.request().clone();
    let peer = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).unwrap();
        bytes
    });
    let observed = submit_original(Arc::clone(&sender), ticket, ingress, Duration::from_secs(2)).await?;
    assert_eq!(observed.state, AgentdNotesSubmissionState::NotSent { issue: "objective_peer_denied" });
    assert_eq!(observed.retention, AgentdNotesObservationRetention::Acknowledged);
    assert!(peer.join().unwrap().is_empty());
    let recovered = sender.recover_pending(original.clone()).await?;
    assert!(matches!(sender.mark_send_started(&recovered).await, Err(ObjectiveSenderError::SendPermissionUnavailable)));
    assert!(AgentdNotesPreparedObjective::Retained(original).submit_once(Duration::from_secs(1)).await.is_err());
    Ok(())
}

#[tokio::test]
async fn notes_literal_control_lost_reply_retains_one_exact_unknown_observation_without_resubmit()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, _probes, _issuer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let sender = Arc::new(config.original_objective_sender(Arc::new(CheckpointProbe::default()), Duration::from_secs(2))?);
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("control.sock");
    let listener = UnixListener::bind(&path)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let (ticket, ingress) = retained(&config, &sender, &path, std::process::id()).await?;
    let original = ticket.request().clone();
    let peer = std::thread::spawn(move || {
        let (stream, _) = listener.accept().unwrap();
        stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        let mut line = String::new();
        BufReader::new(stream).read_line(&mut line).unwrap();
        line
    });
    let observed = submit_original(Arc::clone(&sender), ticket, ingress, Duration::from_secs(2)).await?;
    assert!(matches!(observed.state, AgentdNotesSubmissionState::SubmitUnknown { .. }));
    assert_eq!(observed.retention, AgentdNotesObservationRetention::Acknowledged);
    let sent = peer.join().unwrap();
    let wire: crate::AgentdRequest = serde_json::from_str(&sent)?;
    assert_eq!(wire.request_id, original.origin().request_id);
    assert!(matches!(wire.method, crate::AgentdMethod::ObjectiveStart { .. }));
    let recovered = sender.recover_pending(original).await?;
    let snapshot = sender.snapshot_acknowledged(&recovered).await?;
    assert_eq!(snapshot.observations.len(), 1);
    let metadata: serde_json::Value = serde_json::from_slice(snapshot.observations[0].exact_original())?;
    assert_eq!(metadata["bytes_written"], sent.len());
    assert_eq!(metadata["request_frame_bytes"], sent.len());
    assert_eq!(metadata["status"]["type"], "submit_unknown");
    assert!(matches!(sender.mark_send_started(&recovered).await, Err(ObjectiveSenderError::SendPermissionUnavailable)));
    Ok(())
}
