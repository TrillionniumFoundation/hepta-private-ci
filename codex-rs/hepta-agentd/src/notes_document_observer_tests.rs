use super::*;
use crate::AgentdNotesChannel;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::ProductionNotesTarget;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::error::Error;
use std::io;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

#[test]
fn notes_objective_private_document_observer_correlates_fresh_nonce_and_never_writes_effect()
-> Result<(), Box<dyn Error>> {
    let (effect, mut application_effect) = UnixStream::pair()?;
    let (recovery, application) = UnixDatagram::pair()?;
    application.set_read_timeout(Some(Duration::from_secs(5)))?;
    application_effect.set_nonblocking(true)?;
    let identity = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let target = ProductionNotesTarget::new(
        identity.clone(),
        Arc::new(AgentdNotesChannel::from_private_channels(effect, recovery)?),
    )?;
    let observer = AgentdNotesDocumentObserver::new(target.document_observer());
    let observed_target = identity.clone();
    let peer = std::thread::spawn(move || -> Result<(), String> {
        let mut prior_nonce = Value::Null;
        for revision in 1..=2 {
            let mut bytes = [0_u8; 8192];
            let size = application
                .recv(&mut bytes)
                .map_err(|error| error.to_string())?;
            let request: Value =
                serde_json::from_slice(&bytes[..size]).map_err(|error| error.to_string())?;
            assert_eq!(request["action"], "read_document_state");
            assert_eq!(
                request["target"],
                serde_json::to_value(&observed_target).unwrap()
            );
            assert_ne!(request["request_id"], prior_nonce);
            let mut response = json!({"schema_version":1,"action":"document_state",
                "target":observed_target,"request_id":prior_nonce,"revision":revision,
                "text_sha256":Sha256Digest::for_bytes(b"current document").as_str(),
                "receipt_pending":revision == 2});
            application
                .send(&serde_json::to_vec(&response).unwrap())
                .map_err(|error| error.to_string())?;
            response["request_id"] = request["request_id"].clone();
            application
                .send(&serde_json::to_vec(&response).unwrap())
                .map_err(|error| error.to_string())?;
            prior_nonce = request["request_id"].clone();
        }
        Ok(())
    });
    for revision in 1..=2 {
        assert_eq!(
            observer.observe_document()?,
            NotesDocumentState {
                target: identity.clone(),
                revision,
                text_sha256: Sha256Digest::for_bytes(b"current document"),
                receipt_pending: revision == 2,
            }
        );
    }
    assert_eq!(
        application_effect.read(&mut [0_u8; 1]).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    peer.join().expect("document state peer")?;
    Ok(())
}

#[test]
fn notes_objective_recovery_handle_retains_no_effect_descriptor_and_correlates_discovery()
-> Result<(), Box<dyn Error>> {
    use codex_hepta_memory::NotesPrivateChannel;
    let (effect, mut application_effect) = UnixStream::pair()?;
    let (recovery, application) = UnixDatagram::pair()?;
    let channel = AgentdNotesChannel::from_private_channels(effect, recovery)?;
    let recovery_only = channel.recovery_handle()?;
    drop(channel);
    application_effect.set_read_timeout(Some(Duration::from_secs(1)))?;
    assert_eq!(
        application_effect.read(&mut [0_u8; 1])?,
        0,
        "narrow capability must not retain the effect descriptor"
    );
    let request = json!({"schema_version":1,"action":"read_previous_receipt",
        "target":{"session_instance":"1".repeat(32),"task_id":1,"incarnation":"2".repeat(32)},
        "request_id":"3".repeat(32)});
    let expected = request.clone();
    let peer = std::thread::spawn(move || -> Result<(), String> {
        application
            .set_read_timeout(Some(Duration::from_secs(2)))
            .map_err(|error| error.to_string())?;
        let mut bytes = [0_u8; 8192];
        let size = application
            .recv(&mut bytes)
            .map_err(|error| error.to_string())?;
        assert_eq!(
            serde_json::from_slice::<Value>(&bytes[..size]).unwrap(),
            expected
        );
        let mut response = json!({"schema_version":1,"action":"previous_receipt",
            "target":expected["target"],"request_id":"4".repeat(32),"pending_receipt":null});
        application
            .send(&serde_json::to_vec(&response).unwrap())
            .map_err(|error| error.to_string())?;
        response["request_id"] = expected["request_id"].clone();
        application
            .send(&serde_json::to_vec(&response).unwrap())
            .map_err(|error| error.to_string())?;
        Ok(())
    });
    let observed: Value =
        serde_json::from_slice(&recovery_only.exchange(&serde_json::to_vec(&request)?)?)?;
    assert_eq!(observed["request_id"], request["request_id"]);
    assert!(
        recovery_only
            .exchange(br#"{"schema_version":1,"action":"replace_note"}"#)
            .is_err()
    );
    peer.join().expect("previous receipt discovery peer")?;
    Ok(())
}
